from app.application.use_cases.local_record_queries_support import (
    LocalFilterFacetsResult,
    build_filter_facets_from_records,
    build_filter_facets_status,
    build_read_status,
    build_session_duplicate_check_result,
    build_session_filter_facets_result,
    build_session_record_result,
    build_session_selected_record_result,
    build_sqlite_duplicate_check_result,
    build_sqlite_filter_facets_result,
    build_sqlite_selected_record_result,
    find_duplicate_av_tec_in_records,
    find_record_in_sequence,
    resolve_read_status_key,
    validate_snapshot_against_runtime,
)
from app.models.compensacao import Compensacao
from app.services.sqlite_mirror_service import WorkbookSnapshotSummary


def make_record(**overrides) -> Compensacao:
    payload = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "Gregorio",
        "compensado": "",
        "latitude": "",
        "longitude": "",
        "uid": "u-1",
    }
    payload.update(overrides)
    return Compensacao(**payload)


def test_local_record_queries_support_builds_lookup_and_status_objects():
    records = [make_record(uid="u-1"), make_record(uid="u-2", excel_row=3, av_tec="AT-2", microbacia="Medeiros")]
    read_result = build_session_record_result(records, workbook_path="C:/tmp/base.xlsx", strategy="session_filter")
    read_status = build_read_status(read_result, filtered_records=1)

    assert read_status.status == "session"
    assert find_record_in_sequence(records, uid="u-2").uid == "u-2"
    assert find_record_in_sequence(records, excel_row=3).uid == "u-2"
    assert find_duplicate_av_tec_in_records(records, av_tec="AT-2") == 3
    assert resolve_read_status_key(workbook_path="", uses_sqlite=False, issues=()) == "indisponivel"
    assert resolve_read_status_key(workbook_path="C:/tmp/base.xlsx", uses_sqlite=True, issues=()) == "sqlite"

    facets = build_session_filter_facets_result(
        workbook_path="C:/tmp/base.xlsx",
        synced_at="2026-04-05T10:00:00+00:00",
        mirrored_records=2,
        session_records=2,
        microbacias=("Gregorio", "Medeiros"),
        years=("2026",),
        issues=("fallback",),
    )
    facets_status = build_filter_facets_status(facets)
    assert facets_status.status == "fallback"
    assert facets_status.micro_count == 2


def test_local_record_queries_support_builds_filter_facets_and_selection_results():
    records = [
        make_record(uid="u-1", oficio_processo="123/2026"),
        make_record(uid="u-2", excel_row=3, oficio_processo="999/2025", microbacia=""),
    ]
    micros, years = build_filter_facets_from_records(records)
    assert micros == ("Gregorio",)
    assert years == ("2026", "2025")

    selected_session = build_session_selected_record_result(
        record=records[0],
        workbook_path="C:/tmp/base.xlsx",
        synced_at="2026-04-05T10:00:00+00:00",
        mirrored_records=2,
        session_records=2,
        issues=("fallback",),
    )
    selected_sqlite = build_sqlite_selected_record_result(
        record=records[1],
        workbook_path="C:/tmp/base.xlsx",
        synced_at="2026-04-05T10:00:00+00:00",
        mirrored_records=2,
        session_records=2,
    )
    duplicate_session = build_session_duplicate_check_result(
        duplicate_row=3,
        workbook_path="C:/tmp/base.xlsx",
        synced_at="2026-04-05T10:00:00+00:00",
        mirrored_records=2,
        session_records=2,
        issues=("fallback",),
    )
    duplicate_sqlite = build_sqlite_duplicate_check_result(
        duplicate_row=2,
        workbook_path="C:/tmp/base.xlsx",
        synced_at="2026-04-05T10:00:00+00:00",
        mirrored_records=2,
        session_records=2,
    )
    sqlite_facets = build_sqlite_filter_facets_result(
        workbook_path="C:/tmp/base.xlsx",
        synced_at="2026-04-05T10:00:00+00:00",
        mirrored_records=2,
        session_records=2,
        microbacias=("Gregorio",),
        years=("2026",),
    )

    assert selected_session.issues
    assert selected_sqlite.uses_sqlite is True
    assert duplicate_session.issues
    assert duplicate_sqlite.uses_sqlite is True
    assert isinstance(sqlite_facets, LocalFilterFacetsResult)


def test_local_record_queries_support_validates_snapshot_against_runtime(tmp_path):
    workbook = tmp_path / "base.xlsx"
    workbook.write_text("conteudo", encoding="utf-8")
    stat_result = workbook.stat()
    records = [make_record(uid="u-1"), make_record(uid="u-2", excel_row=3)]
    snapshot = WorkbookSnapshotSummary(
        workbook_path=str(workbook),
        synced_at="2026-04-05T10:00:00+00:00",
        record_count=2,
        plantio_count=0,
        audit_event_count=0,
        source_mtime_ns=stat_result.st_mtime_ns,
        source_size=stat_result.st_size,
    )

    normalized_path, fallback, resolved_snapshot, early = validate_snapshot_against_runtime(
        str(workbook),
        fallback_records=records,
        snapshot_reader_available=True,
        snapshot=snapshot,
        strategy="session_filter",
    )
    assert early is None
    assert resolved_snapshot == snapshot
    assert len(fallback) == 2
    assert normalized_path

    broken_snapshot = WorkbookSnapshotSummary(
        workbook_path=str(workbook),
        synced_at="2026-04-05T10:00:00+00:00",
        record_count=1,
        plantio_count=0,
        audit_event_count=0,
        source_mtime_ns=stat_result.st_mtime_ns,
        source_size=stat_result.st_size,
    )
    _, _, _, early = validate_snapshot_against_runtime(
        str(workbook),
        fallback_records=records,
        snapshot_reader_available=True,
        snapshot=broken_snapshot,
        strategy="session_filter",
    )
    assert early is not None
    assert early.source == "session"
    assert early.issues
