from datetime import datetime, timezone

from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.application.use_cases.operations_overview_use_cases import OperationsOverviewUseCases
from app.application.use_cases.persistence_monitoring import (
    PersistenceMonitoringUseCases,
    PersistenceRecordOverviewReport,
    PersistenceStatusReport,
)
from app.services.audit_service import AuditEvent


def make_event(*, event_id: str, timestamp: str, action: str, summary: str) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        timestamp=timestamp,
        workbook_path="dummy.xlsx",
        action=action,
        summary=summary,
        metadata={},
    )


def test_operations_overview_use_cases_returns_none_without_session_path():
    use_cases = OperationsOverviewUseCases(PersistenceMonitoringUseCases(None))
    snapshot = use_cases.resolve_snapshot(
        session_path="",
        audit_service=object(),
        expected_records=0,
    )
    assert snapshot is None


def test_operations_overview_use_cases_prefers_shell_resolvers():
    now = datetime.now(timezone.utc).isoformat()
    calls = {"status": 0, "overview": 0}
    events = (
        make_event(
            event_id="evt-1",
            timestamp=now,
            action="edit",
            summary="Registro alterado: AT-1",
        ),
    )

    class AuditServiceStub:
        def list_events_for_session(self, _session_path: str, *, limit: int = 100):
            assert limit == 50
            return list(events)

    class ShellControllerStub:
        def resolved_persistence_status_report(self, **kwargs):
            calls["status"] += 1
            assert kwargs["refresh"] is True
            assert kwargs["expected_audit_events"] == 1
            return PersistenceStatusReport(
                status="sincronizado",
                workbook_path="dummy.xlsx",
                synced_at=now,
                mirrored_records=3,
                mirrored_plantios=1,
                mirrored_audit_events=1,
                expected_records=3,
                expected_audit_events=1,
            )

        def resolved_dashboard_record_overview(self, **kwargs):
            calls["overview"] += 1
            assert kwargs["refresh"] is True
            assert kwargs["top_microbacias_limit"] == 3
            assert kwargs["sample_limit"] == 3
            return PersistenceRecordOverviewReport(
                status="sincronizado",
                workbook_path="dummy.xlsx",
                synced_at=now,
                total_records=3,
                compensados_count=1,
                pendentes_count=2,
                records_with_plantios_count=1,
                records_without_microbacia_count=0,
                records_without_coordinates_count=1,
            )

    session_status = LocalRecordReadStatus(
        status="sqlite",
        source="sqlite",
        strategy="sqlite_snapshot",
        workbook_path="dummy.xlsx",
        synced_at=now,
        mirrored_records=3,
        session_records=3,
        filtered_records=3,
    )
    use_cases = OperationsOverviewUseCases(PersistenceMonitoringUseCases(None))
    snapshot = use_cases.resolve_snapshot(
        session_path="dummy.xlsx",
        audit_service=AuditServiceStub(),
        expected_records=3,
        shell_controller=ShellControllerStub(),
        record_integrity_report={"issue_count": 1},
        session_source_status=session_status,
        record_read_status=session_status,
        limit=50,
    )

    assert snapshot is not None
    assert snapshot.session_path == "dummy.xlsx"
    assert len(snapshot.events) == 1
    assert snapshot.overview.total_events == 1
    assert snapshot.persistence_report is not None
    assert snapshot.record_overview_report is not None
    assert snapshot.record_integrity_report == {"issue_count": 1}
    assert snapshot.record_read_status is session_status
    assert calls == {"status": 1, "overview": 1}
