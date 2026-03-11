from __future__ import annotations

import os
import re
import threading
from collections import OrderedDict
from typing import Dict, Optional, Tuple

import requests
from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtWebEngineCore import (
    QWebEngineProfile,
    QWebEngineUrlRequestJob,
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
)


TILE_SCHEME_NAME = b"compmap"
_INSTALLED_HANDLERS: Dict[int, "TileSchemeHandler"] = {}


def register_tile_scheme() -> None:
    existing = QWebEngineUrlScheme.schemeByName(TILE_SCHEME_NAME)
    if existing.name():
        return

    scheme = QWebEngineUrlScheme(TILE_SCHEME_NAME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Path)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
        | QWebEngineUrlScheme.Flag.CorsEnabled
        | QWebEngineUrlScheme.Flag.FetchApiAllowed
        | QWebEngineUrlScheme.Flag.ContentSecurityPolicyIgnored
    )
    QWebEngineUrlScheme.registerScheme(scheme)


def install_tile_scheme(profile: Optional[QWebEngineProfile] = None) -> "TileSchemeHandler":
    target_profile = profile or QWebEngineProfile.defaultProfile()
    profile_key = id(target_profile)
    existing = _INSTALLED_HANDLERS.get(profile_key)
    if existing is not None:
        return existing

    handler = TileSchemeHandler(target_profile)
    target_profile.installUrlSchemeHandler(TILE_SCHEME_NAME, handler)
    _INSTALLED_HANDLERS[profile_key] = handler
    return handler


class TileSchemeHandler(QWebEngineUrlSchemeHandler):
    _PROVIDERS: Dict[str, str] = {
        "osm": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "carto_light": "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        "carto_dark": "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "satellite": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    }
    _PATH_RE = re.compile(r"^/([a-z_]+)/(\d+)/(\d+)/(\d+)\.(png|jpg|jpeg)$")

    def __init__(self, parent=None, *, timeout_sec: int = 12, cache_size: int = 800):
        super().__init__(parent)
        self._timeout_sec = timeout_sec
        self._cache_size = cache_size
        self._cache: "OrderedDict[str, Tuple[bytes, str]]" = OrderedDict()
        self._cache_lock = threading.Lock()
        self._session = requests.Session()
        self._debug = os.environ.get("COMP_DEBUG_MAP", "").strip() == "1"

    def requestStarted(self, request: QWebEngineUrlRequestJob) -> None:
        try:
            url = request.requestUrl()
            path = url.path() or ""

            match = self._PATH_RE.match(path)
            if not match:
                if self._debug:
                    print(f"[MAP SCHEME] invalid request path={path}", flush=True)
                request.fail(QWebEngineUrlRequestJob.Error.UrlInvalid)
                return

            provider, z, x, y, ext = match.groups()
            status, body, content_type, remote_url = self._fetch(provider, z, x, y)

            if status != 200 or not body:
                if self._debug:
                    print(
                        f"[MAP SCHEME] miss provider={provider} status={status} remote={remote_url}",
                        flush=True,
                    )
                request.fail(
                    QWebEngineUrlRequestJob.Error.UrlNotFound
                    if status == 404
                    else QWebEngineUrlRequestJob.Error.RequestFailed
                )
                return

            mime = (content_type or "").split(";")[0].strip().lower()
            if not mime:
                mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"

            buffer = QBuffer(request)
            buffer.setData(QByteArray(body))
            buffer.open(QIODevice.ReadOnly)
            request.reply(mime.encode("ascii", errors="ignore"), buffer)
        except Exception as exc:
            if self._debug:
                print(f"[MAP SCHEME] exception: {exc}", flush=True)
            request.fail(QWebEngineUrlRequestJob.Error.RequestFailed)

    def _fetch(self, provider: str, z: str, x: str, y: str) -> Tuple[int, bytes, str, str]:
        template = self._PROVIDERS.get(provider)
        if not template:
            return 404, b"", "text/plain", ""

        remote_url = template.format(z=z, x=x, y=y)
        cached = self._cache_get(remote_url)
        if cached is not None:
            body, content_type = cached
            if self._debug:
                print(f"[MAP SCHEME] cache-hit provider={provider} len={len(body)}", flush=True)
            return 200, body, content_type, remote_url

        headers = {"User-Agent": "CompensacoesApp/1.0 (TileScheme)"}
        try:
            response = self._session.get(remote_url, timeout=self._timeout_sec, headers=headers)
        except Exception as exc:
            if self._debug:
                print(f"[MAP SCHEME] upstream exception provider={provider} url={remote_url} err={exc}", flush=True)
            return 502, b"", "text/plain", remote_url

        status = int(getattr(response, "status_code", 502))
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        body = response.content if status == 200 else b""
        if status == 200 and body:
            self._cache_put(remote_url, body, content_type)
            if self._debug:
                print(f"[MAP SCHEME] upstream-ok provider={provider} len={len(body)}", flush=True)
        elif self._debug:
            print(f"[MAP SCHEME] upstream-non200 provider={provider} status={status} url={remote_url}", flush=True)
        return status, body, content_type, remote_url

    def _cache_get(self, key: str) -> Optional[Tuple[bytes, str]]:
        with self._cache_lock:
            value = self._cache.get(key)
            if value is None:
                return None
            self._cache.move_to_end(key)
            return value

    def _cache_put(self, key: str, body: bytes, content_type: str) -> None:
        with self._cache_lock:
            self._cache[key] = (body, content_type)
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
