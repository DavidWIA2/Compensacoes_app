import json
import os
import re
import time
from typing import Callable, Dict, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

from PySide6.QtCore import QThread, Signal

from app import __version__ as APP_VERSION
from app.services.geocode_service import geocode_address_arcgis
from app.utils.logger import logger


class GeocodeWorker(QThread):
    progress_update = Signal(int, str)
    finished_process = Signal(object)

    def __init__(self, records_to_process):
        super().__init__()
        self.records = records_to_process
        self.is_running = True
        self.resultados = {}  # {excel_row: {"main": (lat, lon), "plantio": (lat, lon)}}

    def run(self):
        total = len(self.records)
        cancelled = False
        for i, r in enumerate(self.records):
            if not self.is_running or self.isInterruptionRequested():
                cancelled = True
                break

            res = {}
            lat_m = str(getattr(r, "latitude", "")).strip()
            lon_m = str(getattr(r, "longitude", "")).strip()
            lat_p = str(getattr(r, "latitude_plantio", "")).strip()
            lon_p = str(getattr(r, "longitude_plantio", "")).strip()
            micro = str(getattr(r, "microbacia", "")).strip()
            has_main_coords = bool(lat_m and lon_m)
            has_plantio_coords = bool(lat_p and lon_p)

            if (r.endereco or "").strip():
                if not has_main_coords:
                    self.progress_update.emit(i, f"Principal ({i + 1}/{total}): {str(r.endereco)[:30]}...")
                    try:
                        coords = self._geocode_api(r.endereco)
                        if coords:
                            res["main"] = coords
                    except Exception as e:
                        logger.error(f"[GEOCODE] Erro ao buscar endereço principal (linha {r.excel_row}): {e}")
                    time.sleep(0.3)
                    if not self.is_running or self.isInterruptionRequested():
                        cancelled = True
                        break
                elif not micro:
                    res["main"] = (float(lat_m), float(lon_m))

            if (r.endereco_plantio or "").strip():
                if not has_plantio_coords:
                    self.progress_update.emit(i, f"Plantio ({i + 1}/{total}): {str(r.endereco_plantio)[:30]}...")
                    try:
                        coords = self._geocode_api(r.endereco_plantio)
                        if coords:
                            res["plantio"] = coords
                    except Exception as e:
                        logger.error(f"[GEOCODE] Erro ao buscar endereço de plantio (linha {r.excel_row}): {e}")
                    time.sleep(0.3)
                    if not self.is_running or self.isInterruptionRequested():
                        cancelled = True
                        break
                elif not micro and not res.get("main"):
                    res["plantio"] = (float(lat_p), float(lon_p))

            if res:
                self.resultados[r.excel_row] = res

        if not cancelled:
            self.finished_process.emit(self.resultados)

    def stop(self):
        self.is_running = False
        self.requestInterruption()

    def _geocode_api(self, address: str):
        return geocode_address_arcgis(address, timeout=8)


class UpdaterWorker(QThread):
    update_available = Signal(str, str)  # version, release_notes
    update_ready = Signal(object)
    no_update = Signal(str)
    check_failed = Signal(str)
    _VERSION_RE = re.compile(r"^(?P<release>\d+(?:\.\d+)*)(?P<suffix>.*)$")
    _PRERELEASE_RANKS = {
        "": 4,
        "dev": 0,
        "a": 1,
        "alpha": 1,
        "b": 2,
        "beta": 2,
        "pre": 3,
        "preview": 3,
        "rc": 3,
    }

    def __init__(
        self,
        update_url: Optional[str] = None,
        current_version: str = APP_VERSION,
        fetch_json: Optional[Callable[[str], Dict[str, object]]] = None,
    ):
        super().__init__()
        self.update_url = (update_url or os.getenv("COMPENSACOES_UPDATE_URL", "")).strip()
        self.current_version = current_version
        self._fetch_json = fetch_json or self._default_fetch_json

    def run(self):
        if not self.update_url:
            logger.info("[UPDATER] Nenhuma fonte de versao configurada; verificacao automatica ignorada.")
            return

        if self.isInterruptionRequested():
            return

        try:
            payload = self._fetch_json(self.update_url)
        except Exception as exc:
            message = f"Falha ao consultar atualizacoes: {exc}"
            logger.warning(f"[UPDATER] {message}")
            self.check_failed.emit(message)
            return

        if self.isInterruptionRequested():
            return

        details = self._extract_update_details(payload)
        latest_version = details["version"]
        release_notes = details["notes"]

        if not latest_version:
            logger.warning("[UPDATER] Resposta sem versao valida; verificacao ignorada.")
            self.check_failed.emit("Resposta de atualizacao sem versao valida.")
            return

        if self._is_newer_version(latest_version, self.current_version):
            self.update_available.emit(latest_version, release_notes or "Sem notas de versao.")
            self.update_ready.emit(details)
        else:
            logger.info("[UPDATER] Aplicativo ja esta na versao mais recente configurada.")
            self.no_update.emit(self.current_version)

    @staticmethod
    def _extract_update_details(payload: Dict[str, object]) -> Dict[str, object]:
        version = str(
            payload.get("version")
            or payload.get("tag_name")
            or payload.get("latest_version")
            or ""
        ).strip()
        notes = str(
            payload.get("notes")
            or payload.get("release_notes")
            or payload.get("body")
            or ""
        ).strip()
        download_url = str(
            payload.get("download_url")
            or payload.get("browser_download_url")
            or payload.get("html_url")
            or ""
        ).strip()
        homepage_url = str(payload.get("homepage_url") or payload.get("html_url") or "").strip()
        published_at = str(payload.get("published_at") or payload.get("created_at") or "").strip()
        sha256 = str(payload.get("sha256") or "").strip().lower()
        filename = str(payload.get("filename") or "").strip()
        signed_value = payload.get("signed")
        if isinstance(signed_value, bool):
            signed = signed_value
        else:
            signed_text = str(signed_value or "").strip().lower()
            if signed_text in {"1", "true", "yes", "y", "sim"}:
                signed = True
            elif signed_text in {"0", "false", "no", "n", "nao"}:
                signed = False
            else:
                signed = None
        signature_mode = str(payload.get("signature_mode") or "").strip()
        return {
            "version": version,
            "notes": notes,
            "download_url": download_url,
            "homepage_url": homepage_url,
            "published_at": published_at,
            "sha256": sha256,
            "filename": filename,
            "signed": signed,
            "signature_mode": signature_mode,
        }

    @staticmethod
    def _normalize_version(version: str) -> Tuple[Tuple[int, ...], int, int]:
        clean = str(version or "").strip().lstrip("vV")
        if not clean:
            return (0,), UpdaterWorker._PRERELEASE_RANKS[""], 0

        match = UpdaterWorker._VERSION_RE.match(clean)
        if not match:
            return (0,), UpdaterWorker._PRERELEASE_RANKS[""], 0

        release = tuple(int(chunk) for chunk in match.group("release").split("."))
        suffix = (match.group("suffix") or "").strip()
        if not suffix:
            return release, UpdaterWorker._PRERELEASE_RANKS[""], 0

        suffix = suffix.lstrip("-_.")
        prerelease = re.match(r"^(a|alpha|b|beta|rc|pre|preview|dev)(\d*)", suffix, re.IGNORECASE)
        if not prerelease:
            return release, UpdaterWorker._PRERELEASE_RANKS[""], 0

        tag = prerelease.group(1).lower()
        number = int(prerelease.group(2) or 0)
        return release, UpdaterWorker._PRERELEASE_RANKS.get(tag, UpdaterWorker._PRERELEASE_RANKS[""]), number

    @classmethod
    def _is_newer_version(cls, latest_version: str, current_version: str) -> bool:
        latest_parts, latest_rank, latest_number = cls._normalize_version(latest_version)
        current_parts, current_rank, current_number = cls._normalize_version(current_version)
        max_len = max(len(latest_parts), len(current_parts))
        latest_padded = latest_parts + (0,) * (max_len - len(latest_parts))
        current_padded = current_parts + (0,) * (max_len - len(current_parts))

        if latest_padded != current_padded:
            return latest_padded > current_padded
        if latest_rank != current_rank:
            return latest_rank > current_rank
        return latest_number > current_number

    @staticmethod
    def _default_fetch_json(url: str) -> Dict[str, object]:
        request = Request(url, headers={"User-Agent": "CompensacoesAppUpdater/1.0"})
        try:
            with urlopen(request, timeout=5) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                body = response.read().decode(charset)
        except URLError as exc:
            raise RuntimeError(f"nao foi possivel acessar {url}") from exc

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("resposta de atualizacao nao eh um JSON valido") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("resposta de atualizacao deve ser um objeto JSON")

        return payload
