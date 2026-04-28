import json
import re
import time
from typing import Callable, Dict, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

from PySide6.QtCore import QThread, Signal

from app import __version__ as APP_VERSION
from app.config import resolve_update_manifest_url
from app.services.auto_update_service import AutoUpdateCancelled, prepare_staged_update
from app.services.geocode_service import geocode_address
from app.services.plantio_service import record_plantio_items
from app.utils.logger import logger


class GeocodeWorker(QThread):
    progress_update = Signal(int, str)
    finished_process = Signal(object)
    cancelled_process = Signal(str)

    def __init__(self, records_to_process):
        super().__init__()
        self.records = records_to_process
        self.is_running = True
        self.resultados = {}  # {excel_row: {"main": (lat, lon), "plantios": {sequencia: (lat, lon)}}}

    def run(self):
        total = len(self.records)
        cancelled = False
        for i, record in enumerate(self.records):
            if not self.is_running or self.isInterruptionRequested():
                cancelled = True
                break

            result = {}
            lat_m = str(getattr(record, "latitude", "")).strip()
            lon_m = str(getattr(record, "longitude", "")).strip()
            micro = str(getattr(record, "microbacia", "")).strip()
            has_main_coords = bool(lat_m and lon_m)

            if (record.endereco or "").strip():
                if not has_main_coords:
                    self.progress_update.emit(i, f"Principal ({i + 1}/{total}): {str(record.endereco)[:30]}...")
                    try:
                        coords = self._geocode_api(record.endereco)
                        if coords:
                            result["main"] = coords
                    except Exception as exc:
                        logger.error(f"[GEOCODE] Erro ao buscar endereco principal (linha {record.excel_row}): {exc}")
                    time.sleep(0.3)
                    if not self.is_running or self.isInterruptionRequested():
                        cancelled = True
                        break
                elif not micro:
                    result["main"] = (float(lat_m), float(lon_m))

            plantio_results = {}
            for plantio in record_plantio_items(record):
                if not (plantio.endereco or "").strip():
                    continue

                lat_p = str(getattr(plantio, "latitude", "")).strip()
                lon_p = str(getattr(plantio, "longitude", "")).strip()
                has_plantio_coords = bool(lat_p and lon_p)

                if not has_plantio_coords:
                    self.progress_update.emit(i, f"Plantio ({i + 1}/{total}): {str(plantio.endereco)[:30]}...")
                    try:
                        coords = self._geocode_api(plantio.endereco)
                        if coords:
                            plantio_results[int(plantio.sequence)] = coords
                    except Exception as exc:
                        logger.error(
                            f"[GEOCODE] Erro ao buscar endereco de plantio (linha {record.excel_row}, plantio {plantio.sequence}): {exc}"
                        )
                    time.sleep(0.3)
                    if not self.is_running or self.isInterruptionRequested():
                        cancelled = True
                        break
                elif not micro and not result.get("main"):
                    plantio_results[int(plantio.sequence)] = (float(lat_p), float(lon_p))

            if cancelled:
                break

            if plantio_results:
                result["plantios"] = plantio_results

            if result:
                self.resultados[record.excel_row] = result

        if cancelled:
            self.cancelled_process.emit("Geocodificação em lote cancelada.")
            return

        self.finished_process.emit(self.resultados)

    def stop(self):
        self.is_running = False
        self.requestInterruption()

    def _geocode_api(self, address: str):
        return geocode_address(address, timeout=8)


class UpdaterWorker(QThread):
    update_available = Signal(str, str)
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
        self.update_url = resolve_update_manifest_url(update_url or "")
        self.current_version = current_version
        self._fetch_json = fetch_json or self._default_fetch_json

    def run(self):
        if not self.update_url:
            logger.info("[UPDATER] Nenhuma fonte de versão configurada; verificação automática ignorada.")
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
            logger.warning("[UPDATER] Resposta sem versão válida; verificação ignorada.")
            self.check_failed.emit("Resposta de atualização sem versão válida.")
            return

        if self._is_newer_version(latest_version, self.current_version):
            self.update_available.emit(latest_version, release_notes or "Sem notas de versão.")
            self.update_ready.emit(details)
        else:
            logger.info("[UPDATER] Aplicativo já está na versão mais recente configurada.")
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
            raise RuntimeError("resposta de atualização não é um JSON válido") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("resposta de atualização deve ser um objeto JSON")

        return payload


class UpdateInstallerWorker(QThread):
    progress = Signal(int, str)
    staged = Signal(object)
    failed = Signal(str)
    cancelled = Signal(str)

    def __init__(
        self,
        details: Dict[str, object],
        *,
        current_pid: int,
        current_executable: str = "",
        prepare_update: Optional[Callable[..., object]] = None,
    ):
        super().__init__()
        self.details = dict(details or {})
        self.current_pid = current_pid
        self.current_executable = current_executable
        self._prepare_update = prepare_update or prepare_staged_update

    def run(self):
        try:
            staged_update = self._prepare_update(
                self.details,
                current_pid=self.current_pid,
                current_executable=self.current_executable,
                progress_callback=self._emit_progress,
                interruption_requested=self.isInterruptionRequested,
            )
        except AutoUpdateCancelled as exc:
            logger.info(f"[UPDATER] Download cancelado: {exc}")
            self.cancelled.emit(str(exc))
            return
        except Exception as exc:
            logger.warning(f"[UPDATER] Falha ao preparar atualização automática: {exc}")
            self.failed.emit(str(exc))
            return

        payload = staged_update.to_payload() if hasattr(staged_update, "to_payload") else staged_update
        self.staged.emit(payload)

    def _emit_progress(self, downloaded_bytes: int, total_bytes: Optional[int]):
        if total_bytes and total_bytes > 0:
            percent = int((downloaded_bytes / total_bytes) * 100)
            message = f"Baixando atualização... {percent}%"
        else:
            percent = 0
            downloaded_mb = downloaded_bytes / (1024 * 1024)
            message = f"Baixando atualização... {downloaded_mb:.1f} MB"
        self.progress.emit(percent, message)
