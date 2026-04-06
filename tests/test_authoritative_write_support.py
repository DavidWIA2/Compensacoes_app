from app.application.use_cases.authoritative_write_support import (
    build_authoritative_only_status,
    build_write_status,
    clone_records,
    identity_signature,
    normalized_issues,
    resolve_finalized_records,
    status_uses_sqlite,
)
from app.application.use_cases.local_mutation_sync import LocalMutationSyncStatus
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


def test_write_status_helpers_cover_primary_and_authoritative_flows():
    sqlite_status = LocalMutationSyncStatus(
        status="sqlite",
        operation="add",
        workbook_path="base.xlsx",
        strategy="incremental",
        record_count=2,
    )

    mirrored = build_write_status(
        workbook_path="base.xlsx",
        operation="add",
        sqlite_status=sqlite_status,
        record_count=2,
        excel_mirrored=True,
        finalized=True,
        rollback_applied=False,
    )
    authoritative = build_authoritative_only_status(
        workbook_path="base.xlsx",
        operation="import",
        sqlite_status=sqlite_status,
        record_count=2,
        finalized=False,
    )

    assert mirrored.status == "sqlite_primary"
    assert mirrored.finalized is True
    assert authoritative.status == "sqlite_authoritative"
    assert authoritative.uses_sqlite is True


def test_finalize_resolution_detects_identity_change():
    current = [make_record(uid="u-1", excel_row=2), make_record(uid="u-2", excel_row=3)]
    finalized_records, finalized = resolve_finalized_records(
        current_records=current,
        finalized_records_factory=lambda: [make_record(uid="u-1", excel_row=2), make_record(uid="u-2", excel_row=10)],
    )

    assert finalized is True
    assert [record.excel_row for record in finalized_records] == [2, 10]


def test_small_write_helpers_keep_identity_and_issues_stable():
    records = [make_record(uid="u-2", excel_row=4), make_record(uid="u-1", excel_row=2)]
    cloned = clone_records(records)

    assert identity_signature(records) == (("u-1", 2), ("u-2", 4))
    assert normalized_issues(("warn", "warn"), ("other",)) == ("warn", "other")
    assert status_uses_sqlite(LocalMutationSyncStatus(status="sqlite", operation="x", workbook_path="base.xlsx"))
    assert cloned[0] is not records[0]
