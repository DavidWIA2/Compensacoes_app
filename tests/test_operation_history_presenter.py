from datetime import date

from app.application.use_cases.operation_history_presenter import (
    OperationHistoryFilterState,
    OperationHistoryPresenter,
)
from app.services.audit_service import AuditEvent


def make_event(**overrides) -> AuditEvent:
    base = {
        "event_id": "evt-1",
        "timestamp": "2026-03-30T10:00:00+00:00",
        "workbook_path": "C:/tmp/base.xlsx",
        "action": "add",
        "summary": "Registro cadastrado: AT-1",
        "backup_path": "",
        "metadata": {"uid": "uid-1"},
        "before": None,
        "after": None,
    }
    base.update(overrides)
    return AuditEvent(**base)


def test_filter_events_applies_action_backup_period_and_search(tmp_path):
    presenter = OperationHistoryPresenter()
    backup = tmp_path / "edit.xlsx"
    backup.write_text("ok", encoding="utf-8")
    events = [
        make_event(event_id="evt-1", action="add", summary="Registro cadastrado: AT-1"),
        make_event(
            event_id="evt-2",
            action="edit",
            summary="Registro alterado: AT-99",
            backup_path=str(backup),
            metadata={"uid": "uid-99"},
        ),
        make_event(
            event_id="evt-3",
            timestamp="2026-03-01T10:00:00+00:00",
            action="import",
            summary="Importacao importar.xlsx",
            metadata={"source_path": "importar.xlsx"},
        ),
    ]

    state = OperationHistoryFilterState(
        action="EDIT",
        backup="Com backup",
        period="Personalizado",
        date_from=date(2026, 3, 30),
        date_to=date(2026, 3, 30),
        search="uid-99",
    )

    visible = presenter.filter_events(events, state=state)

    assert [event.event_id for event in visible] == ["evt-2"]


def test_build_summary_and_export_payload(tmp_path):
    presenter = OperationHistoryPresenter()
    backup = tmp_path / "add.xlsx"
    backup.write_text("ok", encoding="utf-8")
    events = [
        make_event(event_id="evt-1", action="add", backup_path=str(backup)),
        make_event(event_id="evt-2", action="edit", summary="Registro alterado: AT-99"),
    ]
    state = OperationHistoryFilterState(
        action="Todas",
        backup="Todos",
        period="Personalizado",
        date_from=date(2026, 3, 30),
        date_to=date(2026, 3, 30),
        search="",
    )

    summary = presenter.build_summary_text(visible_events=events, state=state)
    payload = presenter.build_export_payload(
        exported_at="2026-03-31T10:00:00",
        filter_state=state,
        total_events=2,
        visible_events=events,
        summary_text=summary,
    )

    assert "Periodo: 30/03/2026 a 30/03/2026" in summary
    assert payload["filters"] == {
        "action": "Todas",
        "backup": "Todos",
        "period": "Personalizado",
        "date_from": "2026-03-30",
        "date_to": "2026-03-30",
        "search": "",
    }
    assert payload["visible_events"] == 2
