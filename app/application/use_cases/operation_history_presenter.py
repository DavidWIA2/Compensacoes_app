from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence

from app.services.audit_service import (
    AuditEvent,
    audit_backup_available,
    audit_backup_path,
    parse_audit_timestamp,
)


@dataclass(frozen=True)
class OperationHistoryFilterState:
    action: str
    backup: str
    period: str
    date_from: date | None
    date_to: date | None
    search: str

    def to_dict(self) -> dict[str, str]:
        return {
            "action": self.action,
            "backup": self.backup,
            "period": self.period,
            "date_from": self.date_from.isoformat() if self.date_from is not None else "",
            "date_to": self.date_to.isoformat() if self.date_to is not None else "",
            "search": self.search,
        }


@dataclass(frozen=True)
class OperationHistoryRowView:
    timestamp: str
    action: str
    summary: str
    backup_status: str


class OperationHistoryPresenter:
    @staticmethod
    def build_action_items(events: Sequence[AuditEvent]) -> tuple[str, ...]:
        actions = sorted(
            {
                str(getattr(event, "action", "")).strip().upper()
                for event in events
                if str(getattr(event, "action", "")).strip()
            }
        )
        return ("Todas", *actions)

    @staticmethod
    def resolve_default_date_range(events: Sequence[AuditEvent]) -> tuple[date, date]:
        event_dates = [
            candidate_date
            for candidate_date in (OperationHistoryPresenter._event_date(event) for event in events)
            if candidate_date is not None
        ]
        if not event_dates:
            current_date = datetime.now().astimezone().date()
            return current_date, current_date
        ordered_dates = sorted(event_dates)
        return ordered_dates[0], ordered_dates[-1]

    def filter_events(
        self,
        events: Sequence[AuditEvent],
        *,
        state: OperationHistoryFilterState,
    ) -> list[AuditEvent]:
        normalized_search = str(state.search or "").strip().lower()
        visible_events: list[AuditEvent] = []

        for event in events:
            event_action = str(getattr(event, "action", "")).strip().upper()
            if state.action != "Todas" and event_action != state.action:
                continue

            has_backup = bool(audit_backup_path(event))
            if state.backup == "Com backup" and not has_backup:
                continue
            if state.backup == "Sem backup" and has_backup:
                continue

            if not self._matches_period_filter(event, state):
                continue

            if normalized_search:
                payload = {
                    "timestamp": getattr(event, "timestamp", ""),
                    "action": getattr(event, "action", ""),
                    "summary": getattr(event, "summary", ""),
                    "backup_path": getattr(event, "backup_path", ""),
                    "metadata": getattr(event, "metadata", {}),
                    "before": getattr(event, "before", None),
                    "after": getattr(event, "after", None),
                }
                if normalized_search not in json.dumps(payload, ensure_ascii=True, sort_keys=True).lower():
                    continue

            visible_events.append(event)

        return visible_events

    @staticmethod
    def build_row_view(event: AuditEvent) -> OperationHistoryRowView:
        return OperationHistoryRowView(
            timestamp=OperationHistoryPresenter._formatted_timestamp(str(getattr(event, "timestamp", ""))),
            action=str(getattr(event, "action", "")).upper(),
            summary=str(getattr(event, "summary", "")),
            backup_status=OperationHistoryPresenter.backup_status_label(event),
        )

    @staticmethod
    def build_visible_label(*, visible_events: Sequence[AuditEvent], total_events: int) -> str:
        total_available_backups = sum(1 for event in visible_events if audit_backup_available(event))
        return (
            f"Mostrando {len(visible_events)} de {total_events} operacoes | "
            f"{total_available_backups} backups disponiveis"
        )

    def build_summary_text(
        self,
        *,
        visible_events: Sequence[AuditEvent],
        state: OperationHistoryFilterState,
    ) -> str:
        if not visible_events:
            return "Nenhuma operação corresponde aos filtros atuais."

        actions = Counter(
            str(getattr(event, "action", "")).strip().upper() or "SEM ACAO"
            for event in visible_events
        )
        action_parts = [f"{action}: {count}" for action, count in sorted(actions.items())]
        period_text = self.period_label(state)

        return "\n".join(
            [
                (
                    f"Resumo visivel: {len(visible_events)} operacoes | "
                    f"{sum(1 for event in visible_events if audit_backup_available(event))} backups disponiveis | "
                    f"Periodo: {period_text}"
                ),
                "Acoes visiveis: " + " | ".join(action_parts),
            ]
        )

    @staticmethod
    def backup_status_label(event: AuditEvent) -> str:
        backup_path = audit_backup_path(event)
        if not backup_path:
            return "Sem backup"
        if audit_backup_available(event):
            return "Disponivel"
        return "Indisponivel"

    def build_details_text(self, event: AuditEvent) -> str:
        return json.dumps(self.serialize_event(event), ensure_ascii=True, indent=2)

    def serialize_event(self, event: AuditEvent) -> dict[str, object]:
        return {
            "event_id": getattr(event, "event_id", ""),
            "timestamp": getattr(event, "timestamp", ""),
            "action": getattr(event, "action", ""),
            "summary": getattr(event, "summary", ""),
            "backup_path": getattr(event, "backup_path", ""),
            "backup_status": self.backup_status_label(event),
            "metadata": getattr(event, "metadata", {}),
            "before": getattr(event, "before", None),
            "after": getattr(event, "after", None),
        }

    def build_export_payload(
        self,
        *,
        exported_at: str,
        filter_state: OperationHistoryFilterState,
        total_events: int,
        visible_events: Sequence[AuditEvent],
        summary_text: str,
    ) -> dict[str, object]:
        return {
            "exported_at": exported_at,
            "filters": filter_state.to_dict(),
            "total_events": total_events,
            "visible_events": len(visible_events),
            "summary": summary_text,
            "events": [self.serialize_event(event) for event in visible_events],
        }

    @staticmethod
    def period_label(state: OperationHistoryFilterState) -> str:
        if state.period == "Personalizado" and state.date_from is not None and state.date_to is not None:
            return f"{state.date_from.strftime('%d/%m/%Y')} a {state.date_to.strftime('%d/%m/%Y')}"
        return state.period

    @staticmethod
    def _event_date(event: AuditEvent) -> date | None:
        parsed = parse_audit_timestamp(str(getattr(event, "timestamp", "")))
        if parsed is None:
            return None
        return parsed.date()

    @staticmethod
    def _formatted_timestamp(value: str) -> str:
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""
        parsed = parse_audit_timestamp(raw_value)
        if parsed is None:
            return raw_value
        return parsed.strftime("%d/%m/%Y %H:%M:%S")

    def _matches_period_filter(self, event: AuditEvent, state: OperationHistoryFilterState) -> bool:
        if state.period == "Todos":
            return True

        event_date = self._event_date(event)
        if event_date is None:
            return False

        today = datetime.now().astimezone().date()
        if state.period == "Hoje":
            return event_date == today
        if state.period == "Últimos 7 dias":
            return today - timedelta(days=6) <= event_date <= today
        if state.period == "Últimos 30 dias":
            return today - timedelta(days=29) <= event_date <= today
        if state.period == "Personalizado" and state.date_from is not None and state.date_to is not None:
            return state.date_from <= event_date <= state.date_to
        return True
