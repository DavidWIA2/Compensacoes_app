import gc
import logging
import os
import sys
import faulthandler
from types import SimpleNamespace

import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import QCoreApplication, QEvent, QThread, QTimer, Signal
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
        self.btn_export_diagnostics = QtWidgets.QPushButton("Export Diagnostics")

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

    _cleanup_qt_app(app)


def pytest_sessionfinish(session, exitstatus):
    app = QApplication.instance()
    if app:
        _cleanup_qt_app(app)
        app.quit()
    logging.shutdown()
    faulthandler.disable()
    sys.stdout.flush()
    sys.stderr.flush()


def _cleanup_qt_app(app: QApplication) -> None:
    for widget in list(app.topLevelWidgets()):
        _force_close_widget(widget)

    _drain_qt_events(app)
    gc.collect()


def _force_close_widget(widget) -> None:
    try:
        if hasattr(widget, "form_controller"):
            widget.form_controller.confirm_discard_changes = lambda *args, **kwargs: True
        if hasattr(widget, "_startup_close_guard_active"):
            widget._startup_close_guard_active = False
        if hasattr(widget, "_startup_close_guard_armed"):
            widget._startup_close_guard_armed = False
        if hasattr(widget, "_skip_close_discard_confirmation"):
            widget._skip_close_discard_confirmation = True

        lifecycle_controller = getattr(widget, "lifecycle_controller", None)
        if lifecycle_controller is not None and hasattr(lifecycle_controller, "stop_owned_timers"):
            try:
                lifecycle_controller.stop_owned_timers()
            except Exception:
                pass

        support_controller = getattr(widget, "support_controller", None)
        if support_controller is not None and hasattr(support_controller, "shutdown"):
            try:
                support_controller.shutdown()
            except Exception:
                pass

        job_runner = getattr(widget, "job_runner", None)
        if job_runner is not None and hasattr(job_runner, "shutdown_all_workers"):
            try:
                job_runner.shutdown_all_workers()
            except Exception:
                pass

        for timer in widget.findChildren(QTimer):
            try:
                timer.stop()
            except RuntimeError:
                continue

        widget.close()
        widget.hide()
        widget.deleteLater()
    except RuntimeError:
        return


def _drain_qt_events(app: QApplication) -> None:
    for _ in range(4):
        QCoreApplication.sendPostedEvents(None, int(QEvent.DeferredDelete))
        QCoreApplication.sendPostedEvents(None, 0)
        app.processEvents()
