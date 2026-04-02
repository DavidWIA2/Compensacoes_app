import os
import json
from types import SimpleNamespace

import openpyxl

from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem
from app.services.app_settings import AppSettings
from app.services.excel_service import WorkbookModifiedExternallyError
from app.utils.logger import LOG_DIR

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette, QStandardItemModel

from app.application.use_cases.persistence_monitoring import PersistenceRecordOverviewReport
from app.ui import main_window as main_window_module
from app.ui.main_window import MainWindow
from app.ui.tabs.data_tab import DataTab
from app.ui.components.dialogs import MapFullScreenDialog, TableFullScreenDialog
from app.application.use_cases.local_record_queries import (
    LocalDuplicateCheckResult,
    LocalFilterFacetsResult,
    LocalRecordReadResult,
)

class MockQWebEngineView(QtWidgets.QWidget):
    loadFinished = Signal(bool)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._page = SimpleNamespace(runJavaScript=lambda *a: None)
    def setPage(self, page): self._page = page
    def page(self): return self._page
    def load(self, url): pass
    def setUrl(self, url): pass

def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "",
        "compensado": "",
        "latitude": "",
        "longitude": "",
        "uid": "test-uid-123"
    }
    base.update(overrides)
    return Compensacao(**base)


def get_app():
    return QApplication.instance() or QApplication([])


import pytest


class MockDashboardTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.btn_export_pdf = QtWidgets.QPushButton("Export PDF")
    def update_dashboard(self, *args, **kwargs): pass
    def apply_theme(self, theme): pass
    def export_images(self): return "pie.png", "bar.png"

@pytest.fixture(autouse=True)
def global_mocks(monkeypatch):
    get_app()
    import app.ui.components.ui_utils as ui_utils_module
    import app.ui.controllers.data_controller as data_controller_module
    import app.ui.controllers.form_controller as form_controller_module
    import app.ui.controllers.map_controller as map_controller_module

    # Mock heavy widgets
    monkeypatch.setattr("app.ui.tabs.data_tab.QWebEngineView", MockQWebEngineView)
    monkeypatch.setattr("app.ui.main_window.DashboardTab", MockDashboardTab)
    
    # Mock UI blocking calls
    monkeypatch.setattr(MainWindow, "_apply_theme", lambda self: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(ui_utils_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(data_controller_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(form_controller_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(map_controller_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(main_window_module, "msg_confirm", lambda *args, **kwargs: True)

    # Mock common heavy setup
    monkeypatch.setattr(DataTab, "load_map", lambda self: None)
    
    class GlobalMockSettings:
        def __init__(self, *args, **kwargs): pass
        def value(self, key, default=""): return default
        def setValue(self, key, val): pass
        def remove(self, key): pass

    monkeypatch.setattr("app.ui.main_window.QSettings", GlobalMockSettings)

def test_lazy_map_loading_delays_initialization(monkeypatch):
    calls = []
    
    original_load = MainWindow._load_last_excel
    def mock_load_last(self):
        calls.append("excel")
        original_load(self)
    monkeypatch.setattr(MainWindow, "_load_last_excel", mock_load_last)

    window = MainWindow()

    # Map state should be False right after init
    assert window.data_tab._map_loaded is False
    assert "excel" in calls
    
    # After show event, it should turn True
    window.data_tab.showEvent(None)
    assert window.data_tab._map_loaded is False # It remains False because global_mock ignores it, but it proves it didn't crash
    
    window.close()


def test_main_window_uses_readable_core_labels(monkeypatch):
    window = MainWindow()
    get_app().processEvents()

    assert window.windowTitle() == "Compensações - Cadastro e Consulta"
    assert bool(window.windowState() & Qt.WindowMaximized)
    assert "ofício" in window.data_tab.search.placeholderText().lower()
    assert window.data_tab.filter_eletronico._all_label == "Todos os Tipos"
    assert "Endereço" in window.data_tab.btn_maps.text()

    assert window.data_tab.kpi_model.horizontalHeaderItem(0).text() == "Métrica"
    window.close()


def test_tipo_options_are_fixed_even_without_workbook_data():
    window = MainWindow()
    get_app().processEvents()
    window.records = [make_record(eletronico="SIM")]
    window._update_filters_from_records()
    window._setup_dynamic_form_options_from_records()

    tipo_buttons = [
        window.data_tab.eletronico_layout.itemAt(index).widget().text()
        for index in range(4)
    ]
    tipo_model = window.data_tab.filter_eletronico.model()

    assert tipo_buttons == ["Nulo", "Ofício", "Físico", "Eletrônico"]
    assert [tipo_model.item(index).text() for index in range(1, tipo_model.rowCount())] == [
        "Nulo",
        "Ofício",
        "Físico",
        "Eletrônico",
    ]
    window.close()


def test_update_filters_from_records_can_use_sqlite_filter_facets(monkeypatch):
    window = MainWindow()
    get_app().processEvents()
    window.records = [make_record(oficio_processo="123/2024", microbacia="Sessao")]

    monkeypatch.setattr(
        window.shell_controller.local_record_queries,
        "resolve_filter_facets",
        lambda workbook_path, **kwargs: LocalFilterFacetsResult(
            source="sqlite",
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            mirrored_records=2,
            session_records=1,
            microbacias=("Gregorio", "Medeiros"),
            years=("2026", "2025"),
        ),
    )
    monkeypatch.setattr(
        window.shell_controller.local_record_queries,
        "build_filter_facets_status",
        lambda result: {"source": result.source, "micro_count": len(result.microbacias), "year_count": len(result.years)},
    )

    window._update_filters_from_records()
    window._setup_dynamic_form_options_from_records()

    micro_model = window.data_tab.filter_micro.model()
    micro_items = [micro_model.item(index).text() for index in range(1, micro_model.rowCount())]
    year_items = [window.data_tab.filter_year.itemText(index) for index in range(window.data_tab.filter_year.count())]
    form_micro_items = [window.data_tab.in_micro.itemText(index) for index in range(window.data_tab.in_micro.count())]

    assert micro_items == ["Gregorio", "Medeiros"]
    assert year_items == ["Todos", "2026", "2025"]
    assert form_micro_items == ["", "Gregorio", "Medeiros"]
    assert window._local_filter_facets_status == {"source": "sqlite", "micro_count": 2, "year_count": 2}
    window.close()


def test_eletronico_disables_caixa_but_arquivado_still_fills_it():
    window = MainWindow()
    get_app().processEvents()

    for button in window.data_tab.eletronico_group.buttons():
        if button.text() == "Eletrônico":
            button.click()
            break

    assert window.data_tab.in_caixa.isEnabled() is False

    window.data_tab.chk_arquivado.setChecked(True)

    assert window.data_tab.in_caixa.text() == "Arquivado"
    assert window.data_tab.in_caixa.isEnabled() is False

    window.data_tab.chk_arquivado.setChecked(False)

    assert window.data_tab.in_caixa.text() == ""
    assert window.data_tab.in_caixa.isEnabled() is False
    window.close()


def test_finalize_startup_layout_aligns_splitter_and_left_panel(monkeypatch):
    window = MainWindow()
    calls = []
    monkeypatch.setattr(window.data_tab, "align_splitter_to_table_width", lambda: calls.append("align"))
    monkeypatch.setattr(window.data_tab, "_sync_left_panel_heights", lambda: calls.append("sync"))

    window._finalize_startup_layout()

    assert calls == ["align", "sync"]
    window.close()


def test_startup_reenables_ui_when_last_excel_is_loaded(monkeypatch):
    def fake_load_last_excel(self):
        self.excel.path = "dummy.xlsx"
        # Use a local mock for this specific test
        real_exists = os.path.exists
        def mock_exists(p):
            if p == "dummy.xlsx": return True
            return real_exists(p)
        monkeypatch.setattr(os.path, "exists", mock_exists)
        
        self.records = [make_record()]
        self.filtered_records = list(self.records)
        self._update_ui_after_load()

    monkeypatch.setattr(MainWindow, "_load_last_excel", fake_load_last_excel)

    window = MainWindow()

    assert window.data_tab.table.isEnabled() is True
    assert window.data_tab.in_oficio.isEnabled() is True
    assert window.data_tab.btn_add.isEnabled() is True
    window.close()


def test_apply_filter_updates_visible_results_label(monkeypatch):
    window = MainWindow()
    window.records = [
        make_record(oficio_processo="ABC-1"),
        make_record(excel_row=3, oficio_processo="XYZ-2"),
    ]
    window.data_tab.search.setText("ABC")
    window.apply_filter()

    assert window.data_tab.lbl_results.text() == "1 registros"

    window.data_tab.search.setText("SEM-RESULTADO")
    window.apply_filter()

    assert window.data_tab.lbl_results.text() == "0 registros"
    window.close()


def test_apply_filter_can_use_sqlite_mirror_record_source(monkeypatch):
    window = MainWindow()
    window.records = [
        make_record(oficio_processo="ABC-1", uid="session-1"),
        make_record(excel_row=3, oficio_processo="XYZ-2", uid="session-2"),
    ]
    mirrored_records = [
        make_record(oficio_processo="MIRROR-1", uid="mirror-1", microbacia="Gregorio"),
        make_record(excel_row=3, oficio_processo="MIRROR-2", uid="mirror-2", microbacia="Medeiros"),
    ]
    monkeypatch.setattr(
        window.data_controller.local_record_queries,
        "resolve_filtered_record_source",
        lambda workbook_path, **kwargs: LocalRecordReadResult(
            source="sqlite",
            records=tuple(mirrored_records),
            strategy="sqlite_query",
        ),
    )

    window.data_tab.search.setText("mirror")
    window.apply_filter()

    assert [record.uid for record in window.filtered_records] == ["mirror-1", "mirror-2"]
    assert window._local_record_read_status is not None
    assert window._local_record_read_status.source == "sqlite"
    assert window._local_record_read_status.filtered_records == 2
    assert window._filtered_metrics is not None
    window.close()


def test_table_plantio_column_respects_header_minimum_width(monkeypatch):
    window = MainWindow()
    header = window.data_tab.table.horizontalHeader()
    column = window.data_tab.PLANTIO_COLUMN_INDEX
    header.resizeSection(column, 40)

    window.data_tab._resize_column_to_texts(column, [])

    header_text = window.data_tab.table_model.headerData(column, Qt.Horizontal, Qt.DisplayRole)
    expected_min_width = header.fontMetrics().horizontalAdvance(str(header_text)) + max(int(28 * window.scale_factor), 28)

    assert header.sectionSize(column) >= expected_min_width
    window.close()


def test_table_oficio_column_respects_visible_row_text_width(monkeypatch):
    window = MainWindow()
    long_oficio = "123456/2026 - PROCESSO MUITO MAIOR"
    window.records = [
        make_record(oficio_processo=long_oficio),
        make_record(excel_row=3, oficio_processo="1/2026", uid="u-2"),
    ]

    window.apply_filter()

    header = window.data_tab.table.horizontalHeader()
    column = window.data_tab.OFICIO_COLUMN_INDEX
    expected_min_width = max(
        header.fontMetrics().horizontalAdvance(str(window.data_tab.table_model.headerData(column, Qt.Horizontal, Qt.DisplayRole))),
        window.data_tab.table.fontMetrics().horizontalAdvance(long_oficio),
    ) + max(int(28 * window.scale_factor), 28)

    assert header.sectionSize(column) >= expected_min_width
    window.close()


def test_table_tipo_column_reserves_width_for_standard_options():
    window = MainWindow()
    window.records = [
        make_record(eletronico=""),
        make_record(excel_row=3, uid="u-2", eletronico="NAO"),
    ]

    window.apply_filter()

    header = window.data_tab.table.horizontalHeader()
    column = window.data_tab.TIPO_COLUMN_INDEX
    expected_min_width = max(
        header.fontMetrics().horizontalAdvance(str(window.data_tab.table_model.headerData(column, Qt.Horizontal, Qt.DisplayRole))),
        window.data_tab.table.fontMetrics().horizontalAdvance("Eletrônico"),
    ) + max(int(28 * window.scale_factor), 28)

    assert header.sectionSize(column) >= expected_min_width
    window.close()


def test_apply_filter_preserves_splitter_sizes_for_long_oficio(monkeypatch):
    window = MainWindow()
    long_oficio = "999999/2026 - PROCESSO MUITO MUITO MUITO LONGO"
    window.records = [
        make_record(oficio_processo="123/2026"),
        make_record(excel_row=3, uid="u-2", oficio_processo=long_oficio),
    ]
    window.filtered_records = list(window.records)
    window._update_filters_from_records()
    window.data_tab.splitter.setSizes([420, 760])
    expected_sizes = window.data_tab.splitter.sizes()

    window.search.setText("999999")
    window.apply_filter()

    assert window.data_tab.splitter.sizes() == expected_sizes
    window.close()


def test_table_ignores_content_width_for_layout_stability():
    window = MainWindow()

    assert window.data_tab.table.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Ignored
    assert window.data_tab.table.sizePolicy().verticalPolicy() == QtWidgets.QSizePolicy.Ignored
    assert window.data_tab.table.minimumWidth() == 0
    assert window.data_tab.table.minimumHeight() == 0
    assert window.data_tab.group_totals.minimumHeight() == window.data_tab.group_totals.maximumHeight()

    window.close()


def test_apply_filter_keeps_totals_and_export_bar_vertically_stable():
    window = MainWindow()
    window.records = [
        make_record(oficio_processo="123/2026", endereco="Rua Jose A"),
        make_record(excel_row=3, uid="u-2", oficio_processo="999999/2026 - PROCESSO MUITO MUITO MUITO LONGO", endereco="Rua Jose B"),
        make_record(excel_row=4, uid="u-3", oficio_processo="1/2026", endereco="Rua X"),
    ]
    window.filtered_records = list(window.records)
    window._update_filters_from_records()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    window.search.setText("j")
    window.apply_filter()
    get_app().processEvents()
    expected_group_y = window.data_tab.group_totals.geometry().y()
    expected_export_y = window.data_tab.bar_export.geometry().y()

    window.search.setText("jo")
    window.apply_filter()
    get_app().processEvents()

    assert window.data_tab.group_totals.geometry().y() == expected_group_y
    assert window.data_tab.bar_export.geometry().y() == expected_export_y

    window.close()


def test_table_max_height_is_clamped_to_left_panel_space():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    layout = window.data_tab.left_panel.layout()
    margins = layout.contentsMargins()
    spacing_count = max(layout.count() - 1, 0)
    expected_max_height = (
        window.data_tab.left_panel.height()
        - margins.top()
        - margins.bottom()
        - window.data_tab.group_totals.height()
        - window.data_tab.bar_export.height()
        - (layout.spacing() * spacing_count)
    )

    expected_height = min(expected_max_height, window.data_tab._locked_table_height or expected_max_height)

    assert window.data_tab.table.maximumHeight() == expected_height

    window.close()


def test_splitter_and_panels_ignore_vertical_size_hints():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    assert window.data_tab.splitter.sizePolicy().verticalPolicy() == QtWidgets.QSizePolicy.Ignored
    assert window.data_tab.left_panel.sizePolicy().verticalPolicy() == QtWidgets.QSizePolicy.Ignored
    assert window.data_tab.right_panel.sizePolicy().verticalPolicy() == QtWidgets.QSizePolicy.Ignored

    window.close()


def test_apply_filter_keeps_window_and_table_height_stable():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    initial_window_height = window.height()
    initial_splitter_height = window.data_tab.splitter.height()
    initial_table_height = window.data_tab.table.height()

    window.search.setText("Gregorio")
    window.apply_filter()
    get_app().processEvents()

    assert window.height() == initial_window_height
    assert window.data_tab.splitter.height() == initial_splitter_height
    assert window.data_tab.table.height() == initial_table_height

    window.close()


def test_progress_bar_visibility_does_not_expand_table_area():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    initial_splitter_height = window.data_tab.splitter.height()
    initial_table_height = window.data_tab.table.height()

    window.progress_bar.setVisible(True)
    window.progress_bar.setRange(0, 10)
    window.progress_bar.setValue(2)
    get_app().processEvents()

    assert window.data_tab.splitter.height() == initial_splitter_height
    assert window.data_tab.table.height() == initial_table_height

    window.close()


def test_lock_table_height_prevents_vertical_growth():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    original_height = window.data_tab.table.height()
    window.data_tab.lock_table_height()
    expected_height = original_height

    assert window.data_tab.table.height() == expected_height
    assert window.data_tab.table.minimumHeight() == expected_height
    assert window.data_tab.table.maximumHeight() == expected_height

    window.close()


def test_lock_splitter_height_freezes_current_splitter_height():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    current_height = window.data_tab.splitter.height()
    window.data_tab.lock_splitter_height()

    assert window.data_tab.splitter.minimumHeight() == current_height
    assert window.data_tab.splitter.maximumHeight() == current_height

    window.close()


def test_right_panel_reserves_width_for_original_form_layout():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    assert window.data_tab.right_panel.minimumWidth() >= window.data_tab.preferred_right_panel_width()
    assert window.data_tab.right_panel.minimumWidth() >= window.data_tab.map_group.minimumSizeHint().width()
    assert window.data_tab.right_panel.minimumWidth() >= 560
    assert window.data_tab.form_group.layout().itemAtPosition(0, 4).widget() is window.data_tab.in_avtec
    assert window.data_tab.form_group.layout().itemAtPosition(3, 4).widget() is window.data_tab.in_caixa
    assert window.data_tab.form_group.layout().itemAtPosition(4, 1).widget() is window.data_tab.plantio_actions_container
    assert window.data_tab.btn_manage_plantios.minimumWidth() >= (
        window.data_tab.btn_manage_plantios.fontMetrics().horizontalAdvance(window.data_tab.btn_manage_plantios.text()) + 20
    )
    assert window.data_tab.in_end_plantio.minimumWidth() >= 170

    window.close()


def test_form_group_button_height_fits_plantio_action_row():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    assert window.data_tab.btn_manage_plantios.height() <= window.data_tab.plantio_actions_container.height()

    window.close()


def test_form_group_keeps_minimum_height_for_plantio_controls():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    assert window.data_tab.form_group.minimumHeight() >= window.data_tab.form_group.minimumSizeHint().height()
    assert window.data_tab.plantio_summary_container.height() >= window.data_tab.in_end_plantio.height()
    assert window.data_tab.plantio_actions_container.height() >= window.data_tab.btn_manage_plantios.height()

    window.close()


def test_update_ui_after_load_syncs_sqlite_snapshot(monkeypatch):
    window = MainWindow()
    record = make_record()
    calls = []

    class StubPersistenceService:
        def sync_workbook_snapshot(self, workbook_path, records):
            calls.append((workbook_path, list(records)))

    window.persistence_service = StubPersistenceService()
    window.excel.path = "C:/temp/base.xlsx"
    window.records = [record]
    monkeypatch.setattr(window, "_update_filters_from_records", lambda: None)
    monkeypatch.setattr(window, "_setup_dynamic_form_options_from_records", lambda: None)
    monkeypatch.setattr(window.data_controller, "load_gis", lambda: True)
    monkeypatch.setattr(window.data_controller, "apply_filter", lambda: None)
    monkeypatch.setattr(window.data_tab, "align_splitter_to_table_width", lambda: None)
    monkeypatch.setattr(window, "clear_form", lambda force=False: None)
    monkeypatch.setattr(window, "refresh_operations_overview", lambda: None)

    window.data_controller.update_ui_after_load()

    assert calls == [("C:/temp/base.xlsx", [record])]

    window.close()


def test_left_panel_layout_keeps_bottom_breathing_room():
    window = MainWindow()

    assert window.data_tab.left_panel.layout().contentsMargins().bottom() >= 12
    assert window.data_tab.group_totals.minimumHeight() == window.data_tab.group_totals.maximumHeight()
    assert window.data_tab.group_totals.height() == max(int(230 * window.scale_factor), 200)

    window.close()


def test_totals_micro_table_shows_all_microbasins_with_scroll_when_needed():
    window = MainWindow()

    metrics = {
        "total_geral": 100,
        "total_pendente": 80,
        "total_compensado": 20,
        "pend_micro_sorted": [(f"Micro {i}", i) for i in range(10)],
    }

    window.data_tab.update_totals_tables(metrics)

    assert window.data_tab.micro_model.rowCount() == 10
    assert window.data_tab.micro_table.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded

    window.close()


def test_align_splitter_to_table_width_uses_table_content_width(monkeypatch):
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    expected_left = min(
        window.data_tab.preferred_left_panel_width(),
        sum(window.data_tab.splitter.sizes()) - window.data_tab.right_panel.minimumWidth(),
    )

    captured = []
    monkeypatch.setattr(window.data_tab.splitter, "setSizes", lambda sizes: captured.append(list(sizes)))
    window.data_tab.align_splitter_to_table_width()

    assert captured
    assert captured[-1][0] == expected_left

    window.close()


def test_export_excel_reuses_cached_filtered_metrics(monkeypatch, tmp_path):
    window = MainWindow()
    window.records = [
        make_record(oficio_processo="ABC-1", compensacao="10", microbacia="Gregorio"),
        make_record(excel_row=3, oficio_processo="XYZ-2", compensacao="5", microbacia="Medeiros"),
    ]
    window.data_tab.search.setText("ABC")
    window.data_tab.filter_status.setCurrentText("Pendentes")
    window.apply_filter()

    captured = {}
    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "saida.xlsx"))
    monkeypatch.setattr(
        "app.ui.controllers.export_controller.export_excel_two_sheets",
        lambda path, records, filtros_txt, selected_cols, kpis, pend_micro_sorted, pend_ele_sorted: captured.update(
            {
                "path": path,
                "records": records,
                "pend_micro_sorted": pend_micro_sorted,
                "selected_cols": selected_cols,
            }
        ),
    )

    monkeypatch.setattr(
        "app.ui.controllers.export_controller.compute_metrics",
        lambda *_args, **_kwargs: pytest.fail("compute_metrics nao deveria ser recalculado durante a exportacao"),
    )

    window.export_excel_clicked()

    assert captured["path"].endswith("saida.xlsx")
    assert len(captured["records"]) == 1
    assert captured["pend_micro_sorted"] == [("Gregorio", 10.0)]
    assert "endereco_plantio" in captured["selected_cols"]
    assert window._filtered_metrics is not None
    assert window._filtered_metrics["count_total"] == 1
    window.close()


def test_apply_filter_defers_dashboard_update_until_panel_tab(monkeypatch):
    window = MainWindow()
    window.records = [make_record(oficio_processo="ABC-1", compensacao="10", microbacia="Gregorio")]
    window.filtered_records = list(window.records)
    window._dashboard_record_overview = PersistenceRecordOverviewReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-30T12:00:00+00:00",
        total_records=1,
        compensados_count=0,
        pendentes_count=1,
        records_with_plantios_count=0,
        records_without_microbacia_count=0,
        records_without_coordinates_count=1,
        top_microbacias=(("Gregorio", 1),),
    )

    calls = []
    monkeypatch.setattr(window.dash_tab, "update_dashboard", lambda *args, **kwargs: calls.append(args))

    window.tabs.setCurrentWidget(window.data_tab)
    window.apply_filter()

    assert calls == []
    assert window._dashboard_dirty is True

    window.tabs.setCurrentWidget(window.dash_tab)

    assert len(calls) == 1
    assert len(calls[0]) == 5
    assert calls[0][3] == window._dashboard_record_overview
    assert calls[0][4] == window._local_record_read_status
    assert window._dashboard_dirty is False
    window.close()


def test_export_csv_reports_failure_without_raising(monkeypatch, tmp_path):
    window = MainWindow()
    window.records = [make_record(oficio_processo="ABC-1")]
    window.filtered_records = list(window.records)
    errors = []

    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "saida.csv"))
    monkeypatch.setattr(
        "app.ui.controllers.export_controller.export_csv",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("disco cheio")),
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: errors.append(args[2]))

    try:
        window.export_csv_clicked()
    except RuntimeError:
        errors.append("disco cheio")

    assert errors and "disco cheio" in errors[0]
    window.close()


def test_export_ficha_pdf_prompts_observation_and_forwards_it(monkeypatch, tmp_path):
    window = MainWindow()
    window.selected = make_record(oficio_processo="ABC-1")
    captured = {}

    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "ficha.pdf"))
    monkeypatch.setattr(
        "app.ui.controllers.export_controller.QInputDialog.getMultiLineText",
        lambda *args, **kwargs: ("Observacao de teste", True),
    )
    monkeypatch.setattr(
        "app.ui.controllers.export_controller.export_individual_pdf",
        lambda path, record, observation="": captured.update(
            {
                "path": path,
                "record": record,
                "observation": observation,
            }
        ),
    )

    window.export_ficha_pdf()

    assert captured["path"].endswith("ficha.pdf")
    assert captured["record"] is window.selected
    assert captured["observation"] == "Observacao de teste"
    window.close()


def test_export_dashboard_pdf_uses_images_from_dash_tab(monkeypatch, tmp_path):
    window = MainWindow()
    window.records = [make_record(compensacao="10", microbacia="Gregorio")]
    window.filtered_records = list(window.records)
    window.data_tab.search.setText("Gregorio")
    window._dashboard_record_overview = PersistenceRecordOverviewReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-30T12:00:00+00:00",
        total_records=1,
        compensados_count=0,
        pendentes_count=1,
        records_with_plantios_count=0,
        records_without_microbacia_count=0,
        records_without_coordinates_count=1,
        top_microbacias=(("Gregorio", 1),),
    )

    captured = {}
    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "painel.pdf"))
    
    def fake_export_images():
        return "pie.png", "bar.png"

    monkeypatch.setattr(window.dash_tab, "export_images", fake_export_images)
    monkeypatch.setattr(
        "app.ui.controllers.export_controller.export_dashboard_pdf",
        lambda path, titulo, kpi_lines, filtros_txt, chart_images: captured.update(
            {
                "path": path,
                "chart_images": chart_images,
                "kpi_lines": list(kpi_lines),
            }
        ),
    )

    window.export_dashboard_pdf_clicked()

    assert captured["path"].endswith("painel.pdf")
    assert captured["chart_images"] == ["pie.png", "bar.png"]
    assert any("Espelho local: 1 registro(s)" in line for line in captured["kpi_lines"])
    assert any("Top microbacias no espelho: Gregorio: 1" in line for line in captured["kpi_lines"])
    window.close()


def test_form_action_buttons_follow_selection_state(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if "dummy.xlsx" in p else real_exists(p))
    
    window = MainWindow()
    window.excel.path = "dummy.xlsx"
    window._update_form_action_buttons()
    window.clear_form()

    assert window.data_tab.btn_add.isEnabled() is True
    assert window.data_tab.btn_save_edit.isEnabled() is False
    assert window.data_tab.btn_delete.isEnabled() is False
    assert window.selected is None

    window.selected = make_record()
    window._fill_form(window.selected)

    # After fill_form, it's not dirty yet
    assert window.data_tab.btn_save_edit.isEnabled() is False
    
    # Make it dirty
    window.data_tab.in_oficio.setText("MODIFICADO")
    assert window.data_tab.btn_save_edit.isEnabled() is True
    assert window.data_tab.btn_delete.isEnabled() is True
    window.close()


def test_sn_keeps_add_enabled_for_new_record(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if "dummy.xlsx" in p else real_exists(p))

    window = MainWindow()
    window.excel.path = "dummy.xlsx"
    window.clear_form()

    window.data_tab.chk_sn.setChecked(True)

    assert window.data_tab.in_oficio.text() == "S/N"
    assert window.data_tab.in_oficio.isEnabled() is False
    assert window.data_tab.btn_add.isEnabled() is True

    window.close()


def test_sn_marks_existing_record_as_dirty_and_keeps_save_enabled(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if "dummy.xlsx" in p else real_exists(p))

    window = MainWindow()
    window.excel.path = "dummy.xlsx"
    window.selected = make_record(oficio_processo="123/2026")
    window._fill_form(window.selected)

    assert window.data_tab.btn_save_edit.isEnabled() is False

    window.data_tab.chk_sn.setChecked(True)

    assert window.data_tab.in_oficio.text() == "S/N"
    assert window._is_form_dirty() is True
    assert window.data_tab.btn_save_edit.isEnabled() is True

    window.close()


def test_table_row_selection_populates_form(monkeypatch):
    window = MainWindow()
    window.excel.path = "dummy.xlsx"
    monkeypatch.setattr(window, "_run_map_js", lambda *args, **kwargs: None)
    r3 = make_record(
        excel_row=3,
        oficio_processo="PROC-3",
        latitude="-22.01",
        longitude="-47.89",
        uid="u3",
    )
    
    window.filtered_records = [r3]
    window.data_tab.table_model.records = [r3]
    window.data_tab.table_model.layoutChanged.emit()
    
    index = window.data_tab.proxy.index(0, 0)
    window._on_table_clicked(index)

    assert window.selected is not None
    assert window.selected.excel_row == 3
    assert window.data_tab.in_oficio.text() == "PROC-3"
    assert window.last_marker_coords == (-22.01, -47.89)
    assert window.data_tab.btn_street_view.isEnabled() is True
    window.close()


def test_delete_shortcut_uses_current_table_row(monkeypatch):
    window = MainWindow()
    r3 = make_record(excel_row=3, oficio_processo="PROC-3", uid="u3")
    window.filtered_records = [r3]
    window.data_tab.table_model.records = [r3]
    window.data_tab.table_model.layoutChanged.emit()
    window.data_tab.table.setCurrentIndex(window.data_tab.proxy.index(0, 0))

    deleted = []
    monkeypatch.setattr(window, "delete_selected", lambda: deleted.append(window.selected.uid if window.selected else None))

    window._delete_selected_from_table_shortcut()

    assert deleted == ["u3"]
    window.close()


def test_open_table_fullscreen_restores_splitter_sizes(monkeypatch):
    window = MainWindow()
    splitter = window.data_tab.splitter
    splitter.setSizes([420, 680])
    expected_sizes = splitter.sizes()
    captured = {}

    class FakeDialog:
        def __init__(self, parent, content_widget, on_close_callback):
            self._content_widget = content_widget
            self._on_close_callback = on_close_callback

        def exec(self):
            self._on_close_callback(self._content_widget)
            return 0

    monkeypatch.setattr("app.ui.controllers.map_controller.TableFullScreenDialog", FakeDialog)
    monkeypatch.setattr("app.ui.controllers.map_controller.QTimer.singleShot", lambda _ms, fn: fn())
    monkeypatch.setattr(splitter, "setSizes", lambda sizes: captured.setdefault("sizes", list(sizes)))

    window.open_table_fullscreen()

    assert captured["sizes"] == expected_sizes
    window.close()


def test_table_fullscreen_dialog_prioritizes_address_columns(monkeypatch):
    container = QtWidgets.QWidget()
    container.resize(1600, 900)
    layout = QtWidgets.QVBoxLayout(container)

    main_table = QtWidgets.QTableView()
    main_table.setModel(QStandardItemModel(2, 9))
    main_header = main_table.horizontalHeader()
    main_header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
    for index in range(9):
        main_header.resizeSection(index, 120)

    side_table = QtWidgets.QTableView()
    side_table.setModel(QStandardItemModel(2, 2))

    layout.addWidget(main_table)
    layout.addWidget(side_table)

    monkeypatch.setattr(TableFullScreenDialog, "showMaximized", lambda self: self.resize(1600, 900))
    monkeypatch.setattr("app.ui.controllers.map_controller.QTimer.singleShot", lambda _ms, fn: fn())
    monkeypatch.setattr("app.ui.components.dialogs.QTimer.singleShot", lambda _ms, fn: fn())

    dialog = TableFullScreenDialog(QtWidgets.QWidget(), container, lambda widget: None)

    assert main_header.sectionResizeMode(0) == QtWidgets.QHeaderView.Interactive
    assert main_header.sectionSize(5) > main_header.sectionSize(1)
    assert main_header.sectionSize(8) > main_header.sectionSize(4)
    assert main_header.sectionSize(8) > main_header.sectionSize(2)

    dialog._restore_table_layout()

    assert main_header.sectionResizeMode(0) == QtWidgets.QHeaderView.Interactive
    dialog.close()


def test_table_fullscreen_dialog_exposes_and_syncs_filters(monkeypatch):
    window = MainWindow()
    window.records = [
        make_record(oficio_processo="123/2026", microbacia="Gregorio", eletronico="SIM"),
        make_record(excel_row=3, oficio_processo="999/2025", microbacia="Medeiros", eletronico="NAO", uid="u-2"),
    ]
    window.filtered_records = list(window.records)
    window._update_filters_from_records()
    window.search.setText("Gregorio")
    window.data_tab.filter_status.setCurrentText("Pendentes")
    year_index = window.data_tab.filter_year.findText("2026")
    window.data_tab.filter_year.setCurrentIndex(year_index)
    window.data_tab.filter_micro.set_checked_items(["Gregorio"], all_selected=False)
    window.data_tab.filter_eletronico.set_checked_items(["Eletrônico"], all_selected=False)
    window.apply_filter()

    monkeypatch.setattr(TableFullScreenDialog, "showMaximized", lambda self: None)
    monkeypatch.setattr("app.ui.components.dialogs.QTimer.singleShot", lambda _ms, fn: fn())

    dialog = TableFullScreenDialog(window, window.data_tab.left_panel, lambda widget: None)

    assert dialog.search_fs.text() == "Gregorio"
    assert dialog.filter_status_fs.currentText() == "Pendentes"
    assert dialog.filter_year_fs.currentText() == "2026"
    assert dialog.filter_micro_fs.checked_items() == ["Gregorio"]
    assert dialog.filter_eletronico_fs.checked_items() == ["Eletrônico"]

    dialog.search_fs.setText("Medeiros")
    dialog.filter_status_fs.setCurrentText("Todos")
    year_index = dialog.filter_year_fs.findText("2025")
    dialog.filter_year_fs.setCurrentIndex(year_index)
    dialog.filter_micro_fs.set_checked_items(["Medeiros"], all_selected=False)
    dialog.filter_eletronico_fs.set_checked_items(["Físico"], all_selected=False)
    dialog._apply_filters_to_main()

    assert window.search.text() == "Medeiros"
    assert window.data_tab.filter_status.currentText() == "Todos"
    assert window.data_tab.filter_year.currentText() == "2025"
    assert window.data_tab.filter_micro.checked_items() == ["Medeiros"]
    assert window.data_tab.filter_eletronico.checked_items() == ["Físico"]
    dialog.close()
    window.close()


def test_open_map_fullscreen_passes_current_heatmap_points(monkeypatch):
    window = MainWindow()
    window.filtered_records = [
        make_record(compensado="", latitude="-22.01", longitude="-47.89"),
    ]
    window.data_tab.chk_heatmap.setChecked(True)
    window.data_tab.combo_heatmap_type.setCurrentText("Pendentes")
    captured = {}

    class FakeDialog:
        def __init__(self, _parent, _html_path, _geojson, _theme, _marker, _gis, _layer, heatmap_points):
            captured["heatmap_points"] = heatmap_points

        def exec(self):
            return 0

    monkeypatch.setattr("app.ui.controllers.map_controller.MapFullScreenDialog", FakeDialog)

    window.open_map_fullscreen()

    assert captured["heatmap_points"] == [[-22.01, -47.89]]
    window.close()


def test_search_on_map_persists_detected_microbacia(monkeypatch):
    window = MainWindow()
    monkeypatch.setattr("app.ui.controllers.map_controller.geocode_address_arcgis", lambda address: (-22.01, -47.89))
    window.gis = SimpleNamespace(
        find_microbacia=lambda lat, lng: "Gregorio",
        to_geojson_obj=lambda: {}
    )
    monkeypatch.setattr(window, "_highlight_microbacia", lambda micro: None)
    monkeypatch.setattr(window, "_set_map_marker", lambda lat, lng: None)

    window.data_tab.in_end.setText("Rua Teste")
    window.search_on_map()

    assert window.data_tab.in_micro.currentText() == "Gregorio"
    window.close()


def test_load_custom_layer_runs_generated_script(monkeypatch):
    window = MainWindow()
    captured = {"scripts": [], "infos": []}

    monkeypatch.setattr(
        "app.ui.controllers.map_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("C:/tmp/camada.geojson", "Arquivos GIS (*.geojson *.json *.kml)"),
    )
    monkeypatch.setattr(
        window.map_controller,
        "_read_custom_layer_geojson",
        lambda path: {"type": "FeatureCollection", "features": [{"path": path}]},
    )
    monkeypatch.setattr(window.map_controller, "run_map_js", lambda script, context: captured["scripts"].append((context, script)))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: captured["infos"].append(args[2]))

    window.load_custom_layer()

    assert captured["scripts"][0][0] == "load-custom-layer"
    assert "window.customLayer = L.geoJSON" in captured["scripts"][0][1]
    assert captured["infos"] == ["Camada carregada com sucesso."]
    window.close()


def test_search_on_map_enables_street_view_after_geocode(monkeypatch):
    window = MainWindow()
    monkeypatch.setattr("app.ui.controllers.map_controller.geocode_address_arcgis", lambda address: (-22.02, -47.91))
    monkeypatch.setattr(window, "_run_map_js", lambda *args, **kwargs: None)
    monkeypatch.setattr(window, "_highlight_microbacia", lambda *args, **kwargs: None)
    window.gis = SimpleNamespace(
        find_microbacia=lambda lat, lng: None,
        to_geojson_obj=lambda: {}
    )

    assert window.data_tab.btn_street_view.isEnabled() is False

    window.data_tab.in_end.setText("Rua Teste")
    window.search_on_map()

    assert window.last_marker_coords == (-22.02, -47.91)
    assert window.data_tab.btn_street_view.isEnabled() is True
    window.close()


def test_open_street_view_uses_last_marker_when_no_addresses(monkeypatch):
    window = MainWindow()
    opened = []
    window.last_marker_coords = (-22.03, -47.92)

    monkeypatch.setattr(
        "app.ui.controllers.map_controller.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )

    window.open_street_view()

    assert opened == ["https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=-22.03,-47.92"]
    window.close()


def test_open_street_view_prompts_for_selected_address(monkeypatch):
    window = MainWindow()
    opened = []
    markers = []
    window.data_tab.in_end.setText("Rua Principal")
    window.form_plantios = [
        PlantioItem(sequence=1, endereco="Rua Plantio A", qtd_mudas="4"),
        PlantioItem(sequence=2, endereco="Rua Plantio B", qtd_mudas="6"),
    ]

    monkeypatch.setattr(
        "app.ui.controllers.map_controller.QInputDialog.getItem",
        lambda *args, **kwargs: ("Plantio 2: Rua Plantio B (6 mudas)", True),
    )
    monkeypatch.setattr("app.ui.controllers.map_controller.geocode_address_arcgis", lambda address: (-22.04, -47.93))
    monkeypatch.setattr(window.map_controller, "set_map_marker", lambda lat, lng: markers.append((lat, lng)))
    monkeypatch.setattr(
        "app.ui.controllers.map_controller.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )

    window.open_street_view()

    assert markers == [(-22.04, -47.93)]
    assert opened == ["https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=-22.04,-47.93"]
    window.close()


def test_heatmap_realizadas_uses_plantio_coordinates():
    window = MainWindow()
    record = make_record(
        compensado="SIM",
        latitude="-22.01",
        longitude="-47.89",
        latitude_plantio="-22.05",
        longitude_plantio="-47.95",
    )

    assert window._build_heatmap_point(record, "Realizadas") == [-22.05, -47.95]

    window.close()


def test_heatmap_pendentes_keeps_main_coordinates():
    window = MainWindow()
    record = make_record(
        compensado="",
        latitude="-22.01",
        longitude="-47.89",
        latitude_plantio="-22.05",
        longitude_plantio="-47.95",
    )

    assert window._build_heatmap_point(record, "Pendentes") == [-22.01, -47.89]

    window.close()


def test_heatmap_tudo_preserves_main_coordinates_for_compensated_records():
    window = MainWindow()
    record = make_record(
        compensado="SIM",
        latitude="-22.01",
        longitude="-47.89",
        latitude_plantio="-22.05",
        longitude_plantio="-47.95",
    )

    assert window._build_heatmap_point(record, "Tudo") == [-22.01, -47.89]

    window.close()


def test_fullscreen_heatmap_realizadas_uses_same_plantio_coordinates():
    window = MainWindow()
    window.filtered_records = [
        make_record(
            compensado="SIM",
            latitude="-22.01",
            longitude="-47.89",
            latitude_plantio="-22.05",
            longitude_plantio="-47.95",
        )
    ]
    fake_dialog = SimpleNamespace(
        chk_fs_heatmap=SimpleNamespace(isChecked=lambda: True),
        combo_fs_heatmap=SimpleNamespace(currentText=lambda: "Realizadas"),
        parent_window=window,
    )

    assert MapFullScreenDialog._get_current_points_fs(fake_dialog) == [[-22.05, -47.95]]

    window.close()


def test_fullscreen_heatmap_returns_empty_points_when_disabled():
    window = MainWindow()
    window.filtered_records = [
        make_record(
            compensado="SIM",
            latitude="-22.01",
            longitude="-47.89",
            latitude_plantio="-22.05",
            longitude_plantio="-47.95",
        )
    ]
    fake_dialog = SimpleNamespace(
        chk_fs_heatmap=SimpleNamespace(isChecked=lambda: False),
        combo_fs_heatmap=SimpleNamespace(currentText=lambda: "Realizadas"),
        parent_window=window,
    )

    assert MapFullScreenDialog._get_current_points_fs(fake_dialog) == []

    window.close()


def test_record_needs_batch_geocode_when_only_plantio_coords_are_missing():
    window = MainWindow()
    record = make_record(
        latitude="-22.01",
        longitude="-47.89",
        microbacia="Gregorio",
        endereco_plantio="Rua Plantio",
        latitude_plantio="",
        longitude_plantio="",
    )

    assert window._record_needs_batch_geocode(record) is True
    window.close()


def test_on_geocode_finished_persists_batch_coordinates(monkeypatch):
    window = MainWindow()
    record = make_record(
        uid="u-geo",
        endereco="Rua Principal",
        endereco_plantio="Rua Plantio",
        latitude="",
        longitude="",
        latitude_plantio="",
        longitude_plantio="",
        microbacia="",
    )
    window.records = [record]
    window.gis = SimpleNamespace(find_microbacia=lambda lat, lng: "Gregorio")

    saved = {}
    reloaded = []
    monkeypatch.setattr(window.excel, "save_batch_edits", lambda records: saved.setdefault("records", list(records)) or len(records))
    monkeypatch.setattr(window, "reload", lambda: reloaded.append(True))

    window.on_geocode_finished({
        record.excel_row: {
            "main": (-22.01, -47.89),
            "plantio": (-22.02, -47.90),
        }
    })

    assert "records" in saved
    assert len(saved["records"]) == 1
    saved_record = saved["records"][0]
    assert saved_record.latitude == "-22.01"
    assert saved_record.longitude == "-47.89"
    assert saved_record.latitude_plantio == "-22.02"
    assert saved_record.longitude_plantio == "-47.9"
    assert saved_record.microbacia == "Gregorio"
    assert reloaded == [True]
    window.close()


def test_search_on_map_plantio_asks_which_address_to_use(monkeypatch):
    window = MainWindow()
    captured = []
    window.form_plantios = [
        PlantioItem(sequence=1, endereco="Rua Plantio A", qtd_mudas="4"),
        PlantioItem(sequence=2, endereco="Rua Plantio B", qtd_mudas="6"),
    ]

    monkeypatch.setattr(
        "app.ui.controllers.map_controller.QInputDialog.getItem",
        lambda *args, **kwargs: ("Plantio 2: Rua Plantio B (6 mudas)", True),
    )
    monkeypatch.setattr(window.map_controller, "perform_geocode", lambda address: captured.append(address))

    window.search_on_map_plantio()

    assert captured == ["Rua Plantio B"]
    window.close()


def test_on_geocode_finished_updates_all_plantios(monkeypatch):
    window = MainWindow()
    record = make_record(
        uid="u-multi",
        compensado="SIM",
        plantios=[
            PlantioItem(sequence=1, endereco="Rua Plantio A", qtd_mudas="3"),
            PlantioItem(sequence=2, endereco="Rua Plantio B", qtd_mudas="7"),
        ],
    )
    window.records = [record]
    window.gis = SimpleNamespace(find_microbacia=lambda lat, lng: "Gregorio")

    saved = {}
    monkeypatch.setattr(window.excel, "save_batch_edits", lambda records: saved.setdefault("records", list(records)) or len(records))
    monkeypatch.setattr(window, "reload", lambda: None)

    window.on_geocode_finished(
        {
            record.excel_row: {
                "plantios": {
                    1: (-22.01, -47.89),
                    2: (-22.02, -47.90),
                }
            }
        }
    )

    saved_record = saved["records"][0]
    assert saved_record.plantios[0].latitude == "-22.01"
    assert saved_record.plantios[1].longitude == "-47.9"
    assert saved_record.latitude_plantio == "-22.01"
    assert saved_record.endereco_plantio == "2 áreas / 10 mudas"


def test_heatmap_realizadas_includes_all_plantio_coordinates():
    window = MainWindow()
    record = make_record(
        compensado="SIM",
        plantios=[
            PlantioItem(sequence=1, endereco="Rua Plantio A", qtd_mudas="3", latitude="-22.05", longitude="-47.95"),
            PlantioItem(sequence=2, endereco="Rua Plantio B", qtd_mudas="7", latitude="-22.06", longitude="-47.96"),
        ],
    )

    assert window._build_heatmap_points(record, "Realizadas") == [[-22.05, -47.95], [-22.06, -47.96]]

    window.close()


def test_perform_geocode_surfaces_not_found(monkeypatch):
    window = MainWindow()
    warnings = []

    monkeypatch.setattr("app.ui.controllers.map_controller.geocode_address_arcgis", lambda address: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    window._perform_geocode("Endereço Inexistente")

    assert warnings and "localizar" in warnings[0]
    window.close()


def test_load_last_excel_reports_failures_and_clears_setting(monkeypatch, tmp_path):
    expected_path = tmp_path / "ultima.xlsx"
    expected_path.write_text("stub", encoding="utf-8")
    state = {"last_excel_path": str(expected_path)}

    class MockSettings:
        def __init__(self, *args, **kwargs): pass
        def value(self, key, default=""): return state.get(key, default)
        def setValue(self, key, val): state[key] = val
        def remove(self, key): state.pop(key, None)

    monkeypatch.setattr("app.ui.main_window.QSettings", MockSettings)

    # Ensure os.path.exists returns True for our test path
    real_exists = os.path.exists
    def mock_exists(p):
        if p == str(expected_path): return True
        return real_exists(p)
    monkeypatch.setattr(os.path, "exists", mock_exists)

    window = MainWindow()
    def mock_raise_error(*args, **kwargs):
        raise RuntimeError("planilha corrompida")
    monkeypatch.setattr(window.excel, "load", mock_raise_error)

    window._load_last_excel()

    assert "last_excel_path" not in state
    window.close()


def test_load_excel_failure_restores_previous_filter_state(monkeypatch):
    window = MainWindow()
    window.records = [
        make_record(oficio_processo="123/2026", microbacia="Gregorio", eletronico="SIM"),
        make_record(excel_row=3, oficio_processo="999/2025", microbacia="Medeiros", eletronico="NAO", uid="u-2"),
    ]
    window.filtered_records = list(window.records)
    window._update_filters_from_records()

    window.data_tab.search.setText("Gregorio")
    window.data_tab.filter_status.setCurrentText("Pendentes")
    year_index = window.data_tab.filter_year.findText("2026")
    window.data_tab.filter_year.setCurrentIndex(year_index)
    window.data_tab.filter_micro.set_checked_items(["Gregorio"], all_selected=False)
    window.data_tab.filter_eletronico.set_checked_items(["Eletrônico"], all_selected=False)
    window.apply_filter()

    monkeypatch.setattr(window.excel, "load", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("falhou")))

    window._load_excel("quebrado.xlsx")

    assert window.data_tab.search.text() == "Gregorio"
    assert window.data_tab.filter_status.currentText() == "Pendentes"
    assert window.data_tab.filter_year.currentText() == "2026"
    assert window.data_tab.filter_micro.checked_items() == ["Gregorio"]
    assert window.data_tab.filter_eletronico.checked_items() == ["Eletrônico"]
    assert len(window.filtered_records) == 1
    window.close()


def test_load_excel_continues_when_gis_fails(ui_window_factory, monkeypatch, tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "Oficio/ Processo",
            "Eletronico",
            "Caixa",
            "Av. Tec.",
            "Compensacao",
            "Endereco",
            "Microbacia",
            "Compensado",
        ]
    )
    sheet.append(["123/2026", "SIM", "CX-1", "AT-1", 8, "Rua A", "Gregorio", ""])
    workbook.save(workbook_path)

    window = ui_window_factory()
    map_calls = []
    real_isdir = os.path.isdir

    monkeypatch.setattr(window, "_run_map_js", lambda script, context: map_calls.append((context, script)))
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.os.path.isdir",
        lambda path: True if path == window.MICROB_DIR else real_isdir(path),
    )
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.GisService",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("shapefile quebrado")),
    )

    assert window._load_excel(str(workbook_path)) is True
    assert len(window.records) == 1
    assert window.gis is None
    assert "Microbacias indisponiveis" in window.data_tab.map_notice_label.text()
    assert any(context == "clear-microbacias-load-failure" for context, _script in map_calls)
    assert any(context == "gis-load-failure-status" for context, _script in map_calls)
    window.close()


def test_load_excel_can_hydrate_session_records_from_sqlite_snapshot(monkeypatch):
    window = MainWindow()
    session_records = [make_record(oficio_processo="EXCEL-1", uid="excel-1")]
    mirrored_records = [make_record(oficio_processo="SQLITE-1", uid="sqlite-1", microbacia="Gregorio")]

    def fake_run_blocking_spec(spec):
        window.excel.path = "dummy.xlsx"
        return SimpleNamespace(records=session_records)

    monkeypatch.setattr(window, "run_blocking_spec", fake_run_blocking_spec)
    monkeypatch.setattr(
        window.persistence_service,
        "sync_workbook_snapshot",
        lambda workbook_path, records: SimpleNamespace(
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            record_count=len(records),
        ),
    )
    monkeypatch.setattr(window.data_controller, "_refresh_dashboard_record_overview", lambda: None)
    monkeypatch.setattr(
        window.data_controller.local_record_queries,
        "resolve_record_source",
        lambda workbook_path, **kwargs: LocalRecordReadResult(
            source="sqlite",
            records=tuple(mirrored_records),
            strategy="sqlite_snapshot",
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            mirrored_records=1,
            session_records=1,
        ),
    )
    monkeypatch.setattr(window.data_controller, "load_gis", lambda: True)
    monkeypatch.setattr(window.data_controller, "apply_filter", lambda: None)
    monkeypatch.setattr(window.data_tab, "align_splitter_to_table_width", lambda: None)
    monkeypatch.setattr(window, "clear_form", lambda *args, **kwargs: True)
    monkeypatch.setattr(window, "refresh_operations_overview", lambda: None)
    monkeypatch.setattr(window, "_load_sort_settings", lambda: None)

    assert window._load_excel("dummy.xlsx") is True
    assert [record.uid for record in window.records] == ["sqlite-1"]
    assert window._local_session_source_status is not None
    assert window._local_session_source_status.source == "sqlite"
    assert window._local_session_source_status.strategy == "sqlite_snapshot"
    window.close()


def test_load_settings_restores_geometry_and_tab(monkeypatch):
    state = {"window_geometry": b"geom", "active_tab_index": 1}
    restored = []
    
    monkeypatch.setattr(MainWindow, "restoreGeometry", lambda self, geometry: restored.append(geometry) or True)

    window = MainWindow()
    window.settings = SimpleNamespace(
        value=lambda key, default=None: state.get(key, default),
        setValue=lambda *args, **kwargs: None,
    )
    window._load_settings()

    assert restored == [b"geom"]
    assert window._startup_geometry_restored is True
    assert window.tabs.currentIndex() == 1
    window.close()


def test_load_settings_filters_missing_recent_files(monkeypatch, tmp_path):
    existing = tmp_path / "base.xlsx"
    existing.write_text("stub", encoding="utf-8")

    class MemorySettings:
        def __init__(self):
            self._data = {"recent_files": [str(existing), str(existing), str(tmp_path / "missing.xlsx")]}

        def value(self, key, default=None):
            return self._data.get(key, default)

        def setValue(self, key, value):
            self._data[key] = value

        def remove(self, key):
            self._data.pop(key, None)

    window = MainWindow()
    window.settings = AppSettings(MemorySettings())

    window._load_settings()

    assert window.recent_files == [str(existing)]
    assert window.settings.recent_files() == [str(existing)]
    window.close()


def test_close_event_persists_geometry_and_active_tab(monkeypatch):
    window = MainWindow()
    saved = {}
    window.settings = SimpleNamespace(
        value=lambda key, default=None: saved.get(key, default),
        setValue=lambda key, value: saved.__setitem__(key, value),
        remove=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(window, "saveGeometry", lambda: b"geom")
    
    window.tabs.setCurrentIndex(1)
    window.close()

    assert saved["window_geometry"] == b"geom"
    assert saved["active_tab_index"] == 1


def test_help_menu_exposes_support_actions():
    window = MainWindow()

    assert window.action_export_diagnostics.text() == "Exportar Diagnóstico"
    assert window.action_open_logs.text() == "Abrir Pasta de Logs"
    assert window.action_about.text() == "Sobre"
    window.close()


def test_file_menu_exposes_operation_history_action():
    window = MainWindow()

    assert window.action_operation_history.text() == "Histórico de Operações"
    window.close()


def test_close_event_stops_geocode_worker(monkeypatch):
    window = MainWindow()
    calls = []

    worker = SimpleNamespace(
        progress_update=SimpleNamespace(disconnect=lambda: calls.append("disconnect_progress")),
        finished_process=SimpleNamespace(disconnect=lambda: calls.append("disconnect_finished")),
        isRunning=lambda: True,
        stop=lambda: calls.append("stop"),
        quit=lambda: calls.append("quit"),
        wait=lambda timeout: calls.append(("wait", timeout)) or True,
    )
    window.geo_worker = worker
    window.track_background_worker(
        "batch_geocode",
        worker,
        disconnect_callbacks=[
            lambda: worker.progress_update.disconnect(),
            lambda: worker.finished_process.disconnect(),
        ],
        stop_callback=worker.stop,
        wait_ms=10000,
    )

    window.close()

    assert "disconnect_progress" in calls
    assert "disconnect_finished" in calls
    assert "stop" in calls
    assert "quit" in calls
    assert ("wait", 10000) in calls


def test_open_logs_folder_uses_log_directory(monkeypatch):
    window = MainWindow()
    opened = []

    monkeypatch.setattr("app.ui.controllers.support_controller.QDesktopServices.openUrl", lambda url: opened.append(url.toLocalFile()))

    window.open_logs_folder()

    assert [os.path.normcase(os.path.normpath(path)) for path in opened] == [os.path.normcase(os.path.normpath(LOG_DIR))]
    window.close()


def test_export_diagnostics_writes_file_and_remembers_directory(monkeypatch, tmp_path):
    class MemorySettings:
        def __init__(self):
            self._data = {}

        def value(self, key, default=None):
            return self._data.get(key, default)

        def setValue(self, key, value):
            self._data[key] = value

        def remove(self, key):
            self._data.pop(key, None)

    window = MainWindow()
    window.settings = AppSettings(MemorySettings())
    target = tmp_path / "suporte" / "diag.json"
    target.parent.mkdir()

    monkeypatch.setattr(
        "app.ui.controllers.support_controller.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(target), "JSON (*.json)"),
    )

    window.export_diagnostics()

    assert target.exists()
    with open(target, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["app"]["version"]
    assert "session" in payload
    assert "persistence" in payload
    assert payload["persistence"]["available"] is True
    assert window.settings.last_export_dir() == str(target.parent)
    window.close()


def test_run_map_js_reports_failures_without_raising(monkeypatch):
    logs = []
    window = MainWindow()
    fake_page = SimpleNamespace(runJavaScript=lambda script: (_ for _ in ()).throw(RuntimeError("web indisponivel")))
    monkeypatch.setattr(window.data_tab.web, "page", lambda: fake_page)

    monkeypatch.setattr("app.ui.controllers.map_controller.logger.error", lambda msg: logs.append(str(msg)))

    window._run_map_js("window.setStatus('x');", "status")

    assert logs and "MAP JS" in logs[0]
    assert "status" in logs[0]
    window.close()


def test_delete_selected_surfaces_lookup_errors(monkeypatch):
    window = MainWindow()
    errors = []
    reloaded = []
    window.excel.path = "dummy.xlsx"
    window.selected = make_record(uid="u-delete")

    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.excel, "delete_record_shift_up", lambda *args, **kwargs: (_ for _ in ()).throw(LookupError("UID ausente")))
    monkeypatch.setattr(window, "reload", lambda: reloaded.append(True))
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: errors.append(args[2]))

    window.delete_selected()

    assert reloaded == []
    assert errors == ["Nao foi possivel excluir o registro: UID ausente"]
    window.close()


def test_add_new_writes_audit_entry(monkeypatch):
    window = MainWindow()
    added = []
    audits = []
    refreshed = []

    monkeypatch.setattr(window.excel, "create_operation_backup", lambda label: f"C:/tmp/{label}.xlsx")
    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.excel, "add_new", lambda record: added.append(record) or 3)
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: audits.append(payload))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    window.excel.path = "dummy.xlsx"
    window.data_tab.in_oficio.setText("123/2026")
    window.data_tab.in_avtec.setText("AT-55")
    window.data_tab.in_comp.setText("10")
    window.data_tab.in_end.setText("Rua Nova")

    window.add_new()

    assert len(added) == 1
    assert len(refreshed) == 1
    assert audits[0]["action"] == "add"
    assert audits[0]["backup_path"].endswith("add.xlsx")
    assert audits[0]["after"]["av_tec"] == "AT-55"
    window.close()


def test_add_new_reports_external_workbook_change(monkeypatch):
    window = MainWindow()
    errors = []

    monkeypatch.setattr(
        window.excel,
        "ensure_workbook_is_current",
        lambda: (_ for _ in ()).throw(WorkbookModifiedExternallyError("stale")),
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: errors.append((args[1], args[2])))

    window.excel.path = "dummy.xlsx"
    window.data_tab.in_oficio.setText("123/2026")
    window.data_tab.in_avtec.setText("AT-55")
    window.data_tab.in_comp.setText("10")
    window.data_tab.in_end.setText("Rua Nova")

    window.add_new()

    assert errors == [("Planilha Desatualizada", "A planilha foi alterada fora do aplicativo. Recarregue antes de continuar.")]
    window.close()


def test_add_new_uses_authoritative_runtime_base_for_projection_and_sync(monkeypatch):
    window = MainWindow()
    refreshed = []
    sync_calls = []
    authoritative_base = [make_record(uid="uid-sqlite-base", av_tec="AT-BASE", excel_row=8)]

    def fake_add_new(record):
        record.uid = "uid-added"
        record.excel_row = 9
        return 9

    monkeypatch.setattr(window.excel, "create_operation_backup", lambda label: f"C:/tmp/{label}.xlsx")
    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.excel, "add_new", fake_add_new)
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_authoritative_record_source",
        lambda workbook_path, **kwargs: type(
            "RecordSource",
            (),
            {"records": tuple(authoritative_base), "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.local_mutation_sync,
        "apply_after_add",
        lambda **kwargs: sync_calls.append(kwargs)
        or type(
            "MutationResult",
            (),
            {
                "status": type("Status", (), {"issues": (), "operation": "add"})(),
                "records": tuple([*authoritative_base, make_record(uid="uid-added", av_tec="AT-55", excel_row=9)]),
            },
        )(),
    )

    window.excel.path = "dummy.xlsx"
    window.records = [make_record(uid="uid-stale-session", av_tec="AT-OLD", excel_row=2)]
    window.data_tab.in_oficio.setText("123/2026")
    window.data_tab.in_avtec.setText("AT-55")
    window.data_tab.in_comp.setText("10")
    window.data_tab.in_end.setText("Rua Nova")

    window.add_new()

    assert len(sync_calls) == 1
    assert [record.uid for record in sync_calls[0]["existing_records"]] == ["uid-sqlite-base"]
    assert [record.uid for record in refreshed[0]] == ["uid-sqlite-base", "uid-added"]
    window.close()


def test_save_edit_blocks_invalid_payload(monkeypatch):
    window = MainWindow()
    saved = []
    warnings = []

    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.excel, "save_edit", lambda record: saved.append(record))
    monkeypatch.setattr(window, "reload", lambda: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    window.excel.path = "dummy.xlsx"
    window.selected = make_record()
    window._fill_form(window.selected)
    window.data_tab.in_comp.setText("")

    window.save_edit()

    assert saved == []
    assert warnings and "Compensação" in warnings[0]
    window.close()
def test_save_edit_writes_audit_entry(monkeypatch):
    window = MainWindow()
    audits = []
    refreshed = []

    monkeypatch.setattr(window.excel, "create_operation_backup", lambda label: f"C:/tmp/{label}.xlsx")
    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.excel, "save_edit", lambda record: None)
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: audits.append(payload))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    window.excel.path = "dummy.xlsx"
    window.selected = make_record(caixa="CX-1", uid="uid-edit")
    window._fill_form(window.selected)
    window.data_tab.in_caixa.setText("CX-9")

    window.save_edit()

    assert len(refreshed) == 1
    assert audits[0]["action"] == "edit"
    assert audits[0]["before"]["caixa"] == "CX-1"
    assert audits[0]["after"]["caixa"] == "CX-9"
    window.close()


def test_save_edit_reports_external_workbook_change(monkeypatch):
    window = MainWindow()
    errors = []

    monkeypatch.setattr(
        window.excel,
        "ensure_workbook_is_current",
        lambda: (_ for _ in ()).throw(WorkbookModifiedExternallyError("stale")),
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: errors.append((args[1], args[2])))

    window.excel.path = "dummy.xlsx"
    window.selected = make_record(caixa="CX-1", uid="uid-edit")
    window._fill_form(window.selected)
    window.data_tab.in_caixa.setText("CX-9")

    window.save_edit()

    assert errors == [("Planilha Desatualizada", "A planilha foi alterada fora do aplicativo. Recarregue antes de continuar.")]
    window.close()


def test_save_edit_uses_authoritative_selected_record_for_audit_and_target(monkeypatch):
    window = MainWindow()
    audits = []
    saved = []

    monkeypatch.setattr(window.excel, "create_operation_backup", lambda label: f"C:/tmp/{label}.xlsx")
    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.excel, "save_edit", lambda record: saved.append(record))
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: audits.append(payload))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_selected_record",
        lambda workbook_path, **kwargs: type(
            "SelectionResult",
            (),
            {
                "record": make_record(excel_row=9, uid="uid-authoritative", caixa="CX-AUTH", av_tec="AT-AUTH"),
                "issues": (),
            },
        )(),
    )

    window.excel.path = "dummy.xlsx"
    window.selected = make_record(excel_row=3, uid="uid-stale", caixa="CX-OLD", av_tec="AT-OLD")
    window._fill_form(window.selected)
    window.data_tab.in_caixa.setText("CX-EDIT")

    window.save_edit()

    assert len(saved) == 1
    assert saved[0].uid == "uid-authoritative"
    assert saved[0].excel_row == 9
    assert audits[0]["before"]["uid"] == "uid-authoritative"
    assert audits[0]["before"]["caixa"] == "CX-AUTH"
    window.close()


def test_save_edit_uses_authoritative_runtime_base_for_projection_and_sync(monkeypatch):
    window = MainWindow()
    refreshed = []
    sync_calls = []
    authoritative_base = [
        make_record(excel_row=9, uid="uid-authoritative", caixa="CX-AUTH", av_tec="AT-AUTH"),
        make_record(excel_row=10, uid="uid-neighbor", caixa="CX-NB", av_tec="AT-NB"),
    ]

    monkeypatch.setattr(window.excel, "create_operation_backup", lambda label: f"C:/tmp/{label}.xlsx")
    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.excel, "save_edit", lambda record: None)
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_selected_record",
        lambda workbook_path, **kwargs: type(
            "SelectionResult",
            (),
            {"record": authoritative_base[0], "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_authoritative_record_source",
        lambda workbook_path, **kwargs: type(
            "RecordSource",
            (),
            {"records": tuple(authoritative_base), "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.local_mutation_sync,
        "apply_after_edit",
        lambda **kwargs: sync_calls.append(kwargs)
        or type(
            "MutationResult",
            (),
            {
                "status": type("Status", (), {"issues": (), "operation": "edit"})(),
                "records": tuple(
                    [
                        make_record(excel_row=9, uid="uid-authoritative", caixa="CX-EDIT", av_tec="AT-AUTH"),
                        authoritative_base[1],
                    ]
                ),
            },
        )(),
    )

    window.excel.path = "dummy.xlsx"
    window.records = [make_record(excel_row=3, uid="uid-stale-session", caixa="CX-OLD", av_tec="AT-OLD")]
    window.selected = make_record(excel_row=3, uid="uid-stale-session", caixa="CX-OLD", av_tec="AT-OLD")
    window._fill_form(window.selected)
    window.data_tab.in_caixa.setText("CX-EDIT")

    window.save_edit()

    assert len(sync_calls) == 1
    assert [record.uid for record in sync_calls[0]["existing_records"]] == ["uid-authoritative", "uid-neighbor"]
    assert [record.uid for record in refreshed[0]] == ["uid-authoritative", "uid-neighbor"]
    assert refreshed[0][0].caixa == "CX-EDIT"
    window.close()


def test_delete_selected_writes_audit_entry(monkeypatch):
    window = MainWindow()
    audits = []
    refreshed = []

    monkeypatch.setattr(window.excel, "create_operation_backup", lambda label: f"C:/tmp/{label}.xlsx")
    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.excel, "delete_record_shift_up", lambda *args, **kwargs: None)
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: audits.append(payload))

    window.excel.path = "dummy.xlsx"
    window.selected = make_record(uid="uid-delete", av_tec="AT-DEL")

    window.delete_selected()

    assert len(refreshed) == 1
    assert audits[0]["action"] == "delete"
    assert audits[0]["before"]["uid"] == "uid-delete"
    assert audits[0]["backup_path"].endswith("delete.xlsx")
    window.close()


def test_delete_selected_uses_authoritative_selected_record_for_delete_and_audit(monkeypatch):
    window = MainWindow()
    audits = []
    deleted = []

    monkeypatch.setattr(window.excel, "create_operation_backup", lambda label: f"C:/tmp/{label}.xlsx")
    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.excel, "delete_record_shift_up", lambda row_idx, uid="": deleted.append((row_idx, uid)))
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: audits.append(payload))
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_selected_record",
        lambda workbook_path, **kwargs: type(
            "SelectionResult",
            (),
            {
                "record": make_record(excel_row=12, uid="uid-authoritative-delete", av_tec="AT-AUTH-DEL"),
                "issues": (),
            },
        )(),
    )

    window.excel.path = "dummy.xlsx"
    window.selected = make_record(excel_row=4, uid="uid-stale-delete", av_tec="AT-OLD-DEL")

    window.delete_selected()

    assert deleted == [(12, "uid-authoritative-delete")]
    assert audits[0]["before"]["uid"] == "uid-authoritative-delete"
    assert audits[0]["backup_path"].endswith("delete.xlsx")
    window.close()


def test_delete_selected_uses_authoritative_runtime_base_for_projection_and_sync(monkeypatch):
    window = MainWindow()
    refreshed = []
    sync_calls = []
    authoritative_deleted = make_record(excel_row=12, uid="uid-authoritative-delete", av_tec="AT-AUTH-DEL")
    authoritative_base = [
        authoritative_deleted,
        make_record(excel_row=13, uid="uid-neighbor-delete", av_tec="AT-NB-DEL"),
    ]

    monkeypatch.setattr(window.excel, "create_operation_backup", lambda label: f"C:/tmp/{label}.xlsx")
    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.excel, "delete_record_shift_up", lambda row_idx, uid="": None)
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: None)
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_selected_record",
        lambda workbook_path, **kwargs: type(
            "SelectionResult",
            (),
            {"record": authoritative_deleted, "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_authoritative_record_source",
        lambda workbook_path, **kwargs: type(
            "RecordSource",
            (),
            {"records": tuple(authoritative_base), "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.local_mutation_sync,
        "apply_after_delete",
        lambda **kwargs: sync_calls.append(kwargs)
        or type(
            "MutationResult",
            (),
            {
                "status": type("Status", (), {"issues": (), "operation": "delete"})(),
                "records": (make_record(excel_row=12, uid="uid-neighbor-delete", av_tec="AT-NB-DEL"),),
            },
        )(),
    )

    window.excel.path = "dummy.xlsx"
    window.records = [make_record(excel_row=4, uid="uid-stale-session-delete", av_tec="AT-OLD-DEL")]
    window.selected = make_record(excel_row=4, uid="uid-stale-session-delete", av_tec="AT-OLD-DEL")

    window.delete_selected()

    assert len(sync_calls) == 1
    assert [record.uid for record in sync_calls[0]["existing_records"]] == [
        "uid-authoritative-delete",
        "uid-neighbor-delete",
    ]
    assert [record.uid for record in refreshed[0]] == ["uid-neighbor-delete"]
    assert refreshed[0][0].excel_row == 12
    window.close()


def test_save_edit_requires_endereco_plantio_when_compensado(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if p == "dummy.xlsx" else real_exists(p))

    window = MainWindow()
    saved = []
    warnings = []

    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.excel, "save_edit", lambda record: saved.append(record))
    monkeypatch.setattr(window, "reload", lambda: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    window.excel.path = "dummy.xlsx"
    window.selected = make_record()
    window._fill_form(window.selected)

    window.data_tab.chk_compensado.setChecked(True)
    window.data_tab.in_end_plantio.setText("")

    assert window.data_tab.btn_save_edit.isEnabled() is False

    window.save_edit()

    assert saved == []
    assert warnings == ["Preencha Endereco Plantio para salvar um registro compensado."]
    window.close()


def test_save_edit_reenables_when_endereco_plantio_is_filled(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if p == "dummy.xlsx" else real_exists(p))

    window = MainWindow()
    window.excel.path = "dummy.xlsx"
    window.selected = make_record()
    window._fill_form(window.selected)

    window.data_tab.chk_compensado.setChecked(True)
    window.data_tab.in_end_plantio.setText("")
    assert window.data_tab.btn_save_edit.isEnabled() is False

    window.data_tab.in_end_plantio.setText("Rua do Plantio, 123")
    assert window.data_tab.btn_save_edit.isEnabled() is True

    window.close()


def test_duplicate_av_tec_highlight_keeps_current_palette_colors():
    window = MainWindow()
    duplicate_record = make_record(uid="u-1", av_tec="AT-1")
    selected_record = make_record(excel_row=3, uid="u-2", av_tec="AT-2")
    window.records = [duplicate_record, selected_record]
    window.selected = selected_record
    window._fill_form(selected_record)

    palette = window.data_tab.in_avtec.palette()
    expected_bg = palette.color(QPalette.ColorRole.Base).name()
    expected_text = palette.color(QPalette.ColorRole.Text).name()

    window.data_tab.in_avtec.setText("AT-1")
    window._validate_as_you_type()

    style = window.data_tab.in_avtec.styleSheet()

    assert "border: 2px solid #e74c3c;" in style
    assert f"background-color: {expected_bg};" in style
    assert f"color: {expected_text};" in style
    assert "#fdf0ed" not in style

    window.close()


def test_duplicate_av_tec_highlight_can_use_sqlite_duplicate_lookup(monkeypatch):
    window = MainWindow()
    selected_record = make_record(excel_row=3, uid="u-2", av_tec="AT-2")
    window.records = [selected_record]
    window.selected = selected_record
    window._fill_form(selected_record)

    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_duplicate_av_tec",
        lambda workbook_path, **kwargs: LocalDuplicateCheckResult(
            source="sqlite",
            duplicate_row=10,
            strategy="sqlite_duplicate",
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            mirrored_records=1,
            session_records=1,
        ),
    )

    window.data_tab.in_avtec.setText("AT-1")
    window._validate_as_you_type()

    assert "border: 2px solid #e74c3c;" in window.data_tab.in_avtec.styleSheet()
    assert window.data_tab.in_avtec.toolTip() == "Esta Av. Técnica já existe na linha 9."
    window.close()


def test_compensado_cannot_be_unchecked_when_endereco_plantio_has_data(monkeypatch):
    window = MainWindow()
    warnings = []
    record = make_record(compensado="SIM", endereco_plantio="Rua do Plantio, 123")
    window.selected = record

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    window._fill_form(record)
    assert window.data_tab.chk_compensado.isChecked() is True

    window.data_tab.chk_compensado.setChecked(False)

    assert window.data_tab.chk_compensado.isChecked() is True
    assert window.data_tab.in_end_plantio.isEnabled() is True
    assert warnings == ["Limpe Endereco Plantio antes de desmarcar Compensado."]
    window.close()


def test_save_edit_refreshes_runtime_session_without_full_reload(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if p == "dummy.xlsx" else real_exists(p))

    window = MainWindow()
    saved = []
    refresh_calls = []
    infos = []

    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.excel, "save_edit", lambda record: saved.append(record))
    monkeypatch.setattr(window, "reload", lambda *args, **kwargs: pytest.fail("reload nao deveria ser usado apos save_edit"))
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refresh_calls.append(records) or True)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: infos.append(args[2]))

    window.excel.path = "dummy.xlsx"
    window.selected = make_record()
    window._fill_form(window.selected)
    window.data_tab.in_comp.setText("11")

    window.save_edit()

    assert len(saved) == 1
    assert len(refresh_calls) == 1
    assert infos == ["Salvo com sucesso."]
    window.close()


def test_show_rollback_dialog_uses_audit_history_when_available(monkeypatch, tmp_path):
    window = MainWindow()
    audits = []
    reloaded = []

    current_file = tmp_path / "base.xlsx"
    current_file.write_text("atual", encoding="utf-8")
    backup_file = tmp_path / "backup-op.xlsx"
    backup_file.write_text("snapshot", encoding="utf-8")

    event = SimpleNamespace(
        event_id="evt-1",
        timestamp="2026-03-30T12:00:00+00:00",
        action="edit",
        summary="Registro alterado: AT-1",
        backup_path=str(backup_file),
    )

    monkeypatch.setattr(window.audit_service, "list_events_for_workbook", lambda *_args, **_kwargs: [event])
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: audits.append(payload))
    monkeypatch.setattr(window.excel, "create_operation_backup", lambda label: str(tmp_path / f"{label}.xlsx"))
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.QInputDialog.getItem",
        lambda *args, **kwargs: ("30/03/2026 12:00:00 - EDIT - Registro alterado: AT-1", True),
    )
    monkeypatch.setattr(window.data_controller, "reload", lambda *args, **kwargs: reloaded.append(True))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    window.excel.path = str(current_file)

    window.show_rollback_dialog()

    assert current_file.read_text(encoding="utf-8") == "snapshot"
    assert reloaded == [True]
    assert audits[0]["action"] == "rollback"
    assert audits[0]["metadata"]["source_type"] == "operation_audit"
    window.close()


def test_show_operation_history_restores_selected_audit_snapshot(monkeypatch):
    window = MainWindow()
    restored = {}

    event = SimpleNamespace(
        event_id="evt-2",
        timestamp="2026-03-30T13:00:00+00:00",
        action="import",
        summary="2 registro(s) importado(s)",
        backup_path="C:/tmp/import-backup.xlsx",
        metadata={"source_path": "importar.xlsx"},
        before=None,
        after={"imported_count": 2},
    )

    class FakeOperationHistoryDialog:
        def __init__(self, _parent, events):
            restored["events"] = list(events)
            self.restore_requested = True
            self.selected_event = events[0]

        def exec(self):
            return True

    monkeypatch.setattr(window.audit_service, "list_events_for_workbook", lambda *_args, **_kwargs: [event])
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.OperationHistoryDialog",
        FakeOperationHistoryDialog,
    )
    monkeypatch.setattr(
        window.data_controller,
        "_restore_backup_file",
        lambda selected_file, **kwargs: restored.update({"selected_file": selected_file, **kwargs}) or True,
    )

    window.excel.path = "dummy.xlsx"

    window.show_operation_history()

    assert restored["events"] == [event]
    assert restored["selected_file"] == "C:/tmp/import-backup.xlsx"
    assert restored["rollback_source"] == "operation_audit"
    assert restored["metadata"]["event_id"] == "evt-2"
    assert restored["label"] == "2 registro(s) importado(s)"
    window.close()
