from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.application.use_cases.workbook_commands import RollbackSelectionPlan, WorkbookRecoveryUseCases
from app.services.audit_service import AuditEvent


class AuditHistoryReader(Protocol):
    def list_events_for_workbook(self, workbook_path: str, *, limit: int = 50) -> list[AuditEvent]: ...


@dataclass(frozen=True)
class RestoreRequest:
    backup_path: str
    rollback_source: str
    metadata: dict[str, object]
    label: str
    confirmation_title: str
    confirmation_message: str


@dataclass(frozen=True)
class OperationHistoryPlan:
    events: tuple[AuditEvent, ...]
    empty_title: str
    empty_message: str


@dataclass(frozen=True)
class RollbackChoiceView:
    label: str
    request: RestoreRequest


@dataclass(frozen=True)
class RollbackDialogPlan:
    prompt: str
    choices: tuple[RollbackChoiceView, ...]


class RecoveryOperationsUseCases:
    def __init__(self, recovery_use_cases: WorkbookRecoveryUseCases, audit_reader: AuditHistoryReader):
        self.recovery_use_cases = recovery_use_cases
        self.audit_reader = audit_reader

    def build_operation_history_plan(self, workbook_path: str, *, limit: int = 200) -> OperationHistoryPlan:
        events = tuple(self.audit_reader.list_events_for_workbook(workbook_path, limit=limit))
        return OperationHistoryPlan(
            events=events,
            empty_title="Historico de Operacoes",
            empty_message="Nenhuma operacao auditada foi encontrada para esta planilha.",
        )

    def build_restore_request_for_event(self, event: AuditEvent) -> RestoreRequest:
        summary = str(getattr(event, "summary", "") or "").strip()
        return RestoreRequest(
            backup_path=str(getattr(event, "backup_path", "") or "").strip(),
            rollback_source="operation_audit",
            metadata={
                "event_id": str(getattr(event, "event_id", "") or "").strip(),
                "action": str(getattr(event, "action", "") or "").strip(),
                "summary": summary,
            },
            label=summary,
            confirmation_title="ATENCAO",
            confirmation_message=(
                f"Tem certeza que deseja restaurar a operacao '{summary}'? "
                "As alteracoes atuais serao perdidas!"
            ),
        )

    def build_rollback_dialog_plan(self, workbook_path: str, *, limit: int = 200) -> RollbackDialogPlan:
        plan = self.recovery_use_cases.build_rollback_plan(workbook_path, limit=limit)
        return RollbackDialogPlan(
            prompt=plan.prompt,
            choices=tuple(self._build_choice_view(item.label, plan) for item in plan.options),
        )

    def resolve_rollback_choice(
        self,
        dialog_plan: RollbackDialogPlan,
        selected_label: str,
    ) -> RestoreRequest | None:
        for choice in dialog_plan.choices:
            if choice.label == selected_label:
                return choice.request
        return None

    @staticmethod
    def build_no_backup_message() -> str:
        return "Nenhum backup encontrado ainda para este arquivo."

    def _build_choice_view(self, label: str, plan: RollbackSelectionPlan) -> RollbackChoiceView:
        option = next(item for item in plan.options if item.label == label)
        timestamp_prefix = label.split(" - ")[0]
        request = RestoreRequest(
            backup_path=option.backup_path,
            rollback_source=option.source_type,
            metadata=dict(option.metadata),
            label=label,
            confirmation_title="ATENCAO",
            confirmation_message=(
                f"Tem certeza que deseja restaurar a versao de {timestamp_prefix}? "
                "As alteracoes atuais serao perdidas!"
            ),
        )
        return RollbackChoiceView(label=label, request=request)
