from __future__ import annotations

import glob
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Protocol, Sequence

from app.application.use_cases.workbook_session import ImportWorkbookAnalysis, ProgressCallback
from app.models.compensacao import Compensacao
from app.services.audit_service import AuditEvent, serialize_records_sample


class ImportWorkflow(Protocol):
    def import_records(
        self,
        records: Sequence[Compensacao],
        *,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> int: ...


class BackupWorkbook(Protocol):
    path: str

    def create_operation_backup(self, label: str) -> Optional[str]: ...


class AuditTrail(Protocol):
    def list_events_for_workbook(self, workbook_path: str, *, limit: int = 50) -> list[AuditEvent]: ...

    def append_event(
        self,
        *,
        workbook_path: str,
        action: str,
        summary: str,
        backup_path: str = "",
        metadata: Optional[dict[str, Any]] = None,
        before: Optional[dict[str, Any]] = None,
        after: Optional[dict[str, Any]] = None,
    ) -> AuditEvent: ...


@dataclass(frozen=True)
class ImportExecutionResult:
    import_path: str
    imported_count: int
    total_incoming: int
    skipped_by_uid: int
    skipped_by_av_tec: int
    backup_path: str
    imported_records: tuple[Compensacao, ...]


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


class WorkbookImportFlowUseCases:
    def __init__(self, import_workflow: ImportWorkflow, workbook: BackupWorkbook, audit_service: AuditTrail):
        self.import_workflow = import_workflow
        self.workbook = workbook
        self.audit_service = audit_service

    def execute_import(
        self,
        analysis: ImportWorkbookAnalysis,
        *,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> ImportExecutionResult:
        workbook_path = str(getattr(self.workbook, "path", "") or "").strip()
        if not workbook_path:
            raise ValueError("Abra a planilha base antes de importar novos registros.")

        records_to_add = list(analysis.records_to_add)
        backup_path = self.workbook.create_operation_backup("import") or ""
        raw_import_result = self.import_workflow.import_records(records_to_add, progress_callback=progress_callback)
        imported_count = len(records_to_add) if raw_import_result is None else int(raw_import_result)

        self.audit_service.append_event(
            workbook_path=workbook_path,
            action="import",
            summary=f"{imported_count} registro(s) importado(s) de {os.path.basename(analysis.import_path)}",
            backup_path=backup_path,
            metadata={
                "source_path": os.path.abspath(analysis.import_path),
                "incoming_records": analysis.total_incoming,
                "imported_records": imported_count,
                "skipped_by_uid": analysis.skipped_by_uid,
                "skipped_by_av_tec": analysis.skipped_by_av_tec,
            },
            after={
                "imported_count": imported_count,
                "sample_records": serialize_records_sample(records_to_add),
            },
        )

        return ImportExecutionResult(
            import_path=analysis.import_path,
            imported_count=imported_count,
            total_incoming=analysis.total_incoming,
            skipped_by_uid=analysis.skipped_by_uid,
            skipped_by_av_tec=analysis.skipped_by_av_tec,
            backup_path=backup_path,
            imported_records=tuple(records_to_add),
        )


class WorkbookRecoveryUseCases:
    AUDITED_PROMPT = "Selecione uma operacao anterior para restaurar a planilha:"
    LEGACY_PROMPT = "Selecione uma versao anterior para restaurar (o arquivo atual sera substituido):"

    def __init__(self, workbook: BackupWorkbook, audit_service: AuditTrail):
        self.workbook = workbook
        self.audit_service = audit_service

    def build_audited_rollback_options(
        self,
        workbook_path: str,
        *,
        limit: int = 200,
    ) -> tuple[RollbackOption, ...]:
        if not workbook_path:
            return ()

        options: list[RollbackOption] = []
        seen_labels: set[str] = set()
        for event in self.audit_service.list_events_for_workbook(workbook_path, limit=limit):
            backup_path = str(getattr(event, "backup_path", "") or "").strip()
            if not backup_path or not os.path.exists(backup_path):
                continue

            label = (
                f"{self._format_timestamp(event.timestamp)} - "
                f"{str(getattr(event, 'action', '') or '').upper()} - "
                f"{str(getattr(event, 'summary', '') or '').strip()}"
            )
            if label in seen_labels:
                label = f"{label} [{event.event_id[:8]}]"
            seen_labels.add(label)
            options.append(
                RollbackOption(
                    label=label,
                    backup_path=backup_path,
                    source_type="operation_audit",
                    metadata={
                        "event_id": event.event_id,
                        "action": event.action,
                        "summary": event.summary,
                    },
                )
            )

        return tuple(options)

    def build_rollback_plan(
        self,
        workbook_path: str,
        *,
        limit: int = 200,
    ) -> RollbackSelectionPlan:
        audited_options = self.build_audited_rollback_options(workbook_path, limit=limit)
        if audited_options:
            return RollbackSelectionPlan(prompt=self.AUDITED_PROMPT, options=audited_options)

        legacy_options = self._build_legacy_rollback_options(workbook_path)
        return RollbackSelectionPlan(prompt=self.LEGACY_PROMPT, options=legacy_options)

    def restore_backup(
        self,
        source_backup_path: str,
        *,
        rollback_source: str,
        metadata: Optional[dict[str, object]] = None,
        label: str,
    ) -> RollbackRestoreResult:
        workbook_path = str(getattr(self.workbook, "path", "") or "").strip()
        if not workbook_path:
            raise ValueError("Abra a planilha base antes de restaurar um backup.")

        backup_path = self.workbook.create_operation_backup("rollback") or ""
        shutil.copy2(source_backup_path, workbook_path)
        self.audit_service.append_event(
            workbook_path=workbook_path,
            action="rollback",
            summary=f"Planilha restaurada a partir de {label}",
            backup_path=backup_path,
            metadata={
                "source_type": rollback_source,
                "source_backup_path": os.path.abspath(source_backup_path),
                **dict(metadata or {}),
            },
        )
        return RollbackRestoreResult(
            workbook_path=workbook_path,
            source_backup_path=os.path.abspath(source_backup_path),
            rollback_source=rollback_source,
            label=label,
            backup_path=backup_path,
        )

    def _build_legacy_rollback_options(self, workbook_path: str) -> tuple[RollbackOption, ...]:
        if not workbook_path:
            return ()

        backup_dir = os.path.join(os.path.dirname(workbook_path), "backups_historico")
        if not os.path.exists(backup_dir):
            return ()

        files = glob.glob(os.path.join(backup_dir, "*.xlsx"))
        files.sort(key=os.path.getmtime, reverse=True)

        options: list[RollbackOption] = []
        for file_path in files:
            timestamp = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%d/%m/%Y %H:%M:%S")
            options.append(
                RollbackOption(
                    label=f"{timestamp} - {os.path.basename(file_path)}",
                    backup_path=file_path,
                    source_type="legacy_backup",
                    metadata={"filename": os.path.basename(file_path)},
                )
            )
        return tuple(options)

    def _format_timestamp(self, timestamp: str) -> str:
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            return timestamp
