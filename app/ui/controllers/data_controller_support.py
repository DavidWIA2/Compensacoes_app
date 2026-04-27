from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple, cast

from app.models.compensacao import Compensacao


@dataclass(frozen=True)
class FilterStateSnapshot:
    search_text: str = ""
    status: str = "Todos"
    year: str = "Todos"
    micro_all_selected: bool = True
    selected_micros: tuple[str, ...] = ()
    eletronico_all_selected: bool = True
    selected_eletronicos: tuple[str, ...] = ()
    caixa_all_selected: bool = True
    selected_caixas: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, object]:
        return {
            "search_text": self.search_text,
            "status": self.status,
            "year": self.year,
            "micro_all_selected": self.micro_all_selected,
            "selected_micros": list(self.selected_micros),
            "eletronico_all_selected": self.eletronico_all_selected,
            "selected_eletronicos": list(self.selected_eletronicos),
            "caixa_all_selected": self.caixa_all_selected,
            "selected_caixas": list(self.selected_caixas),
        }

    @classmethod
    def from_mapping(cls, state: Dict[str, object] | None) -> "FilterStateSnapshot":
        state = dict(state or {})
        return cls(
            search_text=str(state.get("search_text", "")),
            status=str(state.get("status", "Todos")),
            year=str(state.get("year", "Todos")),
            micro_all_selected=bool(state.get("micro_all_selected", True)),
            selected_micros=tuple(cast(List[str], state.get("selected_micros", []))),
            eletronico_all_selected=bool(state.get("eletronico_all_selected", True)),
            selected_eletronicos=tuple(cast(List[str], state.get("selected_eletronicos", []))),
            caixa_all_selected=bool(state.get("caixa_all_selected", True)),
            selected_caixas=tuple(cast(List[str], state.get("selected_caixas", []))),
        )


@dataclass(frozen=True)
class PreviousDataState:
    session_snapshot: object
    records: tuple[Compensacao, ...]
    filtered_records: tuple[Compensacao, ...]
    selected: Optional[Compensacao]
    last_marker_coords: Optional[Tuple[float, float]]
    filter_state: FilterStateSnapshot
    runtime_state: object
    recent_files: tuple[str, ...]


def build_filter_state_snapshot(window) -> FilterStateSnapshot:
    return FilterStateSnapshot(
        search_text=window.search.text(),
        status=window.data_tab.filter_status.currentText(),
        year=window.data_tab.filter_year.currentText(),
        micro_all_selected=window.data_tab.filter_micro.is_all_selected(),
        selected_micros=tuple(window.data_tab.filter_micro.checked_items()),
        eletronico_all_selected=window.data_tab.filter_eletronico.is_all_selected(),
        selected_eletronicos=tuple(window.data_tab.filter_eletronico.checked_items()),
        caixa_all_selected=window.data_tab.filter_caixa.is_all_selected(),
        selected_caixas=tuple(window.data_tab.filter_caixa.checked_items()),
    )


def restore_filter_state_snapshot(window, state: FilterStateSnapshot, tipo_formatter: Callable[[object], str]) -> None:
    window.search.blockSignals(True)
    window.data_tab.filter_status.blockSignals(True)
    window.data_tab.filter_year.blockSignals(True)
    window.data_tab.filter_micro.blockSignals(True)
    window.data_tab.filter_eletronico.blockSignals(True)
    window.data_tab.filter_caixa.blockSignals(True)
    try:
        window.search.setText(state.search_text)

        status_index = window.data_tab.filter_status.findText(state.status)
        window.data_tab.filter_status.setCurrentIndex(status_index if status_index >= 0 else 0)

        year_index = window.data_tab.filter_year.findText(state.year)
        window.data_tab.filter_year.setCurrentIndex(year_index if year_index >= 0 else 0)

        window.data_tab.filter_micro.set_checked_items(
            list(state.selected_micros),
            all_selected=state.micro_all_selected,
        )
        window.data_tab.filter_eletronico.set_checked_items(
            [tipo_formatter(value) for value in state.selected_eletronicos],
            all_selected=state.eletronico_all_selected,
        )
        window.data_tab.filter_caixa.set_checked_items(
            list(state.selected_caixas),
            all_selected=state.caixa_all_selected,
        )
    finally:
        window.search.blockSignals(False)
        window.data_tab.filter_status.blockSignals(False)
        window.data_tab.filter_year.blockSignals(False)
        window.data_tab.filter_micro.blockSignals(False)
        window.data_tab.filter_eletronico.blockSignals(False)
        window.data_tab.filter_caixa.blockSignals(False)


def capture_previous_data_state(window, *, runtime_state: object) -> PreviousDataState:
    snapshot = window.session_controller.snapshot()
    return PreviousDataState(
        session_snapshot=snapshot,
        records=tuple(snapshot.records),
        filtered_records=tuple(snapshot.filtered_records),
        selected=snapshot.selected,
        last_marker_coords=snapshot.last_marker_coords,
        filter_state=build_filter_state_snapshot(window),
        runtime_state=runtime_state,
        recent_files=tuple(snapshot.recent_files),
    )


def restore_previous_session_snapshot(
    window,
    previous_state: PreviousDataState,
    *,
    build_search_index: Callable[[List[Compensacao]], Dict[str, str]],
) -> None:
    snapshot = previous_state.session_snapshot
    snapshot.records = list(previous_state.records)
    snapshot.filtered_records = list(previous_state.filtered_records)
    snapshot.selected = previous_state.selected
    snapshot.last_marker_coords = previous_state.last_marker_coords
    snapshot.record_search_index = build_search_index(list(previous_state.records))
    snapshot.recent_files = list(previous_state.recent_files)
    window.session_controller.restore(snapshot)


def reset_authoritative_runtime_state(window) -> None:
    window._local_record_read_status = None
    window._local_filter_facets_result = None
    window._local_filter_facets_status = None
    window._local_mutation_sync_status = None
    window._authoritative_write_status = None
    window._remote_snapshot_refresh_status = None
    window._filtered_metrics = None
    window._persistence_status_report = None
    window._record_integrity_report = None


def clear_loaded_data_view(window, empty_metrics: Dict[str, object]) -> None:
    window.session_controller.clear_workbook_state()
    window.gis = None
    window._local_record_read_status = None
    window._local_session_source_status = None
    window._local_filter_facets_result = None
    window._local_filter_facets_status = None
    window._local_mutation_sync_status = None
    window._authoritative_write_status = None
    window._remote_snapshot_refresh_status = None
    window._filtered_metrics = None
    window._persistence_status_report = None
    window._record_integrity_report = None

    window.data_tab.table.clearSelection()
    window.data_tab.table_model.update_data([])
    window.data_tab.update_totals_tables(empty_metrics)
    window.dash_tab.update_dashboard(
        empty_metrics,
        window.is_dark_mode,
        [],
        window._dashboard_record_overview,
        window._record_integrity_report,
        window._local_record_read_status,
    )
    window.data_tab.lbl_results.setText("0 registros")
    window._update_filters_from_records()
    window._setup_dynamic_form_options_from_records()
    window.clear_form(force=True)
    window.statusBar().showMessage("Banco local indisponível")
    window._refresh_window_chrome()
    navigation = getattr(window, "navigation_controller", None)
    if navigation is not None and hasattr(navigation, "update_operations_overview"):
        navigation.update_operations_overview()
    else:
        window.refresh_operations_overview()
