from pathlib import Path

from app.application.use_cases.workbook_commands_support import (
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


def test_import_support_builds_payloads_and_results():
    records = [make_record(uid="uid-10")]
    analysis = make_analysis("origem.xlsx", records)

    payload = build_import_audit_payload(
        analysis=analysis,
        records_to_add=records,
        imported_count=1,
        backup_path="C:/tmp/import-backup.xlsx",
    )
    result = build_import_execution_result(
        analysis=analysis,
        imported_count=1,
        backup_path="C:/tmp/import-backup.xlsx",
        imported_records=records,
    )

    assert payload["action"] == "import"
    assert payload["metadata"]["skipped_by_uid"] == 1
    assert result.session_backup_path.endswith("import-backup.xlsx")
    assert result.imported_records == (records[0],)


def test_rollback_support_builds_labels_options_and_results(tmp_path):
    backup_path = tmp_path / "audit-backup.xlsx"
    backup_path.write_text("snapshot", encoding="utf-8")
    event = AuditEvent(
        event_id="evt-1",
        timestamp="2026-03-31T15:00:00+00:00",
        workbook_path="C:/tmp/base.xlsx",
        action="edit",
        summary="Registro alterado: AT-1",
        backup_path=str(backup_path),
        metadata={},
    )

    label = build_audited_rollback_label(event)
    option = build_audited_rollback_option(event=event, label=label)
    legacy = build_legacy_rollback_option(file_path=str(backup_path), timestamp_label="31/03/2026 12:00:00")
    selection_plan = build_rollback_selection_plan(prompt="Escolha", options=[option, legacy])
    restore_payload = build_restore_audit_payload(
        source_backup_path=str(backup_path),
        rollback_source="operation_audit",
        metadata={"event_id": "evt-1"},
        label=label,
        backup_path="C:/tmp/rollback.xlsx",
    )
    restore_result = build_rollback_restore_result(
        session_path="C:/tmp/base.xlsx",
        source_backup_path=str(backup_path),
        rollback_source="operation_audit",
        label=label,
        backup_path="C:/tmp/rollback.xlsx",
    )

    assert "EDIT - Registro alterado: AT-1" in label
    assert option.source_type == "operation_audit"
    assert legacy.metadata["filename"] == backup_path.name
    assert len(selection_plan.options) == 2
    assert Path(restore_payload["metadata"]["source_backup_path"]) == backup_path.resolve()
    assert restore_result.session_path == "C:/tmp/base.xlsx"


def test_runtime_path_and_timestamp_helpers_are_stable():
    runtime = type("Runtime", (), {"session_path": "", "path": "C:/tmp/base.xlsx"})()

    assert resolve_runtime_session_path(runtime) == "C:/tmp/base.xlsx"
    assert format_rollback_timestamp("2026-03-31T15:00:00+00:00") == "31/03/2026 15:00:00"
