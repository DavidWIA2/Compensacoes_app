from app.application.use_cases.recovery_operations import RecoveryOperationsUseCases
from app.application.use_cases.workbook_commands import WorkbookRecoveryUseCases
from app.services.audit_service import AuditEvent


class FakeWorkbook:
    def __init__(self, path: str, *, backup_path: str):
        self.path = path
        self.backup_path = backup_path

    def create_operation_backup(self, label: str) -> str:
        return self.backup_path


class FakeAuditTrail:
    def __init__(self, events=None):
        self.events = list(events or [])

    def list_events_for_workbook(self, workbook_path: str, *, limit: int = 50):
        return list(self.events)[:limit]

    def append_event(self, **_payload):
        raise AssertionError("append_event should not be called in this test")


def test_recovery_operations_builds_history_restore_request(tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("base", encoding="utf-8")
    backup_path = tmp_path / "backup.xlsx"
    backup_path.write_text("snapshot", encoding="utf-8")
    event = AuditEvent(
        event_id="evt-1",
        timestamp="2026-03-31T12:00:00+00:00",
        workbook_path=str(workbook_path),
        action="edit",
        summary="Registro alterado: AT-1",
        backup_path=str(backup_path),
        metadata={"uid": "uid-1"},
    )
    recovery_use_cases = WorkbookRecoveryUseCases(
        FakeWorkbook(str(workbook_path), backup_path=str(tmp_path / "rollback.xlsx")),
        FakeAuditTrail([event]),
    )
    use_cases = RecoveryOperationsUseCases(recovery_use_cases, FakeAuditTrail([event]))

    history_plan = use_cases.build_operation_history_plan(str(workbook_path))
    request = use_cases.build_restore_request_for_event(event)

    assert history_plan.events == (event,)
    assert history_plan.empty_title == "Historico de Operacoes"
    assert request.backup_path == str(backup_path)
    assert request.rollback_source == "operation_audit"
    assert request.metadata["event_id"] == "evt-1"
    assert "Registro alterado: AT-1" in request.confirmation_message


def test_recovery_operations_wraps_rollback_choices(tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("base", encoding="utf-8")
    backup_path = tmp_path / "backup.xlsx"
    backup_path.write_text("snapshot", encoding="utf-8")
    event = AuditEvent(
        event_id="evt-2",
        timestamp="2026-03-31T12:00:00+00:00",
        workbook_path=str(workbook_path),
        action="import",
        summary="2 registro(s) importado(s)",
        backup_path=str(backup_path),
        metadata={"source_path": "origem.xlsx"},
    )
    recovery_use_cases = WorkbookRecoveryUseCases(
        FakeWorkbook(str(workbook_path), backup_path=str(tmp_path / "rollback.xlsx")),
        FakeAuditTrail([event]),
    )
    use_cases = RecoveryOperationsUseCases(recovery_use_cases, FakeAuditTrail([event]))

    dialog_plan = use_cases.build_rollback_dialog_plan(str(workbook_path))
    request = use_cases.resolve_rollback_choice(dialog_plan, dialog_plan.choices[0].label)

    assert dialog_plan.prompt == recovery_use_cases.AUDITED_PROMPT
    assert len(dialog_plan.choices) == 1
    assert request is not None
    assert request.rollback_source == "operation_audit"
    assert request.metadata["summary"] == "2 registro(s) importado(s)"
    assert "Tem certeza que deseja restaurar a versao de" in request.confirmation_message
    assert use_cases.build_no_backup_message() == "Nenhum backup encontrado ainda para este arquivo."
