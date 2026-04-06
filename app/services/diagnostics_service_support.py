from __future__ import annotations

import os
import platform
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Callable, cast


def serialize_diagnostics_payload(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(cast(Any, value))
    if isinstance(value, dict):
        return {key: serialize_diagnostics_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_diagnostics_payload(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            key: serialize_diagnostics_payload(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return value


def build_base_diagnostics_snapshot(
    *,
    app_name: str,
    app_version: str,
    app_data_dir: str,
    logs_dir: str,
    log_file: str,
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "app": {
            "name": app_name,
            "version": app_version,
        },
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "executable": sys.executable,
            "frozen": bool(getattr(sys, "frozen", False)),
        },
        "paths": {
            "cwd": os.getcwd(),
            "app_data_dir": app_data_dir,
            "logs_dir": logs_dir,
            "log_file": log_file,
        },
    }


def run_diagnostics_probe(
    operation: Callable[[], Any],
    *,
    logger: Any,
    failure_message: str,
    default: Any,
) -> Any:
    try:
        return operation()
    except Exception as exc:
        if logger is not None:
            logger.warning("%s: %s", failure_message, exc, exc_info=True)
        return default


def resolve_current_map_layer(window: Any, *, logger: Any) -> str:
    settings_controller = getattr(window, "settings_controller", None)
    if settings_controller is None or not hasattr(settings_controller, "current_map_layer"):
        return ""
    return str(
        run_diagnostics_probe(
            settings_controller.current_map_layer,
            logger=logger,
            failure_message="Falha ao consultar camada atual do mapa nos diagnosticos",
            default="",
        )
        or ""
    )


def resolve_runtime_materialization(window: Any, *, logger: Any) -> bool:
    session_runtime = getattr(window, "session_runtime", None)
    if session_runtime is None or not hasattr(session_runtime, "has_materialized_workbook"):
        return False
    return bool(
        run_diagnostics_probe(
            session_runtime.has_materialized_workbook,
            logger=logger,
            failure_message="Falha ao consultar materializacao do runtime de sessao",
            default=False,
        )
    )


def build_window_session_snapshot(
    window: Any,
    *,
    logger: Any,
    serializer: Callable[[Any], Any],
) -> dict[str, Any]:
    selected = getattr(window, "selected", None)
    records = getattr(window, "records", []) or []
    filtered = getattr(window, "filtered_records", []) or []
    session_runtime = getattr(window, "session_runtime", None)
    session_path = getattr(session_runtime, "session_path", getattr(session_runtime, "path", "")) or ""
    workbook_runtime_loaded = resolve_runtime_materialization(window, logger=logger)

    return {
        "session_path": session_path,
        "records_total": len(records),
        "filtered_total": len(filtered),
        "selected_uid": getattr(selected, "uid", "") if selected is not None else "",
        "recent_files": list(getattr(window, "recent_files", []) or []),
        "map_layer": resolve_current_map_layer(window, logger=logger),
        "is_dark_mode": bool(getattr(window, "is_dark_mode", False)),
        "workbook_runtime_loaded": workbook_runtime_loaded,
        "session_runtime_materialized": workbook_runtime_loaded,
        "last_marker_coords": list(getattr(window, "last_marker_coords", ()) or []),
        "local_session_source": serializer(getattr(window, "_local_session_source_status", None)),
        "local_filter_facets": serializer(getattr(window, "_local_filter_facets_status", None)),
        "local_mutation_sync": serializer(getattr(window, "_local_mutation_sync_status", None)),
        "local_record_read": serializer(getattr(window, "_local_record_read_status", None)),
    }


def build_persistence_snapshot(
    window: Any,
    *,
    session_path: str,
    logger: Any,
    serializer: Callable[[Any], Any],
) -> dict[str, Any]:
    persistence_service = getattr(window, "persistence_service", None)
    if persistence_service is None:
        return {"available": False}

    persistence_section: dict[str, Any] = {
        "available": True,
        "db_path": str(getattr(persistence_service, "db_path", "") or ""),
    }
    if not session_path:
        return persistence_section

    def _build_snapshot() -> Any:
        if hasattr(persistence_service, "build_session_diagnostics"):
            return persistence_service.build_session_diagnostics(session_path)
        if hasattr(persistence_service, "build_workbook_diagnostics"):
            return persistence_service.build_workbook_diagnostics(session_path)
        return None

    try:
        diagnostics = _build_snapshot()
    except Exception as exc:
        if logger is not None:
            logger.warning("Falha ao montar diagnosticos de persistencia: %s", exc, exc_info=True)
        persistence_section["error"] = str(exc)
        return persistence_section
    if diagnostics is None:
        return persistence_section

    serialized = serializer(diagnostics)
    persistence_section["session"] = serialized
    persistence_section["workbook"] = serialized
    return persistence_section
