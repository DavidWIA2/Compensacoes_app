import gc
import os
from types import SimpleNamespace

import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import QCoreApplication, QThread, Signal
from PySide6.QtWidgets import QApplication


class MockQWebEngineView(QtWidgets.QWidget):
    loadFinished = Signal(bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._page = SimpleNamespace(runJavaScript=lambda *a, **k: None)

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


class NoopUpdaterWorker(QThread):
    update_available = Signal(str, str)

    def start(self, priority=QThread.InheritPriority):
        return None


class GlobalMockSettings:
    def __init__(self, *args, **kwargs):
        pass

    def value(self, key, default=""):
        return default

    def setValue(self, key, value):
        return None

    def remove(self, key):
        return None


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ui_test_env(monkeypatch, qt_app, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    import app.ui.components.ui_utils as ui_utils_module
    import app.ui.controllers.data_controller as data_controller_module
    import app.ui.controllers.form_controller as form_controller_module
    import app.ui.controllers.map_controller as map_controller_module
    import app.ui.main_window as main_window_module
    from app.ui.main_window import MainWindow
    from app.services.sqlite_mirror_service import SqliteMirrorService
    from app.ui.tabs.data_tab import DataTab

    monkeypatch.setattr("app.ui.tabs.data_tab.QWebEngineView", MockQWebEngineView)
    monkeypatch.setattr(main_window_module, "DashboardTab", MockDashboardTab)
    monkeypatch.setattr(main_window_module, "UpdaterWorker", NoopUpdaterWorker)
    monkeypatch.setattr(main_window_module, "QSettings", GlobalMockSettings)
    monkeypatch.setattr(
        main_window_module,
        "SqliteMirrorService",
        lambda *args, **kwargs: SqliteMirrorService(db_path=tmp_path / "ui-mirror.db"),
    )
    monkeypatch.setattr(MainWindow, "_apply_theme", lambda self: None)
    monkeypatch.setattr(DataTab, "load_map", lambda self: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(ui_utils_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(data_controller_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(form_controller_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(map_controller_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(main_window_module, "msg_confirm", lambda *args, **kwargs: True)

    return {"app": qt_app}


@pytest.fixture
def ui_window_factory(ui_test_env):
    from app.ui.main_window import MainWindow

    created_windows = []

    def factory():
        window = MainWindow()
        created_windows.append(window)
        return window

    return factory


@pytest.fixture(autouse=True)
def cleanup_qt_widgets():
    yield

    app = QApplication.instance()
    if not app:
        return

    # Qt can keep closed top-level widgets alive until posted events run.
    for widget in list(app.topLevelWidgets()):
        if hasattr(widget, "form_controller"):
            widget.form_controller.confirm_discard_changes = lambda *args, **kwargs: True
        widget.close()
        widget.deleteLater()

    QCoreApplication.sendPostedEvents(None, 0)
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, 0)
    app.processEvents()
    gc.collect()
