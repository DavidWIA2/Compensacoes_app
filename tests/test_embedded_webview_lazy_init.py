from types import SimpleNamespace

from PySide6 import QtWidgets
from PySide6.QtCore import QObject, Signal


class _FakePage(QObject):
    def __init__(self):
        super().__init__()
        self._settings = SimpleNamespace(setAttribute=lambda *args, **kwargs: None)

    def settings(self):
        return self._settings

    def setBackgroundColor(self, *args, **kwargs):
        return None

    def setWebChannel(self, *args, **kwargs):
        return None

    def runJavaScript(self, *args, **kwargs):
        return None


class _CountingWebView(QtWidgets.QWidget):
    loadFinished = Signal(bool)
    created_count = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        type(self).created_count += 1
        self._page = _FakePage()

    def setPage(self, page):
        self._page = page

    def page(self):
        return self._page

    def setUrl(self, url):
        self._last_url = url

    def grab(self):
        return QtWidgets.QWidget.grab(self)


def test_data_tab_defers_webengine_until_map_load(monkeypatch, qt_app, tmp_path):
    import app.ui.tabs.data_tab as data_tab_module

    _CountingWebView.created_count = 0
    monkeypatch.setattr(data_tab_module, "QWebEngineView", _CountingWebView)
    monkeypatch.setattr(
        data_tab_module,
        "resource_path",
        lambda *parts: str(tmp_path / "map_leaflet.html"),
    )
    (tmp_path / "map_leaflet.html").write_text("<html></html>", encoding="utf-8")

    parent = QtWidgets.QWidget()
    parent.scale_factor = 1.0

    tab = data_tab_module.DataTab(parent)

    assert _CountingWebView.created_count == 0
    assert tab.has_map_web_view() is False

    tab.load_map()

    assert _CountingWebView.created_count == 1
    assert tab.has_map_web_view() is True

    tab.close()
    parent.close()


def test_dashboard_tab_defers_webengine_until_visible(monkeypatch, qt_app):
    import app.ui.tabs.dashboard_tab as dashboard_tab_module

    _CountingWebView.created_count = 0
    monkeypatch.setattr(dashboard_tab_module, "QWebEngineView", _CountingWebView)

    parent = QtWidgets.QWidget()
    parent.scale_factor = 1.0
    parent.is_dark_mode = False

    tab = dashboard_tab_module.DashboardTab(parent)

    assert _CountingWebView.created_count == 0

    tab._ensure_current_scope_webview()

    assert _CountingWebView.created_count == 1

    tab.close()
    parent.close()
