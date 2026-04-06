from __future__ import annotations

from dataclasses import dataclass

from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.application.use_cases.persistence_monitoring import (
    PersistenceMonitoringUseCases,
    PersistenceRecordOverviewReport,
    PersistenceStatusReport,
)
from app.services.audit_service import AuditEvent, AuditOverview, build_audit_overview


@dataclass(frozen=True)
class OperationsOverviewSnapshot:
    session_path: str
    events: tuple[AuditEvent, ...]
    overview: AuditOverview
    persistence_report: PersistenceStatusReport | None
    record_overview_report: PersistenceRecordOverviewReport | None
    session_source_status: object | None = None
    authoritative_write_status: object | None = None
    mutation_sync_status: object | None = None
    record_read_status: LocalRecordReadStatus | None = None


class OperationsOverviewUseCases:
    def __init__(self, persistence_use_cases: PersistenceMonitoringUseCases):
        self.persistence_use_cases = persistence_use_cases

    def _list_events(
        self,
        *,
        audit_service: object,
        session_path: str,
        limit: int,
    ) -> tuple[AuditEvent, ...]:
        if hasattr(audit_service, "list_events_for_session"):
            events = audit_service.list_events_for_session(session_path, limit=limit)
        else:
            events = audit_service.list_events_for_workbook(session_path, limit=limit)
        return tuple(events)

    def _resolve_reports(
        self,
        *,
        session_path: str,
        expected_records: int,
        expected_audit_events: int,
        shell_controller: object | None,
        persistence: object | None,
        runtime_window: object | None,
    ) -> tuple[PersistenceStatusReport | None, PersistenceRecordOverviewReport | None]:
        if shell_controller is not None:
            return (
                shell_controller.resolved_persistence_status_report(
                    refresh=True,
                    expected_audit_events=expected_audit_events,
                ),
                shell_controller.resolved_dashboard_record_overview(
                    refresh=True,
                    top_microbacias_limit=3,
                    sample_limit=3,
                ),
            )

        if persistence is not None:
            if runtime_window is not None:
                persistence.bind_runtime_window(runtime_window)
            monitoring_snapshot = persistence.resolve_monitoring_snapshot(
                session_path,
                expected_records=expected_records,
                expected_audit_events=expected_audit_events,
                cached_record_overview=getattr(runtime_window, "_dashboard_record_overview", None),
                refresh_record_overview=True,
                top_microbacias_limit=3,
                sample_limit=3,
            )
            if runtime_window is not None:
                runtime_window._persistence_status_report = monitoring_snapshot.persistence_report
                runtime_window._dashboard_record_overview = monitoring_snapshot.record_overview_report
            return monitoring_snapshot.persistence_report, monitoring_snapshot.record_overview_report

        return (
            self.persistence_use_cases.build_status_report(
                session_path,
                expected_records=expected_records,
                expected_audit_events=expected_audit_events,
            ),
            self.persistence_use_cases.build_record_overview_report(
                session_path,
                top_microbacias_limit=3,
                sample_limit=3,
            ),
        )

    def resolve_snapshot(
        self,
        *,
        session_path: str,
        audit_service: object,
        expected_records: int,
        shell_controller: object | None = None,
        persistence: object | None = None,
        runtime_window: object | None = None,
        session_source_status: object | None = None,
        authoritative_write_status: object | None = None,
        mutation_sync_status: object | None = None,
        record_read_status: LocalRecordReadStatus | None = None,
        limit: int = 100,
    ) -> OperationsOverviewSnapshot | None:
        normalized_path = str(session_path or "").strip()
        if not normalized_path:
            return None

        events = self._list_events(
            audit_service=audit_service,
            session_path=normalized_path,
            limit=limit,
        )
        overview = build_audit_overview(events)
        persistence_report, record_overview_report = self._resolve_reports(
            session_path=normalized_path,
            expected_records=int(expected_records),
            expected_audit_events=len(events),
            shell_controller=shell_controller,
            persistence=persistence,
            runtime_window=runtime_window,
        )
        return OperationsOverviewSnapshot(
            session_path=normalized_path,
            events=events,
            overview=overview,
            persistence_report=persistence_report,
            record_overview_report=record_overview_report,
            session_source_status=session_source_status,
            authoritative_write_status=authoritative_write_status,
            mutation_sync_status=mutation_sync_status,
            record_read_status=record_read_status,
        )
