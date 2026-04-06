import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from app import __version__ as APP_VERSION
from app.config import APP_NAME
from app.services.diagnostics_service_support import (
    build_base_diagnostics_snapshot,
    build_persistence_snapshot,
    build_window_session_snapshot,
    serialize_diagnostics_payload,
)
from app.utils.app_paths import resolve_app_data_dir
from app.utils.logger import get_logger
from app.utils.logger import LOG_DIR, LOG_FILE


logger = get_logger("Diagnostics")


def _serialize_diagnostics_payload(value: Any) -> Any:
    return serialize_diagnostics_payload(value)


def default_diagnostics_filename(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"diagnostico_compensacoes_{stamp}.json"


def build_diagnostics_snapshot(window=None) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = build_base_diagnostics_snapshot(
        app_name=APP_NAME,
        app_version=APP_VERSION,
        app_data_dir=str(resolve_app_data_dir()),
        logs_dir=LOG_DIR,
        log_file=LOG_FILE,
    )
    if window is None:
        return snapshot

    snapshot["session"] = build_window_session_snapshot(
        window,
        logger=logger,
        serializer=_serialize_diagnostics_payload,
    )
    snapshot["persistence"] = build_persistence_snapshot(
        window,
        session_path=str(snapshot["session"].get("session_path") or ""),
        logger=logger,
        serializer=_serialize_diagnostics_payload,
    )
    return snapshot


def write_diagnostics_report(path: str, snapshot: Dict[str, Any]) -> None:
    target = os.path.abspath(path)
    target_dir = os.path.dirname(target)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, ensure_ascii=False)
