import json
import os
import platform
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, cast

from app import __version__ as APP_VERSION
from app.config import APP_NAME
from app.utils.app_paths import resolve_app_data_dir
from app.utils.logger import LOG_DIR, LOG_FILE


def _serialize_diagnostics_payload(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(cast(Any, value))
    if isinstance(value, dict):
        return {key: _serialize_diagnostics_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_diagnostics_payload(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            key: _serialize_diagnostics_payload(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return value


def default_diagnostics_filename(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"diagnostico_compensacoes_{stamp}.json"


def build_diagnostics_snapshot(window=None) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "app": {
            "name": APP_NAME,
            "version": APP_VERSION,
        },
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "executable": sys.executable,
            "frozen": bool(getattr(sys, "frozen", False)),
        },
        "paths": {
            "cwd": os.getcwd(),
            "app_data_dir": str(resolve_app_data_dir()),
            "logs_dir": LOG_DIR,
            "log_file": LOG_FILE,
        },
    }

    if window is None:
        return snapshot

    current_layer = ""
    settings_controller = getattr(window, "settings_controller", None)
    if settings_controller is not None and hasattr(settings_controller, "current_map_layer"):
        try:
            current_layer = settings_controller.current_map_layer()
        except Exception:
            current_layer = ""

    selected = getattr(window, "selected", None)
    records = getattr(window, "records", []) or []
    filtered = getattr(window, "filtered_records", []) or []

    snapshot["session"] = {
        "excel_path": getattr(getattr(window, "excel", None), "path", "") or "",
        "records_total": len(records),
        "filtered_total": len(filtered),
        "selected_uid": getattr(selected, "uid", "") if selected is not None else "",
        "recent_files": list(getattr(window, "recent_files", []) or []),
        "map_layer": current_layer,
        "is_dark_mode": bool(getattr(window, "is_dark_mode", False)),
        "last_marker_coords": list(getattr(window, "last_marker_coords", ()) or []),
        "local_session_source": _serialize_diagnostics_payload(
            getattr(window, "_local_session_source_status", None)
        ),
        "local_filter_facets": _serialize_diagnostics_payload(
            getattr(window, "_local_filter_facets_status", None)
        ),
        "local_mutation_sync": _serialize_diagnostics_payload(
            getattr(window, "_local_mutation_sync_status", None)
        ),
        "local_record_read": _serialize_diagnostics_payload(
            getattr(window, "_local_record_read_status", None)
        ),
    }

    persistence_service = getattr(window, "persistence_service", None)
    if persistence_service is not None:
        persistence_section: Dict[str, Any] = {
            "available": True,
            "db_path": str(getattr(persistence_service, "db_path", "") or ""),
        }
        excel_path = snapshot["session"]["excel_path"]
        if excel_path and hasattr(persistence_service, "build_workbook_diagnostics"):
            try:
                diagnostics = persistence_service.build_workbook_diagnostics(excel_path)
                persistence_section["workbook"] = _serialize_diagnostics_payload(diagnostics)
            except Exception as exc:
                persistence_section["error"] = str(exc)
        snapshot["persistence"] = persistence_section
    else:
        snapshot["persistence"] = {"available": False}
    return snapshot


def write_diagnostics_report(path: str, snapshot: Dict[str, Any]) -> None:
    target = os.path.abspath(path)
    target_dir = os.path.dirname(target)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, ensure_ascii=False)
