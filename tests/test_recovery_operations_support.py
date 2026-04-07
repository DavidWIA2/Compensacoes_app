from app.application.use_cases.recovery_operations_support import (
    build_operation_history_plan,
    build_operation_restore_request_content,
    build_restore_request,
    build_rollback_choice_view,
    build_rollback_dialog_plan,
    build_rollback_restore_request_content,
    resolve_rollback_choice_by_label,
)
from app.application.use_cases.workbook_commands_support import RollbackOption, RollbackSelectionPlan
from app.services.audit_service import AuditEvent


def test_build_operation_restore_request_content_uses_summary_and_metadata():
    content = build_operation_restore_request_content(
        summary="Registro alterado: AT-1",
        event_id="evt-1",
        action="edit",
    )

    assert content.label == "Registro alterado: AT-1"
    assert content.confirmation_title == "ATENCAO"
    assert "restaurar a operação 'Registro alterado: AT-1'" in content.confirmation_message
    assert content.metadata == {
        "event_id": "evt-1",
        "action": "edit",
        "summary": "Registro alterado: AT-1",
    }


def test_build_rollback_restore_request_content_uses_timestamp_prefix():
    content = build_rollback_restore_request_content(
        label="31/03/2026 12:00:00 - EDIT - Registro alterado",
        metadata={"event_id": "evt-2"},
    )

    assert content.label == "31/03/2026 12:00:00 - EDIT - Registro alterado"
    assert "restaurar a versão de 31/03/2026 12:00:00" in content.confirmation_message
    assert content.metadata == {"event_id": "evt-2"}


def test_recovery_support_builds_history_and_dialog_plan():
    event = AuditEvent(
        event_id="evt-1",
        timestamp="2026-03-31T12:00:00+00:00",
        workbook_path="C:/tmp/base.xlsx",
        action="edit",
        summary="Registro alterado: AT-1",
        backup_path="C:/tmp/backup.xlsx",
        metadata={},
    )
    history_plan = build_operation_history_plan((event,))
    selection_plan = RollbackSelectionPlan(
        prompt="Escolha",
        options=(
            RollbackOption(
                label="31/03/2026 12:00:00 - EDIT - Registro alterado",
                backup_path="C:/tmp/backup.xlsx",
                source_type="operation_audit",
                metadata={"event_id": "evt-1"},
            ),
        ),
    )

    dialog_plan = build_rollback_dialog_plan(selection_plan)
    resolved = resolve_rollback_choice_by_label(dialog_plan, dialog_plan.choices[0].label)

    assert history_plan.events == (event,)
    assert dialog_plan.prompt == "Escolha"
    assert resolved is not None
    assert resolved.rollback_source == "operation_audit"


def test_recovery_support_builds_restore_request_and_choice_view():
    request = build_restore_request(
        backup_path="C:/tmp/backup.xlsx",
        rollback_source="operation_audit",
        metadata={"event_id": "evt-1"},
        label="Registro alterado",
        confirmation_title="ATENCAO",
        confirmation_message="Confirma?",
    )
    selection_plan = RollbackSelectionPlan(
        prompt="Escolha",
        options=(
            RollbackOption(
                label="31/03/2026 12:00:00 - EDIT - Registro alterado",
                backup_path="C:/tmp/backup.xlsx",
                source_type="operation_audit",
                metadata={"event_id": "evt-1"},
            ),
        ),
    )
    choice = build_rollback_choice_view(option=selection_plan.options[0], selection_plan=selection_plan)

    assert request.label == "Registro alterado"
    assert choice.request.metadata == {"event_id": "evt-1"}
