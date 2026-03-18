from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

import requests

from app.utils.app_paths import ensure_dir, resolve_data_path


class TileProxyService:
    _PROVIDERS: Dict[str, str] = {
        "osm": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "carto_light": "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        "carto_dark": "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "satellite": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    }

    _TILE_RE = re.compile(r"^/tiles/([a-z_]+)/(\d+)/(\d+)/(\d+)\.(png|jpg|jpeg)$")

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        timeout_sec: int = 12,
        cache_size: int = 800,
        startup_wait_sec: float = 1.5,
    ):
        self._host = host
        self._port = port
        self._timeout_sec = timeout_sec
        self._cache_size = cache_size
        self._startup_wait_sec = max(0.2, float(startup_wait_sec))
        self._debug = os.environ.get("COMP_DEBUG_MAP", "").strip() == "1"
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._cache: "OrderedDict[str, Tuple[bytes, str]]" = OrderedDict()
        self._cache_lock = threading.Lock()

        self._disk_cache_dir = str(ensure_dir(resolve_data_path("tiles_cache")))

    def _get_disk_cache_path(self, cache_key: str) -> str:
        digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:16]
        safe_prefix = re.sub(r"[^A-Za-z0-9._-]+", "_", cache_key).strip("._")
        if not safe_prefix:
            safe_prefix = "tile"
        safe_name = f"{safe_prefix[:80]}_{digest}.bin"
        return os.path.join(self._disk_cache_dir, safe_name)

    def _read_from_disk(self, cache_key: str) -> Optional[Tuple[bytes, str]]:
        path = self._get_disk_cache_path(cache_key)
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    content_type = f.readline().decode('utf-8').strip()
                    data = f.read()
                    return data, content_type
            except Exception:
                return None
        return None

    def _write_to_disk(self, cache_key: str, data: bytes, content_type: str):
        path = self._get_disk_cache_path(cache_key)
        try:
            with open(path, "wb") as f:
                f.write((content_type + "\n").encode('utf-8'))
                f.write(data)
        except Exception:
            pass

    def start(self) -> str:
        if self._server is not None:
            host, port = self._server.server_address
            return f"http://{host}:{port}"

        handler_cls = self._build_handler()
        self._server = ThreadingHTTPServer((self._host, self._port), handler_cls)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._server.server_address
        base_url = f"http://{host}:{port}"
        self._wait_until_ready(base_url)
        return base_url

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.shutdown()
        except Exception:
            pass
        try:
            self._server.server_close()
        except Exception:
            pass
        self._server = None
        self._thread = None

    def _wait_until_ready(self, base_url: str) -> None:
        deadline = time.monotonic() + self._startup_wait_sec
        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            try:
                resp = requests.get(f"{base_url}/health", timeout=0.6)
                if int(getattr(resp, "status_code", 0)) == 200:
                    return
            except Exception as exc:
                last_error = exc
            time.sleep(0.05)
        if self._debug and last_error is not None:
            print(f"[MAP PROXY] healthcheck warning: {last_error}", flush=True)

    def _build_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer._handle_request(self, head_only=False)

            def do_HEAD(self):
                outer._handle_request(self, head_only=True)

            def log_message(self, _format, *_args):
                return

        return Handler

    def _handle_request(self, handler: BaseHTTPRequestHandler, *, head_only: bool) -> None:
        path = urlparse(handler.path).path
        if path in ("/health", "/healthz"):
            self._send(handler, 200, b"ok", "text/plain; charset=utf-8", head_only=head_only)
            return

        if self._debug and path.startswith("/tiles/"):
            print(f"[MAP PROXY] request {path}", flush=True)

        match = self._TILE_RE.match(path)
        if not match:
            if self._debug and path.startswith("/tiles/"):
                print(f"[MAP PROXY] reject path={path} status=404", flush=True)
            self._send(handler, 404, b"not found", "text/plain; charset=utf-8", head_only=head_only)
            return

        provider, z, x, y, _ext = match.groups()
        template = self._PROVIDERS.get(provider)
        if not template:
            if self._debug:
                print(f"[MAP PROXY] unknown provider={provider} status=404", flush=True)
            self._send(handler, 404, b"provider not found", "text/plain; charset=utf-8", head_only=head_only)
            return

        remote_url = template.format(z=z, x=x, y=y)
        cached = self._cache_get(remote_url)
        if cached is not None:
            body, content_type = cached
            if self._debug:
                print(f"[MAP PROXY] cache-hit provider={provider} status=200 len={len(body)}", flush=True)
            self._send(handler, 200, body, content_type, head_only=head_only)
            return

        headers = {"User-Agent": "CompensacoesApp/1.0 (TileProxy)"}
        try:
            response = requests.get(remote_url, timeout=self._timeout_sec, headers=headers)
        except Exception as exc:
            if self._debug:
                print(f"[MAP PROXY] upstream exception provider={provider} url={remote_url} err={exc}", flush=True)
            msg = f"tile proxy upstream error: {exc}".encode("utf-8", errors="ignore")
            self._send(handler, 502, msg, "text/plain; charset=utf-8", head_only=head_only)
            return

        status = int(getattr(response, "status_code", 502))
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        body = response.content if status == 200 else b""
        if status == 200 and body:
            self._cache_put(remote_url, body, content_type)
            if self._debug:
                print(f"[MAP PROXY] upstream-ok provider={provider} status=200 len={len(body)}", flush=True)
        elif self._debug:
            print(
                f"[MAP PROXY] upstream non-200 provider={provider} status={status} url={remote_url}",
                flush=True,
            )

        self._send(handler, status, body, content_type, head_only=head_only)

    def _cache_get(self, key: str) -> Optional[Tuple[bytes, str]]:
        with self._cache_lock:
            value = self._cache.get(key)
            if value is not None:
                self._cache.move_to_end(key)
                return value
                
        # Fallback para o disco se nao estiver na memoria
        disk_val = self._read_from_disk(key)
        if disk_val:
            with self._cache_lock:
                self._cache[key] = disk_val
                if len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            return disk_val
            
        return None

    def _cache_put(self, key: str, body: bytes, content_type: str) -> None:
        with self._cache_lock:
            self._cache[key] = (body, content_type)
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        self._write_to_disk(key, body, content_type)

    @staticmethod
    def _send(
        handler: BaseHTTPRequestHandler,
        status: int,
        body: bytes,
        content_type: str,
        *,
        head_only: bool,
    ) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Content-Length", str(len(body)))
        if status == 200:
            handler.send_header("Cache-Control", "public, max-age=86400")
        handler.end_headers()
        if not head_only and body:
            handler.wfile.write(body)
