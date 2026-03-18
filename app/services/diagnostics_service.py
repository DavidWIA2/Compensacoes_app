import json
import os
import platform
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app import __version__ as APP_VERSION
from app.config import APP_NAME
from app.utils.logger import LOG_DIR, LOG_FILE


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
    }
    return snapshot


def write_diagnostics_report(path: str, snapshot: Dict[str, Any]) -> None:
    target = os.path.abspath(path)
    target_dir = os.path.dirname(target)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, ensure_ascii=False)
