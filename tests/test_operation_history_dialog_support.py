from datetime import date, datetime
from types import SimpleNamespace

from PySide6.QtCore import QDate

from app.application.use_cases.operation_history_presenter import OperationHistoryFilterState, OperationHistoryPresenter
from app.services.audit_service import AuditEvent
from app.ui.components.operation_history_dialog_support import (
    build_operation_history_filter_state_payload,
    build_operation_history_selection_state,
    date_to_qdate,
    load_operation_history_filter_state,
    persist_operation_history_filter_state,
    qdate_to_date,
    resolve_operation_history_current_event,
    resolve_operation_history_default_export_path,
    resolve_operation_history_target_index,
)


class MemorySettings:
    def __init__(self):
        self._data = {}

    def operation_history_filter_state(self):
        return dict(self._data.get("operation_history_filter_state", {}))

    def set_operation_history_filter_state(self, state):
        self._data["operation_history_filter_state"] = dict(state or {})


def test_operation_history_filter_state_roundtrip_and_export_path(tmp_path):
    parent = SimpleNamespace(
        settings=MemorySettings(),
        settings_controller=SimpleNamespace(preferred_export_dir=lambda: str(tmp_path)),
    )
    state = OperationHistoryFilterState(
        action="EDIT",
        backup="Com backup",
        period="Personalizado",
        date_from=date(2026, 3, 30),
        date_to=date(2026, 3, 31),
        search="uid-99",
    )

    persist_operation_history_filter_state(parent, build_operation_history_filter_state_payload(state))
    restored = load_operation_history_filter_state(parent)
    path = resolve_operation_history_default_export_path(parent, now=datetime(2026, 4, 5, 10, 20, 30))

    assert restored == {
        "action": "EDIT",
        "backup": "Com backup",
        "period": "Personalizado",
        "date_from": "2026-03-30",
        "date_to": "2026-03-31",
        "search": "uid-99",
    }
    assert path.endswith("historico_operacoes_20260405_102030.json")


def test_operation_history_support_resolves_selection_and_dates(tmp_path):
    backup = tmp_path / "snapshot.xlsx"
    backup.write_text("ok", encoding="utf-8")
    presenter = OperationHistoryPresenter()
    events = [
        AuditEvent(
            event_id="evt-1",
            timestamp="2026-03-31T10:00:00+00:00",
            workbook_path="C:/tmp/base.xlsx",
            action="edit",
            summary="Registro alterado",
            backup_path=str(backup),
            metadata={},
        ),
        AuditEvent(
            event_id="evt-2",
            timestamp="2026-03-31T11:00:00+00:00",
            workbook_path="C:/tmp/base.xlsx",
            action="import",
            summary="Importacao",
            backup_path="",
            metadata={},
        ),
    ]

    selection = build_operation_history_selection_state(presenter, events[0])

    assert resolve_operation_history_current_event(events, current_row=1) is events[1]
    assert resolve_operation_history_target_index(events, current_event_id="evt-2") == 1
    assert selection.can_open_backup is True
    assert selection.can_restore is True
    assert "Registro alterado" in selection.details_text
    assert date_to_qdate(date(2026, 3, 30)) == QDate(2026, 3, 30)
    assert qdate_to_date(QDate(2026, 3, 31)) == date(2026, 3, 31)
