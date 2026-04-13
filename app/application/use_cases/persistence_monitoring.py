from __future__ import annotations

from app.application.use_cases.persistence_monitoring_support import (
    PersistenceRecordOverviewReport,
    PersistenceRecordSampleReport,  # noqa: F401
    PersistenceStatusReport,
    SessionRecordOverviewReader,  # noqa: F401
    SessionSnapshotReader,  # noqa: F401
    WorkbookRecordOverviewReader,  # noqa: F401
    WorkbookSnapshotReader,
    build_record_overview_report_from_snapshot,
    build_status_report_from_snapshot,
    build_unavailable_record_overview_report,
    build_unavailable_status_report,
    get_record_overview,
    get_snapshot_summary,
)


class PersistenceMonitoringUseCases:
    def __init__(self, snapshot_reader: WorkbookSnapshotReader | None):
        self.snapshot_reader = snapshot_reader

    def _get_snapshot_summary(self, workbook_path: str):
        return get_snapshot_summary(self.snapshot_reader, workbook_path)

    def _build_record_overview(
        self,
        workbook_path: str,
        *,
        top_microbacias_limit: int,
        sample_limit: int,
    ):
        return get_record_overview(
            self.snapshot_reader,
            workbook_path,
            top_microbacias_limit=top_microbacias_limit,
            sample_limit=sample_limit,
        )

    def build_session_status_report(
        self,
        session_path: str,
        *,
        expected_records: int,
        expected_audit_events: int,
    ) -> PersistenceStatusReport:
        return self.build_status_report(
            session_path,
            expected_records=expected_records,
            expected_audit_events=expected_audit_events,
        )

    def build_status_report(
        self,
        workbook_path: str,
        *,
        expected_records: int,
        expected_audit_events: int,
    ) -> PersistenceStatusReport:
        normalized_path = str(workbook_path or "").strip()
        if not normalized_path:
            return build_unavailable_status_report(
                "",
                expected_records=int(expected_records),
                expected_audit_events=int(expected_audit_events),
                issues=("Nenhuma planilha ativa para validar o espelho local.",),
            )

        if self.snapshot_reader is None:
            return build_unavailable_status_report(
                normalized_path,
                expected_records=int(expected_records),
                expected_audit_events=int(expected_audit_events),
                issues=("O espelho local em SQLite nao esta disponivel nesta sessao.",),
            )

        snapshot = self._get_snapshot_summary(normalized_path)
        return build_status_report_from_snapshot(
            snapshot,
            workbook_path=normalized_path,
            expected_records=int(expected_records),
            expected_audit_events=int(expected_audit_events),
        )

    def build_session_record_overview_report(
        self,
        session_path: str,
        *,
        top_microbacias_limit: int = 3,
        sample_limit: int = 3,
    ) -> PersistenceRecordOverviewReport:
        return self.build_record_overview_report(
            session_path,
            top_microbacias_limit=top_microbacias_limit,
            sample_limit=sample_limit,
        )

    def build_record_overview_report(
        self,
        workbook_path: str,
        *,
        top_microbacias_limit: int = 3,
        sample_limit: int = 3,
    ) -> PersistenceRecordOverviewReport:
        normalized_path = str(workbook_path or "").strip()
        if not normalized_path:
            return build_unavailable_record_overview_report("")

        if self.snapshot_reader is None or not (
            hasattr(self.snapshot_reader, "build_workbook_record_overview")
            or hasattr(self.snapshot_reader, "build_session_record_overview")
        ):
            return build_unavailable_record_overview_report(normalized_path)

        overview = self._build_record_overview(
            normalized_path,
            top_microbacias_limit=int(top_microbacias_limit),
            sample_limit=int(sample_limit),
        )
        return build_record_overview_report_from_snapshot(
            overview,
            workbook_path=normalized_path,
        )
