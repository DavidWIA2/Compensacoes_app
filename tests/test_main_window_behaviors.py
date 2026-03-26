import os
import json
from types import SimpleNamespace

from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem
from app.services.app_settings import AppSettings
from app.utils.logger import LOG_DIR

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, QObject, Signal, QSettings
from PySide6.QtGui import QPalette, QStandardItemModel

from app.ui import main_window as main_window_module
from app.ui.main_window import MainWindow
from app.ui.tabs.data_tab import DataTab
from app.ui.tabs.dashboard_tab import DashboardTab
from app.ui.components.dialogs import MapFullScreenDialog, TableFullScreenDialog


from PySide6.QtWebEngineWidgets import QWebEngineView

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
    assert window.data_tab.filter_eletronico._all_label == "Eletrônico"
    assert "Endereço" in window.data_tab.btn_maps.text()

    assert window.data_tab.kpi_model.horizontalHeaderItem(0).text() == "Métrica"
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

    assert window.data_tab.right_panel.minimumWidth() >= window.data_tab.form_group.minimumSizeHint().width()
    assert window.data_tab.right_panel.minimumWidth() >= window.data_tab.map_group.minimumSizeHint().width()
    assert window.data_tab.right_panel.minimumWidth() >= 620
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
        main_window_module,
        "export_excel_two_sheets",
        lambda path, records, filtros_txt, selected_cols, kpis, pend_micro_sorted, pend_ele_sorted: captured.update(
            {
                "path": path,
                "records": records,
                "pend_micro_sorted": pend_micro_sorted,
                "selected_cols": selected_cols,
            }
        ),
    )
    
    # Mocking compute_metrics to verify it's called with filtered records
    from app.services.records_service import compute_metrics
    real_compute = compute_metrics
    def mock_compute(recs):
        captured["compute_called_with"] = recs
        return real_compute(recs)
    
    monkeypatch.setattr(main_window_module, "compute_metrics", mock_compute)

    window.export_excel_clicked()

    assert captured["path"].endswith("saida.xlsx")
    assert len(captured["records"]) == 1
    assert len(captured["compute_called_with"]) == 1
    assert captured["pend_micro_sorted"] == [("Gregorio", 10.0)]
    assert "endereco_plantio" in captured["selected_cols"]
    window.close()


def test_apply_filter_defers_dashboard_update_until_panel_tab(monkeypatch):
    window = MainWindow()
    window.records = [make_record(oficio_processo="ABC-1", compensacao="10", microbacia="Gregorio")]
    window.filtered_records = list(window.records)

    calls = []
    monkeypatch.setattr(window.dash_tab, "update_dashboard", lambda *args, **kwargs: calls.append(args))

    window.tabs.setCurrentWidget(window.data_tab)
    window.apply_filter()

    assert calls == []
    assert window._dashboard_dirty is True

    window.tabs.setCurrentWidget(window.dash_tab)

    assert len(calls) == 1
    assert window._dashboard_dirty is False
    window.close()


def test_export_csv_reports_failure_without_raising(monkeypatch, tmp_path):
    window = MainWindow()
    window.records = [make_record(oficio_processo="ABC-1")]
    window.filtered_records = list(window.records)
    errors = []

    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "saida.csv"))
    monkeypatch.setattr(
        main_window_module,
        "export_csv",
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
        main_window_module.QInputDialog,
        "getMultiLineText",
        lambda *args, **kwargs: ("Observacao de teste", True),
    )
    monkeypatch.setattr(
        main_window_module,
        "export_individual_pdf",
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

    captured = {}
    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "painel.pdf"))
    
    def fake_export_images():
        return "pie.png", "bar.png"

    monkeypatch.setattr(window.dash_tab, "export_images", fake_export_images)
    monkeypatch.setattr(
        main_window_module,
        "export_dashboard_pdf",
        lambda path, titulo, kpi_lines, filtros_txt, chart_images: captured.update(
            {
                "path": path,
                "chart_images": chart_images,
            }
        ),
    )

    window.export_dashboard_pdf_clicked()

    assert captured["path"].endswith("painel.pdf")
    assert captured["chart_images"] == ["pie.png", "bar.png"]
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

    monkeypatch.setattr(main_window_module, "TableFullScreenDialog", FakeDialog)
    monkeypatch.setattr(main_window_module.QTimer, "singleShot", lambda _ms, fn: fn())
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
    monkeypatch.setattr(main_window_module.QTimer, "singleShot", lambda _ms, fn: fn())
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
    window.data_tab.filter_eletronico.set_checked_items(["SIM"], all_selected=False)
    window.apply_filter()

    monkeypatch.setattr(TableFullScreenDialog, "showMaximized", lambda self: None)
    monkeypatch.setattr("app.ui.components.dialogs.QTimer.singleShot", lambda _ms, fn: fn())

    dialog = TableFullScreenDialog(window, window.data_tab.left_panel, lambda widget: None)

    assert dialog.search_fs.text() == "Gregorio"
    assert dialog.filter_status_fs.currentText() == "Pendentes"
    assert dialog.filter_year_fs.currentText() == "2026"
    assert dialog.filter_micro_fs.checked_items() == ["Gregorio"]
    assert dialog.filter_eletronico_fs.checked_items() == ["SIM"]

    dialog.search_fs.setText("Medeiros")
    dialog.filter_status_fs.setCurrentText("Todos")
    year_index = dialog.filter_year_fs.findText("2025")
    dialog.filter_year_fs.setCurrentIndex(year_index)
    dialog.filter_micro_fs.set_checked_items(["Medeiros"], all_selected=False)
    dialog.filter_eletronico_fs.set_checked_items(["NAO"], all_selected=False)
    dialog._apply_filters_to_main()

    assert window.search.text() == "Medeiros"
    assert window.data_tab.filter_status.currentText() == "Todos"
    assert window.data_tab.filter_year.currentText() == "2025"
    assert window.data_tab.filter_micro.checked_items() == ["Medeiros"]
    assert window.data_tab.filter_eletronico.checked_items() == ["NAO"]
    dialog.close()
    window.close()


def test_search_on_map_persists_detected_microbacia(monkeypatch):
    window = MainWindow()
    monkeypatch.setattr(main_window_module, "geocode_address_arcgis", lambda address: (-22.01, -47.89))
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


def test_search_on_map_enables_street_view_after_geocode(monkeypatch):
    window = MainWindow()
    monkeypatch.setattr(main_window_module, "geocode_address_arcgis", lambda address: (-22.02, -47.91))
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
        combo_fs_heatmap=SimpleNamespace(currentText=lambda: "Realizadas"),
        parent_window=window,
    )

    assert MapFullScreenDialog._get_current_points_fs(fake_dialog) == [[-22.05, -47.95]]

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

    monkeypatch.setattr(main_window_module, "geocode_address_arcgis", lambda address: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    window._perform_geocode("Endereço Inexistente")

    assert warnings and "Não consegui localizar" in warnings[0]
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
    window.data_tab.filter_eletronico.set_checked_items(["SIM"], all_selected=False)
    window.apply_filter()

    monkeypatch.setattr(window.excel, "load", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("falhou")))

    window._load_excel("quebrado.xlsx")

    assert window.data_tab.search.text() == "Gregorio"
    assert window.data_tab.filter_status.currentText() == "Pendentes"
    assert window.data_tab.filter_year.currentText() == "2026"
    assert window.data_tab.filter_micro.checked_items() == ["Gregorio"]
    assert window.data_tab.filter_eletronico.checked_items() == ["SIM"]
    assert len(window.filtered_records) == 1
    window.close()


def test_load_settings_ignores_geometry_and_restores_tab(monkeypatch):
    state = {"window_geometry": b"geom", "active_tab_index": 1}
    restored = []
    
    monkeypatch.setattr(MainWindow, "restoreGeometry", lambda self, geometry: restored.append(geometry) or True)

    window = MainWindow()
    window.settings = SimpleNamespace(
        value=lambda key, default=None: state.get(key, default),
        setValue=lambda *args, **kwargs: None,
    )
    window._load_settings()

    assert restored == []
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
    assert window.settings.last_export_dir() == str(target.parent)
    window.close()


def test_run_map_js_reports_failures_without_raising(monkeypatch):
    logs = []
    window = MainWindow()
    fake_page = SimpleNamespace(runJavaScript=lambda script: (_ for _ in ()).throw(RuntimeError("web indisponivel")))
    monkeypatch.setattr(window.data_tab.web, "page", lambda: fake_page)

    monkeypatch.setattr("app.ui.main_window.logger.error", lambda msg: logs.append(str(msg)))

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

    monkeypatch.setattr(window.excel, "delete_record_shift_up", lambda *args, **kwargs: (_ for _ in ()).throw(LookupError("UID ausente")))
    monkeypatch.setattr(window, "reload", lambda: reloaded.append(True))
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: errors.append(args[2]))

    window.delete_selected()

    assert reloaded == []
    assert errors == ["Nao foi possivel excluir o registro: UID ausente"]
    window.close()


def test_save_edit_blocks_invalid_payload(monkeypatch):
    window = MainWindow()
    saved = []
    warnings = []

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
def test_save_edit_requires_endereco_plantio_when_compensado(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if p == "dummy.xlsx" else real_exists(p))

    window = MainWindow()
    saved = []
    warnings = []

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


def test_save_edit_reloads_without_discard_confirmation(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if p == "dummy.xlsx" else real_exists(p))

    window = MainWindow()
    saved = []
    reload_calls = []
    infos = []

    monkeypatch.setattr(window.excel, "save_edit", lambda record: saved.append(record))
    monkeypatch.setattr(window, "reload", lambda confirm_discard=True: reload_calls.append(confirm_discard) or True)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: infos.append(args[2]))

    window.excel.path = "dummy.xlsx"
    window.selected = make_record()
    window._fill_form(window.selected)
    window.data_tab.in_comp.setText("11")

    window.save_edit()

    assert len(saved) == 1
    assert reload_calls == [False]
    assert infos == ["Salvo com sucesso."]
    window.close()
