from app.application.use_cases.persistence_monitoring_support import (
    build_record_overview_report_from_snapshot,
    build_status_report_from_snapshot,
    build_unavailable_record_overview_report,
    build_unavailable_status_report,
    get_record_overview,
    get_snapshot_summary,
)
from app.services.sqlite_mirror_service import (
    MirroredRecordSample,
    WorkbookRecordOverview,
    WorkbookSnapshotSummary,
)


class StubReader:
    def __init__(self, summary, overview):
        self.summary = summary
        self.overview = overview

    def get_session_snapshot_summary(self, workbook_path):
        return self.summary

    def build_session_record_overview(self, workbook_path, *, top_microbacias_limit=5, sample_limit=5):
        return self.overview


def test_monitoring_support_dispatches_session_variants():
    summary = WorkbookSnapshotSummary(
        workbook_path="C:/tmp/base.xlsx",
        synced_at="2026-04-05T10:00:00+00:00",
        record_count=4,
        plantio_count=1,
        audit_event_count=2,
    )
    overview = WorkbookRecordOverview(
        workbook_path="C:/tmp/base.xlsx",
        synced_at="2026-04-05T10:00:00+00:00",
        total_records=4,
        compensados_count=1,
        pendentes_count=3,
        records_with_plantios_count=1,
        records_without_microbacia_count=0,
        records_without_coordinates_count=1,
    )
    reader = StubReader(summary, overview)

    assert get_snapshot_summary(reader, "C:/tmp/base.xlsx").record_count == 4
    assert get_record_overview(reader, "C:/tmp/base.xlsx", top_microbacias_limit=3, sample_limit=1).total_records == 4


def test_monitoring_support_builds_status_and_overview_reports():
    summary = WorkbookSnapshotSummary(
        workbook_path="C:/tmp/base.xlsx",
        synced_at="2026-04-05T10:00:00+00:00",
        record_count=4,
        plantio_count=1,
        audit_event_count=2,
    )
    overview = WorkbookRecordOverview(
        workbook_path="C:/tmp/base.xlsx",
        synced_at="2026-04-05T10:00:00+00:00",
        total_records=4,
        compensados_count=1,
        pendentes_count=3,
        records_with_plantios_count=1,
        records_without_microbacia_count=0,
        records_without_coordinates_count=1,
        top_microbacias=(("Gregorio", 4),),
        sample_records=(
            MirroredRecordSample(
                excel_row=2,
                uid="uid-1",
                av_tec="AT-1",
                microbacia="Gregorio",
                compensado="SIM",
                plantio_count=1,
            ),
        ),
    )

    status_report = build_status_report_from_snapshot(
        summary,
        workbook_path="C:/tmp/base.xlsx",
        expected_records=4,
        expected_audit_events=2,
    )
    overview_report = build_record_overview_report_from_snapshot(
        overview,
        workbook_path="C:/tmp/base.xlsx",
    )

    assert status_report.status == "sincronizado"
    assert overview_report.status == "sincronizado"
    assert overview_report.sample_records[0].uid == "uid-1"


def test_monitoring_support_builds_unavailable_reports():
    assert build_unavailable_status_report(
        "C:/tmp/base.xlsx",
        expected_records=0,
        expected_audit_events=0,
        issues=("offline",),
    ).status == "indisponivel"
    assert build_unavailable_record_overview_report("C:/tmp/base.xlsx").status == "indisponivel"
