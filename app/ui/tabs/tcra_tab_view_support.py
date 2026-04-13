from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from app.models.tcra import Tcra
from app.services.tcra_records_service import (
    TcraAgendaItem,
    TcraOperationalRules,
    TcraQualityQueueItem,
    resolve_operational_status,
    resolve_tcra_risk_profile,
)
from app.ui.tabs.tcra_tab_support import (
    build_row_hint,
    format_date,
    format_latest_event_label,
    format_orgao_context,
    latest_event,
    resolve_record_next_action,
    resolve_record_priority_label,
    stringify,
)


MAIN_TABLE_HEADERS = (
    "Prioridade",
    "Processo",
    "TCRA",
    "Status",
    "Ult. evento",
    "Prox. acao",
    "Prazo",
    "Prox. relatorio",
    "Responsavel",
    "Orgao/MPSP",
    "Local",
)
MAIN_TABLE_STATUS_COLUMN = 3
MAIN_TABLE_BOLD_COLUMNS = frozenset({0, MAIN_TABLE_STATUS_COLUMN, 4, 5, 6, 7})


@dataclass(frozen=True)
class TcraGridRowData:
    record: Tcra
    uid: str
    values: tuple[str, ...]
    operational_status: str
    tooltip: str


@dataclass(frozen=True)
class TcraOverviewRowData:
    uid: str
    values: tuple[str, ...]
    tooltip: str
    rank: int


@dataclass(frozen=True)
class TcraSelectionState:
    selected_count: int
    bulk_selected_uids: tuple[str, ...]
    selection_summary: str
    bulk_action_text: str
    primary_record: Tcra | None

    @property
    def has_selection(self) -> bool:
        return self.selected_count > 0

    @property
    def show_actions(self) -> bool:
        return self.has_selection

    @property
    def open_selected_enabled(self) -> bool:
        return self.primary_record is not None


def build_main_table_rows(
    records: Sequence[Tcra],
    *,
    today: date,
    rules: TcraOperationalRules | None = None,
) -> tuple[TcraGridRowData, ...]:
    rows: list[TcraGridRowData] = []
    for record in records:
        operational_status = resolve_operational_status(record, today=today)
        risk_profile = resolve_tcra_risk_profile(record, today=today, rules=rules)
        priority_label = f"{resolve_record_priority_label(record, today=today)} ({risk_profile.score})"
        next_action = resolve_record_next_action(record, today=today)
        latest_record_event = latest_event(list(record.eventos))
        latest_event_tooltip = "Ultimo evento: sem registro"
        if latest_record_event is not None:
            latest_event_tooltip = "Ultimo evento: " + " | ".join(
                part
                for part in (
                    format_date(latest_record_event.data_evento),
                    stringify(latest_record_event.tipo_evento) or "Evento",
                    stringify(latest_record_event.status_resultante),
                    (
                        f"prazo {format_date(latest_record_event.prazo_resultante)}"
                        if latest_record_event.prazo_resultante is not None
                        else ""
                    ),
                )
                if part
            )
        tooltip = "\n".join(
            part
            for part in (
                build_row_hint(record, today=today),
                f"Prioridade: {priority_label}",
                f"Risco: {risk_profile.band} | score {risk_profile.score}",
                "Fatores: " + ", ".join(risk_profile.drivers) if risk_profile.drivers else "",
                latest_event_tooltip,
                f"Proxima acao: {next_action}",
                f"Responsavel: {stringify(record.responsavel_execucao) or '--'}",
                f"Orgao: {format_orgao_context(record)}",
            )
            if part
        )
        rows.append(
            TcraGridRowData(
                record=record,
                uid=stringify(record.uid),
                operational_status=operational_status,
                values=(
                    priority_label,
                    stringify(record.numero_processo) or "--",
                    stringify(record.numero_tcra) or "--",
                    operational_status or "--",
                    format_latest_event_label(record),
                    next_action,
                    format_date(record.prazo_final),
                    format_date(record.data_proximo_relatorio),
                    stringify(record.responsavel_execucao) or "--",
                    format_orgao_context(record),
                    stringify(record.local or record.endereco or record.bairro) or "--",
                ),
                tooltip=tooltip,
            )
        )
    return tuple(rows)


def build_agenda_overview_rows(items: Sequence[TcraAgendaItem]) -> tuple[TcraOverviewRowData, ...]:
    rows: list[TcraOverviewRowData] = []
    for item in items:
        workflow_parts = [
            stringify(item.workflow_state),
            f"ate {format_date(item.workflow_until)}" if item.workflow_until is not None else "",
        ]
        workflow_text = " ".join(part for part in workflow_parts if part) or "--"
        tooltip = "\n".join(
            part
            for part in (
                f"Risco {int(item.risk_score or 0)}",
                f"Status: {stringify(item.status_operacional) or '--'}",
                f"Referencia: {format_date(item.data_referencia)}",
                f"Workflow: {workflow_text}",
                stringify(item.detalhe) or stringify(item.prioridade_label) or "--",
            )
            if part
        )
        rows.append(
            TcraOverviewRowData(
                uid=stringify(item.uid),
                values=(
                    f"{stringify(item.prioridade_label) or '--'} ({int(item.risk_score or 0)})",
                    stringify(item.termo_label) or "--",
                    stringify(item.status_operacional) or "--",
                    format_date(item.data_referencia),
                    stringify(item.local) or "--",
                    stringify(item.detalhe) or "--",
                ),
                tooltip=tooltip,
                rank=int(item.priority_rank),
            )
        )
    return tuple(rows)


def build_quality_overview_rows(items: Sequence[TcraQualityQueueItem]) -> tuple[TcraOverviewRowData, ...]:
    rows: list[TcraOverviewRowData] = []
    for item in items:
        tooltip = "\n".join(item.issues) if item.issues else stringify(item.detalhe)
        rows.append(
            TcraOverviewRowData(
                uid=stringify(item.uid),
                values=(
                    stringify(item.severity_label) or "--",
                    stringify(item.termo_label) or "--",
                    stringify(item.local) or "--",
                    stringify(item.detalhe) or "--",
                    " | ".join(item.issues[:3]) if item.issues else "--",
                ),
                tooltip=tooltip or stringify(item.severity_label) or "--",
                rank=int(item.severity_rank),
            )
        )
    return tuple(rows)


def build_selection_state(
    *,
    filtered_records: Sequence[Tcra],
    selected_rows: Sequence[int],
    selected_records: Sequence[Tcra],
    current_row: int,
) -> TcraSelectionState:
    if not selected_rows:
        return TcraSelectionState(
            selected_count=0,
            bulk_selected_uids=(),
            selection_summary="Nenhum termo selecionado",
            bulk_action_text="Acoes em lote",
            primary_record=None,
        )

    primary_record: Tcra | None = None
    if 0 <= current_row < len(filtered_records):
        primary_record = filtered_records[current_row]
    elif selected_records:
        primary_record = selected_records[0]
    else:
        first_row = next((row for row in selected_rows if 0 <= row < len(filtered_records)), -1)
        if first_row >= 0:
            primary_record = filtered_records[first_row]

    selected_count = len(selected_records)
    bulk_selected_uids = tuple(stringify(record.uid) for record in selected_records if stringify(record.uid))
    if selected_count > 1:
        selection_summary = f"{selected_count} termos selecionados para acao em lote"
        bulk_action_text = f"Acoes em lote ({selected_count})"
    else:
        selection_summary = "1 termo selecionado"
        bulk_action_text = "Acoes em lote"

    return TcraSelectionState(
        selected_count=selected_count,
        bulk_selected_uids=bulk_selected_uids,
        selection_summary=selection_summary,
        bulk_action_text=bulk_action_text,
        primary_record=primary_record,
    )
