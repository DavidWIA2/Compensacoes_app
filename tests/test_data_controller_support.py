from types import SimpleNamespace

from app.models.compensacao import Compensacao
from app.ui.controllers.data_controller_support import (
    FilterStateSnapshot,
    build_filter_state_snapshot,
    capture_previous_data_state,
    clear_loaded_data_view,
    reset_authoritative_runtime_state,
    restore_filter_state_snapshot,
)


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "Gregorio",
        "compensado": "",
        "latitude": "",
        "longitude": "",
        "uid": "u-1",
    }
    base.update(overrides)
    return Compensacao(**base)


class FakeField:
    def __init__(self, value=""):
        self._value = value
        self.blocked = []

    def text(self):
        return self._value

    def setText(self, value):
        self._value = value

    def currentText(self):
        return self._value

    def setCurrentIndex(self, index):
        self._value = self.items[index]

    def findText(self, value):
        return self.items.index(value) if value in self.items else -1

    def blockSignals(self, blocked):
        self.blocked.append(blocked)


class FakeMultiSelect:
    def __init__(self, items, all_selected=True):
        self._items = list(items)
        self._all_selected = all_selected
        self.blocked = []

    def checked_items(self):
        return list(self._items)

    def is_all_selected(self):
        return self._all_selected

    def set_checked_items(self, items, all_selected=True):
        self._items = list(items)
        self._all_selected = all_selected

    def blockSignals(self, blocked):
        self.blocked.append(blocked)


def build_window():
    search = FakeField("Gregorio")
    status = FakeField("Pendentes")
    status.items = ["Todos", "Pendentes"]
    year = FakeField("2026")
    year.items = ["Todos", "2026"]
    micro = FakeMultiSelect(["Gregorio"], all_selected=False)
    ele = FakeMultiSelect(["SIM"], all_selected=False)

    window = SimpleNamespace(
        search=search,
        data_tab=SimpleNamespace(
            filter_status=status,
            filter_year=year,
            filter_micro=micro,
            filter_eletronico=ele,
            table=SimpleNamespace(clearSelection=lambda: None),
            table_model=SimpleNamespace(update_data=lambda data: setattr(window, "_table_data", data)),
            update_totals_tables=lambda metrics: setattr(window, "_totals_metrics", metrics),
            lbl_results=SimpleNamespace(setText=lambda text: setattr(window, "_results_label", text)),
        ),
        dash_tab=SimpleNamespace(update_dashboard=lambda *args: setattr(window, "_dashboard_args", args)),
        session_controller=SimpleNamespace(
            clear_workbook_state=lambda: setattr(window, "_cleared_session", True),
            snapshot=lambda: SimpleNamespace(
                records=[make_record()],
                filtered_records=[make_record(uid="u-2")],
                selected=make_record(uid="u-3"),
                last_marker_coords=(1.0, 2.0),
                recent_files=["session://banco-local"],
            ),
        ),
        is_dark_mode=False,
        _dashboard_record_overview="overview",
        _local_record_read_status="read-status",
        clear_form=lambda force=False: setattr(window, "_clear_form_force", force),
        _update_filters_from_records=lambda: setattr(window, "_filters_updated", True),
        _setup_dynamic_form_options_from_records=lambda: setattr(window, "_dynamic_options_updated", True),
        statusBar=lambda: SimpleNamespace(showMessage=lambda message: setattr(window, "_status_message", message)),
        _refresh_window_chrome=lambda: setattr(window, "_chrome_refreshed", True),
        refresh_operations_overview=lambda: setattr(window, "_ops_refreshed", True),
        gis="gis",
        recent_files=["session://banco-local"],
        _local_session_source_status="session-source",
        _local_filter_facets_result="facets",
        _local_filter_facets_status="facets-status",
        _local_mutation_sync_status="sync",
        _authoritative_write_status="write",
        _filtered_metrics={"count_total": 1},
        _persistence_status_report="report",
    )
    return window


def test_data_controller_support_builds_and_restores_filter_snapshot():
    window = build_window()
    snapshot = build_filter_state_snapshot(window)

    assert snapshot.search_text == "Gregorio"
    restore_filter_state_snapshot(
        window,
        FilterStateSnapshot.from_mapping(
            {
                "search_text": "Medeiros",
                "status": "Todos",
                "year": "Todos",
                "micro_all_selected": True,
                "selected_micros": [],
                "eletronico_all_selected": False,
                "selected_eletronicos": ["SIM"],
            }
        ),
        lambda value: "Eletrônico" if value == "SIM" else str(value),
    )

    assert window.search.text() == "Medeiros"
    assert window.data_tab.filter_status.currentText() == "Todos"
    assert window.data_tab.filter_eletronico.checked_items() == ["Eletrônico"]


def test_data_controller_support_captures_previous_data_state():
    window = build_window()

    previous_state = capture_previous_data_state(window, runtime_state={"path": "session://banco-local"})

    assert len(previous_state.records) == 1
    assert previous_state.last_marker_coords == (1.0, 2.0)
    assert previous_state.filter_state.search_text == "Gregorio"
    assert previous_state.runtime_state == {"path": "session://banco-local"}


def test_data_controller_support_resets_runtime_status():
    window = build_window()

    reset_authoritative_runtime_state(window)

    assert window._local_record_read_status is None
    assert window._local_filter_facets_result is None
    assert window._local_mutation_sync_status is None
    assert window._authoritative_write_status is None


def test_data_controller_support_clears_loaded_view():
    window = build_window()

    clear_loaded_data_view(window, {"count_total": 0})

    assert window.gis is None
    assert window._cleared_session is True
    assert window._table_data == []
    assert window._results_label == "0 registros"
    assert window._clear_form_force is True
    assert window._status_message == "Banco local indisponível"
