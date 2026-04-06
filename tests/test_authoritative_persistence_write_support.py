from app.application.use_cases.authoritative_persistence_write_support import (
    assign_provisional_add_identity,
    assign_provisional_import_identities,
    build_batch_geocode_audit_after_payload,
    build_batch_geocode_audit_metadata,
    build_import_audit_after_payload,
    build_import_audit_metadata,
    build_import_execution_result,
)
from app.application.use_cases.workbook_session import ImportWorkbookAnalysis
from app.models.compensacao import Compensacao


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "",
        "compensado": "",
        "latitude": "",
        "longitude": "",
        "uid": "test-uid-123",
    }
    base.update(overrides)
    return Compensacao(**base)


def test_assign_provisional_add_identity_fills_missing_uid_and_excel_row():
    existing = [make_record(uid="uid-base", excel_row=8)]
    record = make_record(uid="", excel_row=0)

    assign_provisional_add_identity(record, existing_records=existing)

    assert record.uid
    assert record.uid != "uid-base"
    assert record.excel_row == 9


def test_assign_provisional_import_identities_keeps_unique_rows_and_uids():
    existing = [make_record(uid="uid-base", excel_row=8)]
    imported = [
        make_record(uid="", excel_row=0, av_tec="AT-1"),
        make_record(uid="uid-base", excel_row=0, av_tec="AT-2"),
    ]

    assign_provisional_import_identities(imported, existing_records=existing)

    assert imported[0].uid
    assert imported[1].uid not in {"", "uid-base"}
    assert imported[0].excel_row == 9
    assert imported[1].excel_row == 10


def test_build_import_payload_helpers_keep_expected_counts():
    imported = [make_record(uid="novo-1"), make_record(uid="novo-2")]
    analysis = ImportWorkbookAnalysis(
        import_path="C:/dados/importar.xlsx",
        incoming_records=list(imported),
        records_to_add=list(imported),
        skipped_by_uid=1,
        skipped_by_av_tec=2,
        skipped_uid_details=[],
        skipped_av_tec_details=[],
        invalid_issues=[],
    )

    result = build_import_execution_result(
        analysis=analysis,
        imported_records=imported,
        backup_path="C:/tmp/import.json",
    )
    metadata = build_import_audit_metadata(analysis=analysis, import_result=result)
    after = build_import_audit_after_payload(imported)

    assert result.imported_count == 2
    assert result.backup_path.endswith(".json")
    assert metadata["source_path"].endswith("dados\\importar.xlsx")
    assert metadata["skipped_by_uid"] == 1
    assert after["imported_count"] == 2
    assert len(after["sample_records"]) == 2


def test_build_batch_geocode_audit_payloads_sample_updated_rows():
    updated = [
        make_record(uid="geo-1", excel_row=12),
        make_record(uid="geo-2", excel_row=13),
    ]

    metadata = build_batch_geocode_audit_metadata(updated)
    after = build_batch_geocode_audit_after_payload(updated)

    assert metadata["updated_records"] == 2
    assert metadata["sample_rows"] == [12, 13]
    assert metadata["sample_uids"] == ["geo-1", "geo-2"]
    assert after["updated_count"] == 2
    assert len(after["sample_records"]) == 2
