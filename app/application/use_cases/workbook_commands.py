from __future__ import annotations

import glob
import os
import shutil
from datetime import datetime
from typing import Any, Optional, Protocol, Sequence

from app.application.use_cases.workbook_commands_support import (
    ImportExecutionResult,
    RollbackOption,
    RollbackRestoreResult,
    RollbackSelectionPlan,
    build_audited_rollback_label,
    build_audited_rollback_option,
    build_import_audit_payload,
    build_import_execution_result,
    build_legacy_rollback_option,
    build_restore_audit_payload,
    build_rollback_restore_result,
    build_rollback_selection_plan,
    format_rollback_timestamp,
    resolve_runtime_session_path,
)
from app.application.use_cases.workbook_session import ImportSessionAnalysis, ProgressCallback
from app.models.compensacao import Compensacao
from app.services.audit_service import AuditEvent


class SessionImportWorkflow(Protocol):
    def import_records(
        self,
        records: Sequence[Compensacao],
        *,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> int: ...


class SessionBackupRuntime(Protocol):
    path: str

    def create_operation_backup(self, label: str) -> Optional[str]: ...


class SessionAuditTrail(Protocol):
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


class SessionImportFlowUseCases:
    def __init__(
        self,
        import_workflow: SessionImportWorkflow,
        session_runtime: SessionBackupRuntime,
        audit_service: SessionAuditTrail,
    ):
        self.import_workflow = import_workflow
        self.session_runtime = session_runtime
        self.audit_service = audit_service

    def execute_import(
        self,
        analysis: ImportSessionAnalysis,
        *,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> ImportExecutionResult:
        session_path = resolve_runtime_session_path(self.session_runtime)
        if not session_path:
            raise ValueError("Abra uma sessao base antes de importar novos registros.")

        records_to_add = list(analysis.records_to_add)
        backup_path = self.session_runtime.create_operation_backup("import") or ""
        raw_import_result = self.import_workflow.import_records(records_to_add, progress_callback=progress_callback)
        imported_count = len(records_to_add) if raw_import_result is None else int(raw_import_result)

        audit_payload = build_import_audit_payload(
            analysis=analysis,
            records_to_add=records_to_add,
            imported_count=imported_count,
            backup_path=backup_path,
        )
        if hasattr(self.audit_service, "append_session_event"):
            self.audit_service.append_session_event(session_path=session_path, **audit_payload)
        else:
            self.audit_service.append_event(workbook_path=session_path, **audit_payload)

        return build_import_execution_result(
            analysis=analysis,
            imported_count=imported_count,
            backup_path=backup_path,
            imported_records=records_to_add,
        )


class SessionRecoveryUseCases:
    AUDITED_PROMPT = "Selecione uma operacao anterior para restaurar a sessao:"
    LEGACY_PROMPT = "Selecione uma versao anterior para restaurar (o arquivo atual sera substituido):"

    def __init__(self, session_runtime: SessionBackupRuntime, audit_service: SessionAuditTrail):
        self.session_runtime = session_runtime
        self.audit_service = audit_service

    def build_audited_rollback_options(
        self,
        session_path: str,
        *,
        limit: int = 200,
    ) -> tuple[RollbackOption, ...]:
        if not session_path:
            return ()

        options: list[RollbackOption] = []
        seen_labels: set[str] = set()
        if hasattr(self.audit_service, "list_events_for_session"):
            events = self.audit_service.list_events_for_session(session_path, limit=limit)
        else:
            events = self.audit_service.list_events_for_workbook(session_path, limit=limit)
        for event in events:
            backup_path = str(getattr(event, "backup_path", "") or "").strip()
            if not backup_path or not os.path.exists(backup_path):
                continue

            label = build_audited_rollback_label(event)
            if label in seen_labels:
                label = f"{label} [{event.event_id[:8]}]"
            seen_labels.add(label)
            options.append(build_audited_rollback_option(event=event, label=label))

        return tuple(options)

    def build_rollback_plan(
        self,
        session_path: str,
        *,
        limit: int = 200,
    ) -> RollbackSelectionPlan:
        audited_options = self.build_audited_rollback_options(session_path, limit=limit)
        if audited_options:
            return build_rollback_selection_plan(prompt=self.AUDITED_PROMPT, options=audited_options)

        legacy_options = self._build_legacy_rollback_options(session_path)
        return build_rollback_selection_plan(prompt=self.LEGACY_PROMPT, options=legacy_options)

    def restore_backup(
        self,
        source_backup_path: str,
        *,
        rollback_source: str,
        metadata: Optional[dict[str, object]] = None,
        label: str,
    ) -> RollbackRestoreResult:
        session_path = resolve_runtime_session_path(self.session_runtime)
        if not session_path:
            raise ValueError("Abra uma sessao base antes de restaurar um backup.")

        backup_path = self.session_runtime.create_operation_backup("rollback") or ""
        shutil.copy2(source_backup_path, session_path)
        audit_payload = build_restore_audit_payload(
            source_backup_path=source_backup_path,
            rollback_source=rollback_source,
            metadata=metadata,
            label=label,
            backup_path=backup_path,
        )
        if hasattr(self.audit_service, "append_session_event"):
            self.audit_service.append_session_event(session_path=session_path, **audit_payload)
        else:
            self.audit_service.append_event(workbook_path=session_path, **audit_payload)
        return build_rollback_restore_result(
            session_path=session_path,
            source_backup_path=source_backup_path,
            rollback_source=rollback_source,
            label=label,
            backup_path=backup_path,
        )

    def _build_legacy_rollback_options(self, session_path: str) -> tuple[RollbackOption, ...]:
        if not session_path:
            return ()

        backup_dir = os.path.join(os.path.dirname(session_path), "backups_historico")
        if not os.path.exists(backup_dir):
            return ()

        files = glob.glob(os.path.join(backup_dir, "*.xlsx"))
        files.sort(key=os.path.getmtime, reverse=True)

        options: list[RollbackOption] = []
        for file_path in files:
            timestamp = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%d/%m/%Y %H:%M:%S")
            options.append(build_legacy_rollback_option(file_path=file_path, timestamp_label=timestamp))
        return tuple(options)

    def _format_timestamp(self, timestamp: str) -> str:
        return format_rollback_timestamp(timestamp)


SessionImportExecutionResult = ImportExecutionResult
SessionRollbackOption = RollbackOption
SessionRollbackSelectionPlan = RollbackSelectionPlan
SessionRollbackRestoreResult = RollbackRestoreResult

WorkbookImportFlowUseCases = SessionImportFlowUseCases
WorkbookRecoveryUseCases = SessionRecoveryUseCases
ImportWorkflow = SessionImportWorkflow
BackupWorkbook = SessionBackupRuntime
AuditTrail = SessionAuditTrail
