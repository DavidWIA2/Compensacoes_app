from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from app.application.use_cases.workbook_session import ImportSessionAnalysis
from app.models.compensacao import Compensacao
from app.services.audit_service import AuditEvent, serialize_records_sample


@dataclass(frozen=True)
class ImportExecutionResult:
    import_path: str
    imported_count: int
    total_incoming: int
    skipped_by_uid: int
    skipped_by_av_tec: int
    backup_path: str
    imported_records: tuple[Compensacao, ...]

    @property
    def session_backup_path(self) -> str:
        return self.backup_path


@dataclass(frozen=True)
class RollbackOption:
    label: str
    backup_path: str
    source_type: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class RollbackSelectionPlan:
    prompt: str
    options: tuple[RollbackOption, ...]


@dataclass(frozen=True)
class RollbackRestoreResult:
    workbook_path: str
    source_backup_path: str
    rollback_source: str
    label: str
    backup_path: str

    @property
    def session_path(self) -> str:
        return self.workbook_path


def resolve_runtime_session_path(session_runtime: object) -> str:
    return str(
        getattr(session_runtime, "session_path", "")
        or getattr(session_runtime, "path", "")
        or ""
    ).strip()


def build_import_audit_payload(
    *,
    analysis: ImportSessionAnalysis,
    records_to_add: Sequence[Compensacao],
    imported_count: int,
    backup_path: str,
) -> dict[str, Any]:
    return {
        "action": "import",
        "summary": f"{imported_count} registro(s) importado(s) de {os.path.basename(analysis.import_path)}",
        "backup_path": backup_path,
        "metadata": {
            "source_path": os.path.abspath(analysis.import_path),
            "incoming_records": analysis.total_incoming,
            "imported_records": imported_count,
            "skipped_by_uid": analysis.skipped_by_uid,
            "skipped_by_av_tec": analysis.skipped_by_av_tec,
        },
        "after": {
            "imported_count": imported_count,
            "sample_records": serialize_records_sample(records_to_add),
        },
    }


def build_import_execution_result(
    *,
    analysis: ImportSessionAnalysis,
    imported_count: int,
    backup_path: str,
    imported_records: Sequence[Compensacao],
) -> ImportExecutionResult:
    return ImportExecutionResult(
        import_path=analysis.import_path,
        imported_count=imported_count,
        total_incoming=analysis.total_incoming,
        skipped_by_uid=analysis.skipped_by_uid,
        skipped_by_av_tec=analysis.skipped_by_av_tec,
        backup_path=backup_path,
        imported_records=tuple(imported_records),
    )


def format_rollback_timestamp(timestamp: str) -> str:
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return timestamp


def build_audited_rollback_label(event: AuditEvent) -> str:
    return (
        f"{format_rollback_timestamp(event.timestamp)} - "
        f"{str(getattr(event, 'action', '') or '').upper()} - "
        f"{str(getattr(event, 'summary', '') or '').strip()}"
    )


def build_audited_rollback_option(
    *,
    event: AuditEvent,
    label: str,
) -> RollbackOption:
    return RollbackOption(
        label=label,
        backup_path=str(getattr(event, "backup_path", "") or "").strip(),
        source_type="operation_audit",
        metadata={
            "event_id": event.event_id,
            "action": event.action,
            "summary": event.summary,
        },
    )


def build_legacy_rollback_option(
    *,
    file_path: str,
    timestamp_label: str,
) -> RollbackOption:
    return RollbackOption(
        label=f"{timestamp_label} - {os.path.basename(file_path)}",
        backup_path=file_path,
        source_type="legacy_backup",
        metadata={"filename": os.path.basename(file_path)},
    )


def build_rollback_selection_plan(
    *,
    prompt: str,
    options: Sequence[RollbackOption],
) -> RollbackSelectionPlan:
    return RollbackSelectionPlan(prompt=prompt, options=tuple(options))


def build_restore_audit_payload(
    *,
    source_backup_path: str,
    rollback_source: str,
    metadata: dict[str, object] | None,
    label: str,
    backup_path: str,
) -> dict[str, Any]:
    return {
        "action": "rollback",
        "summary": f"Sessao restaurada a partir de {label}",
        "backup_path": backup_path,
        "metadata": {
            "source_type": rollback_source,
            "source_backup_path": os.path.abspath(source_backup_path),
            **dict(metadata or {}),
        },
    }


def build_rollback_restore_result(
    *,
    session_path: str,
    source_backup_path: str,
    rollback_source: str,
    label: str,
    backup_path: str,
) -> RollbackRestoreResult:
    return RollbackRestoreResult(
        workbook_path=session_path,
        source_backup_path=os.path.abspath(source_backup_path),
        rollback_source=rollback_source,
        label=label,
        backup_path=backup_path,
    )
