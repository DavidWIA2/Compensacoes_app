from app.services.audit_service_support import (
    audit_event_matches_path,
    build_audit_event,
    build_audit_event_from_payload,
    sort_audit_events,
)


def test_build_audit_event_normalizes_session_alias(tmp_path):
    session_path = str(tmp_path / "base-a.xlsx")

    event = build_audit_event(
        session_path=session_path,
        action="edit",
        summary="Registro alterado",
        metadata={"uid": "uid-1"},
    )

    assert event.session_path.endswith("base-a.xlsx")
    assert event.metadata["uid"] == "uid-1"
    assert audit_event_matches_path(event, session_path) is True


def test_build_audit_event_from_payload_prefers_session_path_and_sorts():
    older = build_audit_event_from_payload(
        {
            "event_id": "evt-1",
            "timestamp": "2026-04-01T10:00:00+00:00",
            "session_path": "C:/tmp/base.xlsx",
            "action": "edit",
            "summary": "Primeiro",
        }
    )
    newer = build_audit_event_from_payload(
        {
            "event_id": "evt-2",
            "timestamp": "2026-04-02T10:00:00+00:00",
            "workbook_path": "C:/tmp/base.xlsx",
            "action": "import",
            "summary": "Segundo",
        }
    )

    events = sort_audit_events([older, newer], limit=10)

    assert older.session_path == "C:/tmp/base.xlsx"
    assert events[0].event_id == "evt-2"
    assert events[1].event_id == "evt-1"
