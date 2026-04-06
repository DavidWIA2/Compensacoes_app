from app.application.use_cases.local_mutation_sync_support import (
    build_apply_result,
    build_sync_status,
    clone_records,
    extend_status_issues,
    list_session_records_dispatch,
    normalized_workbook_path,
    project_records_after_add,
    project_records_after_delete,
    project_records_after_edit,
    project_records_after_import,
    resolve_incremental_method,
    sort_records,
    sync_snapshot_dispatch,
)
from app.models.compensacao import Compensacao
from app.services.sqlite_mirror_service import WorkbookSnapshotSummary


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
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


class SessionWriter:
    def __init__(self):
        self.calls = []
        self.records = {}

    def sync_session_snapshot(self, workbook_path, records):
        self.calls.append(("sync", workbook_path, len(records)))
        self.records[workbook_path] = list(records)
        return WorkbookSnapshotSummary(
            workbook_path=workbook_path,
            synced_at="2026-04-05T10:00:00+00:00",
            record_count=len(records),
            plantio_count=0,
            audit_event_count=0,
        )

    def list_records_for_session(self, workbook_path):
        self.calls.append(("list", workbook_path))
        return list(self.records.get(workbook_path, []))

    def append_record_to_session(self, workbook_path, record):
        self.calls.append(("append", workbook_path, record.uid))
        return "ok"


def test_projection_helpers_cover_add_edit_delete_import():
    existing = [
        make_record(uid="u-1", excel_row=2, av_tec="AT-1"),
        make_record(uid="u-2", excel_row=3, av_tec="AT-2"),
    ]
    added = make_record(uid="u-3", excel_row=4, av_tec="AT-3")
    edited = make_record(uid="u-2", excel_row=3, endereco="Rua B")

    assert [record.uid for record in project_records_after_add(existing, added)] == ["u-1", "u-2", "u-3"]
    assert project_records_after_edit(existing, edited)[1].endereco == "Rua B"
    assert [record.uid for record in project_records_after_delete(existing, existing[0])] == ["u-2"]
    assert [record.uid for record in project_records_after_import(existing, [added])] == ["u-1", "u-2", "u-3"]


def test_dispatch_helpers_use_session_variants_when_available():
    writer = SessionWriter()
    records = [make_record(uid="u-1")]

    summary = sync_snapshot_dispatch(writer, "session://banco-local", records)
    listed = list_session_records_dispatch(writer, "session://banco-local")
    incremental = resolve_incremental_method(writer, "append_record_to_workbook")

    assert summary.record_count == 1
    assert [record.uid for record in listed] == ["u-1"]
    assert callable(incremental)
    assert writer.calls[:2] == [("sync", "session://banco-local", 1), ("list", "session://banco-local")]


def test_status_and_apply_helpers_preserve_projection_and_sqlite_results():
    projected = [make_record(uid="u-1"), make_record(uid="u-2", excel_row=3)]
    sqlite_records = [make_record(uid="u-1", endereco="SQLite"), make_record(uid="u-2", excel_row=3)]
    status = build_sync_status(
        status="sqlite",
        operation="edit",
        workbook_path="base.xlsx",
        strategy="incremental",
        record_count=2,
    )
    extended = extend_status_issues(status, "warn-1", "warn-2")
    sqlite_result = build_apply_result(
        status=extended,
        projected_records=projected,
        sqlite_records=sqlite_records,
        source="sqlite",
    )
    projection_result = build_apply_result(
        status=extended,
        projected_records=projected,
        source="projection",
    )

    assert extended.issues == ("warn-1", "warn-2")
    assert sqlite_result.source == "sqlite"
    assert sqlite_result.records[0].endereco == "SQLite"
    assert projection_result.records[0].endereco == "Rua A"


def test_small_pure_helpers_keep_paths_and_clones_stable():
    records = [make_record(uid="u-2", excel_row=4), make_record(uid="u-1", excel_row=2)]
    sorted_records = sort_records(records)
    cloned_records = clone_records(records)

    assert normalized_workbook_path("  C:/tmp/base.xlsx  ") == "C:/tmp/base.xlsx"
    assert [record.uid for record in sorted_records] == ["u-1", "u-2"]
    assert cloned_records[0] is not records[0]
