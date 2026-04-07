from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Sequence

from PySide6.QtCore import QDate, Qt

from app.application.use_cases.operation_history_presenter import OperationHistoryFilterState, OperationHistoryPresenter
from app.services.audit_service import AuditEvent


BACKUP_FILTER_OPTIONS = ("Todos", "Com backup", "Sem backup")
PERIOD_FILTER_OPTIONS = ("Todos", "Hoje", "Últimos 7 dias", "Últimos 30 dias", "Personalizado")


@dataclass(frozen=True)
class OperationHistorySelectionState:
    event: AuditEvent | None
    can_open_backup: bool
    can_restore: bool
    details_text: str


def resolve_operation_history_settings_store(parent: Any) -> Any | None:
    settings = getattr(parent, "settings", None)
    if settings is None:
        return None
    if hasattr(settings, "operation_history_filter_state") and hasattr(settings, "set_operation_history_filter_state"):
        return settings
    if hasattr(settings, "value") and hasattr(settings, "setValue"):
        return settings
    return None


def load_operation_history_filter_state(parent: Any) -> dict[str, str]:
    settings = resolve_operation_history_settings_store(parent)
    if settings is None:
        return {}
    if hasattr(settings, "operation_history_filter_state"):
        raw_state = settings.operation_history_filter_state()
    else:
        raw_state = settings.value("operation_history_filter_state", {})
    return dict(raw_state) if isinstance(raw_state, dict) else {}


def persist_operation_history_filter_state(parent: Any, state: dict[str, str]) -> None:
    settings = resolve_operation_history_settings_store(parent)
    if settings is None:
        return
    payload = dict(state or {})
    if hasattr(settings, "set_operation_history_filter_state"):
        settings.set_operation_history_filter_state(payload)
    else:
        settings.setValue("operation_history_filter_state", payload)


def resolve_operation_history_default_export_path(parent: Any, *, now: datetime | None = None) -> str:
    initial_dir = ""
    if parent is not None and hasattr(parent, "settings_controller"):
        initial_dir = str(parent.settings_controller.preferred_export_dir() or "")
    filename = f"historico_operacoes_{(now or datetime.now()).strftime('%Y%m%d_%H%M%S')}.json"
    if initial_dir:
        return os.path.join(initial_dir, filename)
    return filename


def write_operation_history_export(path: str, payload: dict[str, object]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)


def qdate_to_date(value: QDate) -> date | None:
    if not value.isValid():
        return None
    return date(value.year(), value.month(), value.day())


def date_to_qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


def resolve_operation_history_target_index(
    visible_events: Sequence[AuditEvent],
    *,
    current_event_id: str,
) -> int:
    if not current_event_id:
        return 0
    for index, event in enumerate(visible_events):
        if getattr(event, "event_id", "") == current_event_id:
            return index
    return 0


def resolve_operation_history_current_event(
    visible_events: Sequence[AuditEvent],
    *,
    current_row: int,
) -> AuditEvent | None:
    if current_row < 0 or current_row >= len(visible_events):
        return None
    return visible_events[current_row]


def build_operation_history_selection_state(
    presenter: OperationHistoryPresenter,
    event: AuditEvent | None,
) -> OperationHistorySelectionState:
    if event is None:
        return OperationHistorySelectionState(
            event=None,
            can_open_backup=False,
            can_restore=False,
            details_text="",
        )
    backup_available = presenter.backup_status_label(event) == "Disponivel"
    return OperationHistorySelectionState(
        event=event,
        can_open_backup=backup_available,
        can_restore=backup_available,
        details_text=presenter.build_details_text(event),
    )


def build_operation_history_filter_state_payload(state: OperationHistoryFilterState) -> dict[str, str]:
    return state.to_dict()
