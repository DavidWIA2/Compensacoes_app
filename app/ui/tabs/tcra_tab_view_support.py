from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from app.models.tcra import Tcra
from app.services.tcra_records_service import TcraAgendaItem, TcraQualityQueueItem, resolve_operational_status, tcra_is_mpsp_related
from app.ui.tabs.tcra_tab_support import build_row_hint, format_date, stringify


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
    values: tuple[str, str, str, str]
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


def build_main_table_rows(records: Sequence[Tcra], *, today: date) -> tuple[TcraGridRowData, ...]:
    rows: list[TcraGridRowData] = []
    for record in records:
        operational_status = resolve_operational_status(record, today=today)
        rows.append(
            TcraGridRowData(
                record=record,
                uid=stringify(record.uid),
                operational_status=operational_status,
                values=(
                    stringify(record.numero_processo) or "--",
                    stringify(record.numero_tcra) or "--",
                    stringify(record.local) or "--",
                    operational_status or "--",
                    format_date(record.prazo_final),
                    format_date(record.data_proximo_relatorio),
                    stringify(record.orgao_acompanhamento) or "--",
                    "Sim" if tcra_is_mpsp_related(record) else "Não",
                ),
                tooltip=build_row_hint(record, today=today),
            )
        )
    return tuple(rows)


def build_agenda_overview_rows(items: Sequence[TcraAgendaItem]) -> tuple[TcraOverviewRowData, ...]:
    return tuple(
        TcraOverviewRowData(
            uid=stringify(item.uid),
            values=(
                stringify(item.prioridade_label) or "--",
                stringify(item.termo_label) or "--",
                stringify(item.local) or "--",
                stringify(item.detalhe) or "--",
            ),
            tooltip=stringify(item.detalhe) or stringify(item.prioridade_label) or "--",
            rank=int(item.priority_rank),
        )
        for item in items
    )


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
            bulk_action_text="Ações em lote",
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
        selection_summary = f"{selected_count} termos selecionados para ação em lote"
        bulk_action_text = f"Ações em lote ({selected_count})"
    else:
        selection_summary = "1 termo selecionado"
        bulk_action_text = "Ações em lote"

    return TcraSelectionState(
        selected_count=selected_count,
        bulk_selected_uids=bulk_selected_uids,
        selection_summary=selection_summary,
        bulk_action_text=bulk_action_text,
        primary_record=primary_record,
    )
