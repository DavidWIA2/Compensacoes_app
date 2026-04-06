from __future__ import annotations

from dataclasses import dataclass

from app.application.use_cases.workbook_commands_support import RollbackOption, RollbackSelectionPlan
from app.services.audit_service import AuditEvent


@dataclass(frozen=True)
class RestoreRequestContent:
    label: str
    confirmation_title: str
    confirmation_message: str
    metadata: dict[str, object]


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


def build_operation_restore_request_content(
    *,
    summary: str,
    event_id: str,
    action: str,
) -> RestoreRequestContent:
    normalized_summary = str(summary or "").strip()
    return RestoreRequestContent(
        label=normalized_summary,
        confirmation_title="ATENCAO",
        confirmation_message=(
            f"Tem certeza que deseja restaurar a operacao '{normalized_summary}'? "
            "As alteracoes atuais serao perdidas!"
        ),
        metadata={
            "event_id": str(event_id or "").strip(),
            "action": str(action or "").strip(),
            "summary": normalized_summary,
        },
    )


def build_rollback_restore_request_content(
    *,
    label: str,
    metadata: dict[str, object] | None,
) -> RestoreRequestContent:
    resolved_label = str(label or "").strip()
    timestamp_prefix = resolved_label.split(" - ")[0]
    return RestoreRequestContent(
        label=resolved_label,
        confirmation_title="ATENCAO",
        confirmation_message=(
            f"Tem certeza que deseja restaurar a versao de {timestamp_prefix}? "
            "As alteracoes atuais serao perdidas!"
        ),
        metadata=dict(metadata or {}),
    )


def build_restore_request(
    *,
    backup_path: str,
    rollback_source: str,
    label: str,
    confirmation_title: str,
    confirmation_message: str,
    metadata: dict[str, object],
) -> RestoreRequest:
    return RestoreRequest(
        backup_path=backup_path,
        rollback_source=rollback_source,
        metadata=metadata,
        label=label,
        confirmation_title=confirmation_title,
        confirmation_message=confirmation_message,
    )


def build_operation_history_plan(events: tuple[AuditEvent, ...]) -> OperationHistoryPlan:
    return OperationHistoryPlan(
        events=events,
        empty_title="Historico de Operacoes",
        empty_message="Nenhuma operacao auditada foi encontrada para esta sessao.",
    )


def build_rollback_choice_view(
    *,
    option: RollbackOption,
    selection_plan: RollbackSelectionPlan,
) -> RollbackChoiceView:
    content = build_rollback_restore_request_content(
        label=option.label,
        metadata=dict(option.metadata),
    )
    return RollbackChoiceView(
        label=option.label,
        request=build_restore_request(
            backup_path=option.backup_path,
            rollback_source=option.source_type,
            metadata=content.metadata,
            label=content.label,
            confirmation_title=content.confirmation_title,
            confirmation_message=content.confirmation_message,
        ),
    )


def build_rollback_dialog_plan(selection_plan: RollbackSelectionPlan) -> RollbackDialogPlan:
    return RollbackDialogPlan(
        prompt=selection_plan.prompt,
        choices=tuple(
            build_rollback_choice_view(option=option, selection_plan=selection_plan)
            for option in selection_plan.options
        ),
    )


def resolve_rollback_choice_by_label(
    dialog_plan: RollbackDialogPlan,
    selected_label: str,
) -> RestoreRequest | None:
    for choice in dialog_plan.choices:
        if choice.label == selected_label:
            return choice.request
    return None
