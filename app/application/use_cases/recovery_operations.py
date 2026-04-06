from __future__ import annotations

from typing import Protocol

from app.application.use_cases.recovery_operations_support import (
    OperationHistoryPlan,
    RestoreRequest,
    RollbackDialogPlan,
    build_operation_history_plan,
    build_operation_restore_request_content,
    build_restore_request,
    build_rollback_choice_view,
    build_rollback_dialog_plan,
    resolve_rollback_choice_by_label,
)
from app.application.use_cases.workbook_commands import SessionRecoveryUseCases, SessionRollbackSelectionPlan
from app.services.audit_service import AuditEvent


class AuditHistoryReader(Protocol):
    def list_events_for_session(self, session_path: str, *, limit: int = 50) -> list[AuditEvent]: ...

    def list_events_for_workbook(self, workbook_path: str, *, limit: int = 50) -> list[AuditEvent]: ...


class RecoveryOperationsUseCases:
    def __init__(self, recovery_use_cases: SessionRecoveryUseCases, audit_reader: AuditHistoryReader):
        self.recovery_use_cases = recovery_use_cases
        self.audit_reader = audit_reader

    def _list_session_events(self, workbook_path: str, *, limit: int) -> list[AuditEvent]:
        if hasattr(self.audit_reader, "list_events_for_session"):
            return self.audit_reader.list_events_for_session(workbook_path, limit=limit)
        return self.audit_reader.list_events_for_workbook(workbook_path, limit=limit)

    def build_operation_history_plan(self, workbook_path: str, *, limit: int = 200) -> OperationHistoryPlan:
        events = tuple(self._list_session_events(workbook_path, limit=limit))
        return build_operation_history_plan(events)

    def build_restore_request_for_event(self, event: AuditEvent) -> RestoreRequest:
        content = build_operation_restore_request_content(
            summary=str(getattr(event, "summary", "") or "").strip(),
            event_id=str(getattr(event, "event_id", "") or "").strip(),
            action=str(getattr(event, "action", "") or "").strip(),
        )
        return build_restore_request(
            backup_path=str(getattr(event, "backup_path", "") or "").strip(),
            rollback_source="operation_audit",
            metadata=content.metadata,
            label=content.label,
            confirmation_title=content.confirmation_title,
            confirmation_message=content.confirmation_message,
        )

    def build_rollback_dialog_plan(self, workbook_path: str, *, limit: int = 200) -> RollbackDialogPlan:
        plan = self.recovery_use_cases.build_rollback_plan(workbook_path, limit=limit)
        return build_rollback_dialog_plan(plan)

    def resolve_rollback_choice(
        self,
        dialog_plan: RollbackDialogPlan,
        selected_label: str,
    ) -> RestoreRequest | None:
        return resolve_rollback_choice_by_label(dialog_plan, selected_label)

    @staticmethod
    def build_no_backup_message() -> str:
        return "Nenhum backup encontrado ainda para este arquivo."

    def _build_choice_view(self, label: str, plan: SessionRollbackSelectionPlan):
        option = next(item for item in plan.options if item.label == label)
        return build_rollback_choice_view(option=option, selection_plan=plan)


SessionRecoveryOperationsUseCases = RecoveryOperationsUseCases
