from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from app.application.use_cases.local_record_queries import (
    LocalRecordReadResult,
    LocalRecordReadStatus,
)
from app.application.use_cases.persistence_monitoring import (
    PersistenceRecordOverviewReport,
    PersistenceStatusReport,
)
from app.application.use_cases.workbook_session import LoadSessionResult
from app.models.compensacao import Compensacao


@dataclass(frozen=True)
class WorkbookServiceStateSnapshot:
    path: str
    wb: object | None
    ws: object | None
    plantio_ws: object | None
    col_map: dict[str, int]
    plantio_col_map: dict[str, int]
    uid_to_row: dict[str, int]
    last_backup_time: object | None
    merged_cells_warning: object | None

    @property
    def session_path(self) -> str:
        return self.path


@dataclass(frozen=True)
class AuthoritativeWorkbookLoadResult:
    path: str
    loaded_records: tuple[Compensacao, ...]
    records: tuple[Compensacao, ...]
    local_session_source_status: LocalRecordReadStatus
    load_result: LoadSessionResult
    issues: tuple[str, ...] = ()
    snapshot_status: object | None = None

    @property
    def session_path(self) -> str:
        return self.path


@dataclass(frozen=True)
class AuthoritativeMonitoringSnapshot:
    workbook_path: str
    persistence_report: PersistenceStatusReport
    record_overview_report: PersistenceRecordOverviewReport | None = None

    @property
    def session_path(self) -> str:
        return self.workbook_path


@dataclass(frozen=True)
class SessionAvailability:
    path: str
    display_name: str
    has_workbook_file: bool = False
    has_local_snapshot: bool = False
    source_kind: str = "missing"

    @property
    def is_openable(self) -> bool:
        return self.has_workbook_file or self.has_local_snapshot

    @property
    def display_label(self) -> str:
        if not self.display_name:
            return "local"
        if str(self.path or "").strip().lower().startswith("session://"):
            return self.display_name
        if self.source_kind == "sqlite_only":
            return f"{self.display_name} (SQLite local)"
        return self.display_name

    @property
    def detail_message(self) -> str:
        if not self.path:
            return "Banco local ainda nao inicializado."
        if str(self.path or "").strip().lower().startswith("session://"):
            return f"Banco SQLite local disponivel em {self.display_name}."
        if self.source_kind == "hybrid":
            return (
                f"Base local vinculada a {self.path} com arquivo original e snapshot local do SQLite disponiveis."
            )
        if self.source_kind == "sqlite_only":
            return (
                f"Base local do SQLite disponivel para {self.path}, mesmo sem o arquivo original no disco."
            )
        if self.source_kind == "workbook_only":
            return (
                f"Base vinculada a {self.path} com arquivo original disponivel e sem snapshot local confirmado."
            )
        return (
            f"Base indisponivel para {self.path}: nem o arquivo original nem o snapshot local foram encontrados."
        )


def current_workbook_path(workbook: object) -> str:
    return str(getattr(workbook, "path", "") or "").strip()


def current_session_path(workbook: object) -> str:
    session_path = str(getattr(workbook, "session_path", "") or "").strip()
    if session_path:
        return session_path
    return current_workbook_path(workbook)


def get_session_snapshot_summary(persistence_service, workbook_path: str):
    if persistence_service is None:
        raise RuntimeError("Espelho local indisponivel.")
    if hasattr(persistence_service, "get_session_snapshot_summary"):
        return persistence_service.get_session_snapshot_summary(workbook_path)
    return persistence_service.get_workbook_snapshot_summary(workbook_path)


def list_session_records(persistence_service, workbook_path: str) -> tuple[Compensacao, ...]:
    if persistence_service is None:
        return ()
    if hasattr(persistence_service, "list_records_for_session"):
        return tuple(persistence_service.list_records_for_session(workbook_path))
    return tuple(persistence_service.list_records_for_workbook(workbook_path))


def sync_session_snapshot(
    persistence_service,
    workbook_path: str,
    records: Sequence[Compensacao],
) -> object | None:
    if persistence_service is None:
        return None
    record_list = list(records)
    if hasattr(persistence_service, "sync_session_snapshot"):
        return persistence_service.sync_session_snapshot(workbook_path, record_list)
    return persistence_service.sync_workbook_snapshot(workbook_path, record_list)


def has_snapshot_data(snapshot: object | None) -> bool:
    if snapshot is None:
        return False
    return bool(
        str(getattr(snapshot, "synced_at", "") or "").strip()
        or int(getattr(snapshot, "record_count", 0) or 0) > 0
    )


def resolve_session_display_name(
    persistence_service,
    workbook_path: str,
    *,
    default_display_name: str,
) -> str:
    if persistence_service is None or not hasattr(persistence_service, "get_session_display_name"):
        return default_display_name
    try:
        resolved = persistence_service.get_session_display_name(workbook_path)
    except Exception:
        return default_display_name
    return str(resolved or default_display_name)


def build_session_availability(
    workbook_path: str,
    *,
    has_local_snapshot: bool,
    persistence_service=None,
) -> SessionAvailability:
    normalized_path = str(workbook_path or "").strip()
    if not normalized_path:
        return SessionAvailability(path="", display_name="")

    is_named_session = normalized_path.lower().startswith("session://")
    resolved_path = normalized_path if is_named_session else os.path.abspath(normalized_path)
    has_workbook_file = False if is_named_session else os.path.exists(resolved_path)
    default_display_name = os.path.basename(resolved_path) or resolved_path
    display_name = resolve_session_display_name(
        persistence_service,
        resolved_path,
        default_display_name=default_display_name,
    )

    if has_workbook_file and has_local_snapshot:
        source_kind = "hybrid"
    elif has_local_snapshot:
        source_kind = "sqlite_only"
    elif has_workbook_file:
        source_kind = "workbook_only"
    else:
        source_kind = "missing"

    return SessionAvailability(
        path=resolved_path,
        display_name=display_name,
        has_workbook_file=has_workbook_file,
        has_local_snapshot=has_local_snapshot,
        source_kind=source_kind,
    )


def bind_workbook_runtime_path(
    workbook: object,
    workbook_path: str,
    *,
    clear_loaded_workbook: bool = False,
) -> None:
    normalized_path = str(workbook_path or "").strip()
    workbook.path = normalized_path
    if not clear_loaded_workbook:
        return
    workbook.wb = None
    workbook.ws = None
    workbook.plantio_ws = None
    workbook.col_map = {}
    workbook.plantio_col_map = {}
    workbook.uid_to_row = {}
    workbook.merged_cells_warning = None


def snapshot_workbook_service_state(workbook: object) -> WorkbookServiceStateSnapshot:
    return WorkbookServiceStateSnapshot(
        path=str(getattr(workbook, "path", "") or ""),
        wb=getattr(workbook, "wb", None),
        ws=getattr(workbook, "ws", None),
        plantio_ws=getattr(workbook, "plantio_ws", None),
        col_map=dict(getattr(workbook, "col_map", {}) or {}),
        plantio_col_map=dict(getattr(workbook, "plantio_col_map", {}) or {}),
        uid_to_row=dict(getattr(workbook, "uid_to_row", {}) or {}),
        last_backup_time=getattr(workbook, "last_backup_time", None),
        merged_cells_warning=getattr(workbook, "merged_cells_warning", None),
    )


def restore_workbook_service_state(workbook: object, snapshot: WorkbookServiceStateSnapshot) -> None:
    workbook.path = snapshot.path
    workbook.wb = snapshot.wb
    workbook.ws = snapshot.ws
    workbook.plantio_ws = snapshot.plantio_ws
    workbook.col_map = dict(snapshot.col_map)
    workbook.plantio_col_map = dict(snapshot.plantio_col_map)
    workbook.uid_to_row = dict(snapshot.uid_to_row)
    workbook.last_backup_time = snapshot.last_backup_time
    workbook.merged_cells_warning = snapshot.merged_cells_warning


def build_runtime_record_result(
    *,
    source: str,
    records: Sequence[Compensacao],
    strategy: str,
    workbook_path: str,
    metrics: object,
    snapshot: object | None = None,
    issues: Sequence[str] = (),
) -> LocalRecordReadResult:
    return LocalRecordReadResult(
        source=source,
        records=tuple(records),
        strategy=strategy,
        metrics=metrics,
        workbook_path=workbook_path,
        synced_at=str(getattr(snapshot, "synced_at", "") or "") if snapshot is not None else "",
        mirrored_records=(
            int(getattr(snapshot, "record_count", 0) or 0)
            if snapshot is not None
            else len(tuple(records))
        ),
        session_records=len(tuple(records)),
        issues=tuple(str(issue or "").strip() for issue in issues if str(issue or "").strip()),
    )


def build_authoritative_workbook_load_result(
    *,
    path: str,
    loaded_records: Sequence[Compensacao],
    record_source: LocalRecordReadResult,
    local_session_source_status: LocalRecordReadStatus,
    load_result: LoadSessionResult,
    issues: Sequence[str] = (),
    snapshot_status: object | None = None,
) -> AuthoritativeWorkbookLoadResult:
    normalized_issues = tuple(str(issue or "").strip() for issue in issues if str(issue or "").strip())
    return AuthoritativeWorkbookLoadResult(
        path=path,
        loaded_records=tuple(loaded_records),
        records=tuple(record_source.records),
        local_session_source_status=local_session_source_status,
        load_result=load_result,
        issues=normalized_issues,
        snapshot_status=snapshot_status,
    )


def build_monitoring_snapshot(
    workbook_path: str,
    *,
    persistence_report: PersistenceStatusReport,
    record_overview_report: PersistenceRecordOverviewReport | None = None,
) -> AuthoritativeMonitoringSnapshot:
    return AuthoritativeMonitoringSnapshot(
        workbook_path=str(workbook_path or "").strip(),
        persistence_report=persistence_report,
        record_overview_report=record_overview_report,
    )


def try_touch_session_catalog_entry(
    persistence_service,
    session_path: str,
    *,
    logger_warning: Callable[[str], None] | None = None,
) -> None:
    if persistence_service is None or not hasattr(persistence_service, "touch_session"):
        return
    try:
        persistence_service.touch_session(session_path)
    except Exception:
        if logger_warning is not None:
            logger_warning(session_path)
