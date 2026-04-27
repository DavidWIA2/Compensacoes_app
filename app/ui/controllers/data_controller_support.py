from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple, cast

from app.models.compensacao import Compensacao
from app.services.record_integrity_service import RecordIntegrityReport
from app.services.records_service import display_tipo_value


COMPENSACOES_QUICK_FILTER_ALL = "all"
COMPENSACOES_QUICK_FILTER_PENDENTES = "pendentes"
COMPENSACOES_QUICK_FILTER_COMPENSADOS = "compensados"
COMPENSACOES_QUICK_FILTER_COM_PLANTIO = "com_plantio"
COMPENSACOES_QUICK_FILTER_OFICIOS = "oficios"
COMPENSACOES_QUICK_FILTER_QUALIDADE = "qualidade"
COMPENSACOES_QUICK_FILTER_SEM_MICRO = "sem_micro"
COMPENSACOES_QUICK_FILTER_SEM_GPS = "sem_gps"
COMPENSACOES_QUICK_FILTER_DUPLICIDADE_AV_TEC = "duplicidade_av_tec"

COMPENSACOES_QUICK_FILTER_MODES = (
    COMPENSACOES_QUICK_FILTER_ALL,
    COMPENSACOES_QUICK_FILTER_PENDENTES,
    COMPENSACOES_QUICK_FILTER_COMPENSADOS,
    COMPENSACOES_QUICK_FILTER_COM_PLANTIO,
    COMPENSACOES_QUICK_FILTER_OFICIOS,
    COMPENSACOES_QUICK_FILTER_QUALIDADE,
    COMPENSACOES_QUICK_FILTER_SEM_MICRO,
    COMPENSACOES_QUICK_FILTER_SEM_GPS,
    COMPENSACOES_QUICK_FILTER_DUPLICIDADE_AV_TEC,
)


@dataclass(frozen=True)
class FilterStateSnapshot:
    search_text: str = ""
    status: str = "Todos"
    year: str = "Todos"
    quick_filter_mode: str = COMPENSACOES_QUICK_FILTER_ALL
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
            "quick_filter_mode": self.quick_filter_mode,
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
            quick_filter_mode=str(state.get("quick_filter_mode", COMPENSACOES_QUICK_FILTER_ALL)),
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
        quick_filter_mode=str(getattr(window.data_tab, "quick_filter_mode", COMPENSACOES_QUICK_FILTER_ALL) or COMPENSACOES_QUICK_FILTER_ALL),
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
    quick_filter_buttons = dict(getattr(window.data_tab, "quick_filter_buttons", {}) or {})
    for button in quick_filter_buttons.values():
        button.blockSignals(True)
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
        restored_mode = (
            state.quick_filter_mode
            if state.quick_filter_mode in COMPENSACOES_QUICK_FILTER_MODES
            else COMPENSACOES_QUICK_FILTER_ALL
        )
        window.data_tab.quick_filter_mode = restored_mode
        for mode, button in quick_filter_buttons.items():
            button.setChecked(mode == restored_mode)
    finally:
        window.search.blockSignals(False)
        window.data_tab.filter_status.blockSignals(False)
        window.data_tab.filter_year.blockSignals(False)
        window.data_tab.filter_micro.blockSignals(False)
        window.data_tab.filter_eletronico.blockSignals(False)
        window.data_tab.filter_caixa.blockSignals(False)
        for button in quick_filter_buttons.values():
            button.blockSignals(False)


def record_identity_key(record: object) -> tuple[str, int, str]:
    return (
        str(getattr(record, "uid", "") or "").strip(),
        int(getattr(record, "excel_row", 0) or 0),
        str(getattr(record, "av_tec", "") or "").strip().upper(),
    )


def _record_text(record: object, attr: str) -> str:
    return str(getattr(record, attr, "") or "").strip()


def _record_has_microbacia(record: object) -> bool:
    return bool(_record_text(record, "microbacia"))


def _record_is_compensado(record: object) -> bool:
    return _record_text(record, "compensado").upper() == "SIM"


def _record_has_plantio(record: object) -> bool:
    if _record_text(record, "endereco_plantio"):
        return True
    return bool(tuple(getattr(record, "plantios", ()) or ()))


def _record_is_oficio(record: object) -> bool:
    return display_tipo_value(getattr(record, "eletronico", "")) == "Ofício"


def _record_is_missing_main_coordinates(record: object) -> bool:
    return not (_record_text(record, "latitude") and _record_text(record, "longitude"))


def build_duplicate_av_tec_record_keys(records: Sequence[Compensacao]) -> set[tuple[str, int, str]]:
    grouped_rows: dict[str, list[Compensacao]] = {}
    for record in records or ():
        av_tec = _record_text(record, "av_tec").upper()
        if not av_tec:
            continue
        grouped_rows.setdefault(av_tec, []).append(record)

    duplicate_keys: set[tuple[str, int, str]] = set()
    for group in grouped_rows.values():
        if len(group) < 2:
            continue
        for record in group:
            duplicate_keys.add(record_identity_key(record))
    return duplicate_keys


def build_quality_record_key_sets(
    *,
    all_records: Sequence[Compensacao],
    record_integrity_report: RecordIntegrityReport | None,
) -> dict[str, set[tuple[str, int, str]]]:
    issue_keys = {
        record_identity_key(issue)
        for issue in tuple(getattr(record_integrity_report, "issues", ()) or ())
    }
    sem_micro_keys = {
        record_identity_key(record)
        for record in all_records or ()
        if not _record_has_microbacia(record)
    }
    sem_gps_keys = {
        record_identity_key(record)
        for record in all_records or ()
        if _record_is_missing_main_coordinates(record)
    }
    sem_gps_issue_codes = {
        "incomplete_latitude_longitude",
        "invalid_latitude_format",
        "invalid_latitude_range",
        "invalid_longitude_format",
        "invalid_longitude_range",
    }
    sem_gps_keys.update(
        record_identity_key(issue)
        for issue in tuple(getattr(record_integrity_report, "issues", ()) or ())
        if str(getattr(issue, "code", "") or "").strip() in sem_gps_issue_codes
    )
    duplicate_av_tec_keys = build_duplicate_av_tec_record_keys(all_records)
    qualidade_keys = set(issue_keys)
    qualidade_keys.update(sem_micro_keys)
    qualidade_keys.update(sem_gps_keys)
    return {
        COMPENSACOES_QUICK_FILTER_QUALIDADE: qualidade_keys,
        COMPENSACOES_QUICK_FILTER_SEM_MICRO: sem_micro_keys,
        COMPENSACOES_QUICK_FILTER_SEM_GPS: sem_gps_keys,
        COMPENSACOES_QUICK_FILTER_DUPLICIDADE_AV_TEC: duplicate_av_tec_keys,
    }


def _filter_records_by_key_set(
    records: Sequence[Compensacao],
    allowed_keys: set[tuple[str, int, str]],
) -> list[Compensacao]:
    if not allowed_keys:
        return []
    return [record for record in records if record_identity_key(record) in allowed_keys]


def apply_compensacoes_quick_filter(
    records: Sequence[Compensacao],
    *,
    mode: str,
    quality_key_sets: dict[str, set[tuple[str, int, str]]] | None = None,
) -> list[Compensacao]:
    normalized_mode = str(mode or COMPENSACOES_QUICK_FILTER_ALL).strip() or COMPENSACOES_QUICK_FILTER_ALL
    if normalized_mode == COMPENSACOES_QUICK_FILTER_ALL:
        return list(records)
    if normalized_mode == COMPENSACOES_QUICK_FILTER_PENDENTES:
        return [record for record in records if not _record_is_compensado(record)]
    if normalized_mode == COMPENSACOES_QUICK_FILTER_COMPENSADOS:
        return [record for record in records if _record_is_compensado(record)]
    if normalized_mode == COMPENSACOES_QUICK_FILTER_COM_PLANTIO:
        return [record for record in records if _record_has_plantio(record)]
    if normalized_mode == COMPENSACOES_QUICK_FILTER_OFICIOS:
        return [record for record in records if _record_is_oficio(record)]
    if quality_key_sets is not None and normalized_mode in quality_key_sets:
        return _filter_records_by_key_set(records, quality_key_sets[normalized_mode])
    return list(records)


def build_compensacoes_quick_filter_counts(
    records: Sequence[Compensacao],
    *,
    quality_key_sets: dict[str, set[tuple[str, int, str]]] | None = None,
) -> dict[str, int]:
    counts = {
        COMPENSACOES_QUICK_FILTER_ALL: len(list(records)),
        COMPENSACOES_QUICK_FILTER_PENDENTES: 0,
        COMPENSACOES_QUICK_FILTER_COMPENSADOS: 0,
        COMPENSACOES_QUICK_FILTER_COM_PLANTIO: 0,
        COMPENSACOES_QUICK_FILTER_OFICIOS: 0,
        COMPENSACOES_QUICK_FILTER_QUALIDADE: 0,
        COMPENSACOES_QUICK_FILTER_SEM_MICRO: 0,
        COMPENSACOES_QUICK_FILTER_SEM_GPS: 0,
        COMPENSACOES_QUICK_FILTER_DUPLICIDADE_AV_TEC: 0,
    }
    for record in records:
        if not _record_is_compensado(record):
            counts[COMPENSACOES_QUICK_FILTER_PENDENTES] += 1
        if _record_is_compensado(record):
            counts[COMPENSACOES_QUICK_FILTER_COMPENSADOS] += 1
        if _record_has_plantio(record):
            counts[COMPENSACOES_QUICK_FILTER_COM_PLANTIO] += 1
        if _record_is_oficio(record):
            counts[COMPENSACOES_QUICK_FILTER_OFICIOS] += 1
    if quality_key_sets is None:
        return counts
    identity_keys = {record_identity_key(record) for record in records}
    for mode in (
        COMPENSACOES_QUICK_FILTER_QUALIDADE,
        COMPENSACOES_QUICK_FILTER_SEM_MICRO,
        COMPENSACOES_QUICK_FILTER_SEM_GPS,
        COMPENSACOES_QUICK_FILTER_DUPLICIDADE_AV_TEC,
    ):
        counts[mode] = len(identity_keys.intersection(quality_key_sets.get(mode, set())))
    return counts


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
