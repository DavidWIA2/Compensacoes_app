import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from app.models.compensacao import Compensacao
from app.ui.main_window import MainWindow
from app.ui.tabs.data_tab import DataTab


class MockQWebEngineView(QtWidgets.QWidget):
    loadFinished = Signal(bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._page = SimpleNamespace(runJavaScript=lambda *a: None)

    def setPage(self, page):
        self._page = page

    def page(self):
        return self._page

    def load(self, url):
        return None

    def setUrl(self, url):
        return None


class MockDashboardTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.btn_export_pdf = QtWidgets.QPushButton("Export PDF")

    def update_dashboard(self, *args, **kwargs):
        return None

    def apply_theme(self, theme):
        return None

    def export_images(self):
        return "pie.png", "bar.png"


def get_app():
    return QApplication.instance() or QApplication([])


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
        "uid": "test-uid-123",
    }
    base.update(overrides)
    return Compensacao(**base)


@pytest.fixture(autouse=True)
def phase2_mocks(monkeypatch):
    get_app()
    import app.ui.components.ui_utils as ui_utils_module
    import app.ui.controllers.data_controller as data_controller_module
    import app.ui.controllers.form_controller as form_controller_module
    import app.ui.controllers.map_controller as map_controller_module
    import app.ui.main_window as main_window_module

    monkeypatch.setattr("app.ui.tabs.data_tab.QWebEngineView", MockQWebEngineView)
    monkeypatch.setattr("app.ui.main_window.DashboardTab", MockDashboardTab)
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
    monkeypatch.setattr(DataTab, "load_map", lambda self: None)

    class GlobalMockSettings:
        def __init__(self, *args, **kwargs):
            return None

        def value(self, key, default=""):
            return default

        def setValue(self, key, val):
            return None

        def remove(self, key):
            return None

    monkeypatch.setattr("app.ui.main_window.QSettings", GlobalMockSettings)


def test_window_chrome_summarizes_loaded_session():
    window = MainWindow()
    records = [
        make_record(oficio_processo="PROC-1", av_tec="AT-1", uid="u-1"),
        make_record(excel_row=3, oficio_processo="PROC-2", av_tec="AT-2", uid="u-2"),
    ]
    window.excel.path = os.path.join("C:\\base", "compensacoes.xlsx")
    window.records = list(records)
    window.filtered_records = [records[0]]
    window.selected = records[0]
    window.search.setText("PROC-1")

    window._refresh_window_chrome()

    assert "compensacoes.xlsx" in window.windowTitle()
    assert "(1/2)" in window.windowTitle()
    assert window.session_file_label.text() == "Planilha: compensacoes.xlsx"
    assert window.session_records_label.text() == "Registros: 1 de 2"
    assert window.session_selection_label.text() == "Selecionado: AT-1"
    assert window.session_records_label.toolTip() == "Busca atual: PROC-1"
    window.close()


def test_dirty_form_refreshes_window_chrome(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda path: True if path == "dummy.xlsx" else real_exists(path))

    window = MainWindow()
    record = make_record(oficio_processo="PROC-9", av_tec="AT-9", uid="u-9")
    window.excel.path = "dummy.xlsx"
    window.records = [record]
    window.filtered_records = [record]
    window.selected = record
    window._fill_form(record)

    window.data_tab.in_comp.setText("99")

    assert window.isWindowModified() is True
    assert "dummy.xlsx" in window.windowTitle()
    assert window.form_state_label.text() == "Alterações pendentes"
    assert window.session_selection_label.text() == "Selecionado: AT-9"
    window.close()


def test_help_menu_exposes_update_action():
    window = MainWindow()

    assert window.action_check_updates.text() == "Verificar Atualizacoes"
    window.close()


def test_startup_layout_does_not_lock_table_or_splitter_heights():
    window = MainWindow()

    window._finalize_startup_layout()

    assert window.data_tab._locked_table_height is None
    assert window.data_tab._locked_splitter_height is None
    window.close()
