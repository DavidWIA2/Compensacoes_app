from app.application.use_cases.persistence_monitoring import PersistenceMonitoringUseCases
from app.services.sqlite_mirror_service import (
    MirroredRecordSample,
    WorkbookRecordOverview,
    WorkbookSnapshotSummary,
)


class StubSnapshotReader:
    def __init__(
        self,
        summary: WorkbookSnapshotSummary,
        overview: WorkbookRecordOverview | None = None,
    ):
        self.summary = summary
        self.overview = overview or WorkbookRecordOverview(
            workbook_path=summary.workbook_path,
            synced_at=summary.synced_at,
            total_records=summary.record_count,
            compensados_count=0,
            pendentes_count=summary.record_count,
            records_with_plantios_count=summary.plantio_count,
            records_without_microbacia_count=0,
            records_without_coordinates_count=0,
        )

    def get_workbook_snapshot_summary(self, workbook_path: str) -> WorkbookSnapshotSummary:
        return self.summary

    def build_workbook_record_overview(
        self,
        workbook_path: str,
        *,
        top_microbacias_limit: int = 5,
        sample_limit: int = 5,
    ) -> WorkbookRecordOverview:
        return self.overview


def test_persistence_monitoring_reports_synchronized_status():
    use_cases = PersistenceMonitoringUseCases(
        StubSnapshotReader(
            WorkbookSnapshotSummary(
                workbook_path="C:/tmp/base.xlsx",
                synced_at="2026-03-30T12:00:00+00:00",
                record_count=12,
                plantio_count=3,
                audit_event_count=5,
            )
        )
    )

    report = use_cases.build_status_report(
        "C:/tmp/base.xlsx",
        expected_records=12,
        expected_audit_events=5,
    )

    assert report.status == "sincronizado"
    assert report.is_healthy is True
    assert report.issues == ()


def test_persistence_monitoring_reports_attention_when_counts_diverge():
    use_cases = PersistenceMonitoringUseCases(
        StubSnapshotReader(
            WorkbookSnapshotSummary(
                workbook_path="C:/tmp/base.xlsx",
                synced_at="2026-03-30T12:00:00+00:00",
                record_count=10,
                plantio_count=2,
                audit_event_count=1,
            )
        )
    )

    report = use_cases.build_status_report(
        "C:/tmp/base.xlsx",
        expected_records=12,
        expected_audit_events=3,
    )

    assert report.status == "atencao"
    assert report.is_healthy is False
    assert any("10" in issue for issue in report.issues)
    assert any("1" in issue for issue in report.issues)


def test_persistence_monitoring_reports_unavailable_without_reader():
    use_cases = PersistenceMonitoringUseCases(None)

    report = use_cases.build_status_report(
        "C:/tmp/base.xlsx",
        expected_records=0,
        expected_audit_events=0,
    )

    assert report.status == "indisponivel"
    assert report.is_healthy is False
    assert report.issues


def test_persistence_monitoring_builds_record_overview_report():
    use_cases = PersistenceMonitoringUseCases(
        StubSnapshotReader(
            WorkbookSnapshotSummary(
                workbook_path="C:/tmp/base.xlsx",
                synced_at="2026-03-30T12:00:00+00:00",
                record_count=12,
                plantio_count=3,
                audit_event_count=5,
            ),
            overview=WorkbookRecordOverview(
                workbook_path="C:/tmp/base.xlsx",
                synced_at="2026-03-30T12:00:00+00:00",
                total_records=12,
                compensados_count=7,
                pendentes_count=5,
                records_with_plantios_count=3,
                records_without_microbacia_count=1,
                records_without_coordinates_count=2,
                top_microbacias=(("Gregorio", 8), ("Medeiros", 4)),
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
            ),
        )
    )

    report = use_cases.build_record_overview_report("C:/tmp/base.xlsx")

    assert report.status == "sincronizado"
    assert report.is_available is True
    assert report.total_records == 12
    assert report.compensados_count == 7
    assert report.records_without_coordinates_count == 2
    assert report.top_microbacias[0] == ("Gregorio", 8)
    assert report.sample_records[0].uid == "uid-1"
