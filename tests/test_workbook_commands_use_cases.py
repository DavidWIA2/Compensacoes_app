from __future__ import annotations

from pathlib import Path

from app.application.use_cases.workbook_commands import (
    SessionImportExecutionResult,
    SessionImportFlowUseCases,
    SessionRecoveryUseCases,
    WorkbookImportFlowUseCases,
    WorkbookRecoveryUseCases,
)
from app.application.use_cases.workbook_session import ImportWorkbookAnalysis
from app.models.compensacao import Compensacao
from app.services.audit_service import AuditEvent


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 3,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "Gregorio",
        "compensado": "",
        "uid": "uid-1",
    }
    base.update(overrides)
    return Compensacao(**base)


class FakeImportWorkflow:
    def __init__(self, *, import_result=None):
        self.import_result = import_result
        self.import_calls = []

    def import_records(self, records, *, progress_callback=None) -> int:
        imported_records = list(records)
        self.import_calls.append(imported_records)
        if progress_callback:
            total = len(imported_records)
            for index, _record in enumerate(imported_records, start=1):
                progress_callback(index, total)
        return self.import_result if self.import_result is not None else len(imported_records)


class FakeWorkbook:
    def __init__(self, path: str, *, backup_path: str):
        self.path = path
        self.backup_path = backup_path
        self.backup_labels = []

    def create_operation_backup(self, label: str) -> str:
        self.backup_labels.append(label)
        return self.backup_path


class FakeAuditTrail:
    def __init__(self, *, events=None):
        self.events = list(events or [])
        self.append_calls = []

    def list_events_for_workbook(self, workbook_path: str, *, limit: int = 50) -> list[AuditEvent]:
        return list(self.events)[:limit]

    def list_events_for_session(self, session_path: str, *, limit: int = 50) -> list[AuditEvent]:
        return self.list_events_for_workbook(session_path, limit=limit)

    def append_event(self, **payload) -> AuditEvent:
        self.append_calls.append(payload)
        return AuditEvent(
            event_id="evt-appended",
            timestamp="2026-03-31T12:00:00+00:00",
            workbook_path=payload["workbook_path"],
            action=payload["action"],
            summary=payload["summary"],
            backup_path=payload.get("backup_path", ""),
            metadata=dict(payload.get("metadata") or {}),
            before=payload.get("before"),
            after=payload.get("after"),
        )

    def append_session_event(self, **payload) -> AuditEvent:
        payload = dict(payload)
        payload["workbook_path"] = payload.pop("session_path")
        return self.append_event(**payload)


def make_analysis(import_path: str, records_to_add: list[Compensacao]) -> ImportWorkbookAnalysis:
    return ImportWorkbookAnalysis(
        import_path=import_path,
        incoming_records=list(records_to_add),
        records_to_add=list(records_to_add),
        skipped_by_uid=1,
        skipped_by_av_tec=2,
        skipped_uid_details=[],
        skipped_av_tec_details=[],
        invalid_issues=[],
    )


def test_import_flow_creates_backup_and_audit_entry(tmp_path):
    current_workbook = tmp_path / "base.xlsx"
    current_workbook.write_text("base", encoding="utf-8")
    workflow = FakeImportWorkflow(import_result=1)
    workbook = FakeWorkbook(str(current_workbook), backup_path=str(tmp_path / "import-backup.xlsx"))
    audit_trail = FakeAuditTrail()
    imported_record = make_record(uid="uid-10", av_tec="AT-10")
    analysis = make_analysis("origem.xlsx", [imported_record])
    progress_updates = []
    use_cases = WorkbookImportFlowUseCases(workflow, workbook, audit_trail)

    result = use_cases.execute_import(
        analysis,
        progress_callback=lambda current, total: progress_updates.append((current, total)),
    )

    assert workbook.backup_labels == ["import"]
    assert workflow.import_calls == [[imported_record]]
    assert progress_updates == [(1, 1)]
    assert result.imported_count == 1
    assert result.session_backup_path.endswith("import-backup.xlsx")
    assert result.backup_path.endswith("import-backup.xlsx")
    assert result.imported_records == (imported_record,)
    assert audit_trail.append_calls[0]["action"] == "import"
    assert audit_trail.append_calls[0]["metadata"]["imported_records"] == 1
    assert audit_trail.append_calls[0]["metadata"]["skipped_by_uid"] == 1


def test_recovery_use_cases_prefer_audited_options_when_available(tmp_path):
    current_workbook = tmp_path / "base.xlsx"
    current_workbook.write_text("base", encoding="utf-8")
    event_backup = tmp_path / "audit-backup.xlsx"
    event_backup.write_text("snapshot", encoding="utf-8")
    legacy_dir = tmp_path / "backups_historico"
    legacy_dir.mkdir()
    (legacy_dir / "legacy.xlsx").write_text("legacy", encoding="utf-8")

    audit_event = AuditEvent(
        event_id="evt-1",
        timestamp="2026-03-31T15:00:00+00:00",
        workbook_path=str(current_workbook),
        action="edit",
        summary="Registro alterado: AT-1",
        backup_path=str(event_backup),
        metadata={},
    )
    use_cases = WorkbookRecoveryUseCases(
        FakeWorkbook(str(current_workbook), backup_path=str(tmp_path / "rollback.xlsx")),
        FakeAuditTrail(events=[audit_event]),
    )

    plan = use_cases.build_rollback_plan(str(current_workbook))

    assert plan.prompt == use_cases.AUDITED_PROMPT
    assert len(plan.options) == 1
    assert plan.options[0].source_type == "operation_audit"
    assert "EDIT - Registro alterado: AT-1" in plan.options[0].label


def test_recovery_use_cases_restore_backup_and_audit_event(tmp_path):
    current_workbook = tmp_path / "base.xlsx"
    current_workbook.write_text("atual", encoding="utf-8")
    selected_backup = tmp_path / "selecionado.xlsx"
    selected_backup.write_text("snapshot", encoding="utf-8")
    workbook = FakeWorkbook(str(current_workbook), backup_path=str(tmp_path / "rollback-backup.xlsx"))
    audit_trail = FakeAuditTrail()
    use_cases = WorkbookRecoveryUseCases(workbook, audit_trail)

    result = use_cases.restore_backup(
        str(selected_backup),
        rollback_source="operation_audit",
        metadata={"event_id": "evt-restore"},
        label="31/03/2026 12:00:00 - EDIT - Registro alterado",
    )

    assert current_workbook.read_text(encoding="utf-8") == "snapshot"
    assert workbook.backup_labels == ["rollback"]
    assert result.session_path == str(current_workbook)
    assert result.rollback_source == "operation_audit"
    assert Path(result.source_backup_path) == selected_backup.resolve()
    assert audit_trail.append_calls[0]["action"] == "rollback"
    assert audit_trail.append_calls[0]["metadata"]["source_type"] == "operation_audit"
    assert audit_trail.append_calls[0]["metadata"]["event_id"] == "evt-restore"


def test_recovery_use_cases_fall_back_to_legacy_backups(tmp_path):
    current_workbook = tmp_path / "base.xlsx"
    current_workbook.write_text("base", encoding="utf-8")
    legacy_dir = tmp_path / "backups_historico"
    legacy_dir.mkdir()
    legacy_backup = legacy_dir / "legacy.xlsx"
    legacy_backup.write_text("legacy", encoding="utf-8")
    use_cases = WorkbookRecoveryUseCases(
        FakeWorkbook(str(current_workbook), backup_path=str(tmp_path / "rollback.xlsx")),
        FakeAuditTrail(),
    )

    plan = use_cases.build_rollback_plan(str(current_workbook))

    assert plan.prompt == use_cases.LEGACY_PROMPT
    assert len(plan.options) == 1
    assert plan.options[0].source_type == "legacy_backup"
    assert plan.options[0].metadata["filename"] == "legacy.xlsx"


def test_workbook_command_use_cases_expose_session_aliases(tmp_path):
    current_workbook = tmp_path / "base.xlsx"
    current_workbook.write_text("base", encoding="utf-8")
    workflow = FakeImportWorkflow(import_result=1)
    workbook = FakeWorkbook(str(current_workbook), backup_path=str(tmp_path / "import-backup.xlsx"))
    audit_trail = FakeAuditTrail()
    analysis = make_analysis("origem.xlsx", [make_record(uid="uid-10", av_tec="AT-10")])

    import_use_cases = SessionImportFlowUseCases(workflow, workbook, audit_trail)
    recovery_use_cases = SessionRecoveryUseCases(workbook, audit_trail)
    result = import_use_cases.execute_import(analysis)

    assert isinstance(result, SessionImportExecutionResult)
    assert result.session_backup_path.endswith("import-backup.xlsx")
    assert recovery_use_cases.build_audited_rollback_options(str(current_workbook), limit=10) == ()
