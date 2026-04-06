from types import SimpleNamespace

from app.application.use_cases.authoritative_persistence_support import (
    build_authoritative_workbook_load_result,
    build_monitoring_snapshot,
    build_runtime_record_result,
    build_session_availability,
    current_session_path,
    current_workbook_path,
    get_session_snapshot_summary,
    has_snapshot_data,
    list_session_records,
    restore_workbook_service_state,
    snapshot_workbook_service_state,
    sync_session_snapshot,
    try_touch_session_catalog_entry,
)
from app.models.compensacao import Compensacao
from app.application.use_cases.workbook_session import LoadSessionResult


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


class SessionSnapshotPersistence:
    def __init__(self):
        self.calls = []

    def get_session_snapshot_summary(self, workbook_path):
        self.calls.append(("summary", workbook_path))
        return SimpleNamespace(synced_at="2026-04-05T10:00:00+00:00", record_count=3)

    def list_records_for_session(self, workbook_path):
        self.calls.append(("list", workbook_path))
        return [make_record(uid="s-1")]

    def sync_session_snapshot(self, workbook_path, records):
        self.calls.append(("sync", workbook_path, len(records)))
        return SimpleNamespace(workbook_path=workbook_path, synced_at="ok", record_count=len(records))


class WorkbookSnapshotPersistence:
    def __init__(self):
        self.calls = []

    def get_workbook_snapshot_summary(self, workbook_path):
        self.calls.append(("summary", workbook_path))
        return SimpleNamespace(synced_at="", record_count=1)

    def list_records_for_workbook(self, workbook_path):
        self.calls.append(("list", workbook_path))
        return [make_record(uid="w-1")]

    def sync_workbook_snapshot(self, workbook_path, records):
        self.calls.append(("sync", workbook_path, len(records)))
        return SimpleNamespace(workbook_path=workbook_path, synced_at="ok", record_count=len(records))


class TouchPersistence:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.touched = []

    def touch_session(self, session_path):
        if self.fail:
            raise RuntimeError("catalog offline")
        self.touched.append(session_path)


def test_current_runtime_paths_prefer_session_path():
    workbook = SimpleNamespace(path="base.xlsx", session_path="session://banco-local")

    assert current_workbook_path(workbook) == "base.xlsx"
    assert current_session_path(workbook) == "session://banco-local"


def test_snapshot_dispatch_supports_session_and_workbook_variants():
    session_persistence = SessionSnapshotPersistence()
    workbook_persistence = WorkbookSnapshotPersistence()

    session_summary = get_session_snapshot_summary(session_persistence, "session://banco-local")
    workbook_summary = get_session_snapshot_summary(workbook_persistence, "base.xlsx")
    session_records = list_session_records(session_persistence, "session://banco-local")
    workbook_records = list_session_records(workbook_persistence, "base.xlsx")
    session_sync = sync_session_snapshot(session_persistence, "session://banco-local", session_records)
    workbook_sync = sync_session_snapshot(workbook_persistence, "base.xlsx", workbook_records)

    assert session_summary.record_count == 3
    assert workbook_summary.record_count == 1
    assert [record.uid for record in session_records] == ["s-1"]
    assert [record.uid for record in workbook_records] == ["w-1"]
    assert session_sync.record_count == 1
    assert workbook_sync.record_count == 1


def test_has_snapshot_data_checks_synced_at_or_record_count():
    assert has_snapshot_data(SimpleNamespace(synced_at="", record_count=0)) is False
    assert has_snapshot_data(SimpleNamespace(synced_at="2026-04-05T10:00:00+00:00", record_count=0)) is True
    assert has_snapshot_data(SimpleNamespace(synced_at="", record_count=2)) is True


def test_build_session_availability_uses_catalog_display_name(tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("ok", encoding="utf-8")
    persistence = SimpleNamespace(get_session_display_name=lambda _path: "Banco local")

    availability = build_session_availability(
        str(workbook_path),
        has_local_snapshot=True,
        persistence_service=persistence,
    )

    assert availability.source_kind == "hybrid"
    assert availability.display_label == "Banco local"
    assert availability.is_openable is True


def test_snapshot_and_restore_workbook_state_support():
    workbook = SimpleNamespace(
        path="base.xlsx",
        wb=object(),
        ws=object(),
        plantio_ws=object(),
        col_map={"uid": 1},
        plantio_col_map={"plantio": 2},
        uid_to_row={"uid-1": 9},
        last_backup_time="2026-03-31T12:00:00+00:00",
        merged_cells_warning=None,
    )

    snapshot = snapshot_workbook_service_state(workbook)
    workbook.path = "alterado.xlsx"
    workbook.col_map = {}
    workbook.uid_to_row = {}

    restore_workbook_service_state(workbook, snapshot)

    assert workbook.path == "base.xlsx"
    assert workbook.col_map == {"uid": 1}
    assert workbook.uid_to_row == {"uid-1": 9}


def test_build_runtime_record_and_load_results_keep_snapshot_context():
    records = (make_record(uid="uid-1"),)
    snapshot = SimpleNamespace(synced_at="2026-04-05T10:00:00+00:00", record_count=4)
    record_source = build_runtime_record_result(
        source="sqlite",
        records=records,
        strategy="sqlite_runtime",
        workbook_path="session://banco-local",
        metrics=SimpleNamespace(total=1),
        snapshot=snapshot,
    )
    read_status = SimpleNamespace(source="sqlite", strategy="sqlite_runtime")
    load_result = LoadSessionResult(path="session://banco-local", records=list(records))
    result = build_authoritative_workbook_load_result(
        path="session://banco-local",
        loaded_records=records,
        record_source=record_source,
        local_session_source_status=read_status,
        load_result=load_result,
        issues=("ok",),
        snapshot_status=snapshot,
    )

    assert record_source.mirrored_records == 4
    assert result.records[0].uid == "uid-1"
    assert result.load_result.path == "session://banco-local"
    assert result.session_path == "session://banco-local"


def test_build_monitoring_snapshot_wraps_reports():
    persistence_report = SimpleNamespace(status="sincronizado")
    overview_report = SimpleNamespace(total_records=4)

    snapshot = build_monitoring_snapshot(
        "session://banco-local",
        persistence_report=persistence_report,
        record_overview_report=overview_report,
    )

    assert snapshot.session_path == "session://banco-local"
    assert snapshot.persistence_report.status == "sincronizado"
    assert snapshot.record_overview_report.total_records == 4


def test_try_touch_session_catalog_entry_is_resilient():
    warnings = []
    ok_persistence = TouchPersistence()
    fail_persistence = TouchPersistence(fail=True)

    try_touch_session_catalog_entry(ok_persistence, "session://ok")
    try_touch_session_catalog_entry(
        fail_persistence,
        "session://fail",
        logger_warning=lambda session_path: warnings.append(session_path),
    )

    assert ok_persistence.touched == ["session://ok"]
    assert warnings == ["session://fail"]
