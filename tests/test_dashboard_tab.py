from PySide6 import QtWidgets
from PySide6.QtCore import Signal

from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.application.use_cases.persistence_monitoring import PersistenceRecordOverviewReport


class _DummyPage:
    def runJavaScript(self, *args, **kwargs):
        return None

    def setBackgroundColor(self, *args, **kwargs):
        return None


class MockQWebEngineView(QtWidgets.QWidget):
    loadFinished = Signal(bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._page = _DummyPage()

    def page(self):
        return self._page

    def setUrl(self, url):
        self._last_url = url


def test_dashboard_tab_shows_local_sqlite_overview(monkeypatch, qt_app):
    import app.ui.tabs.dashboard_tab as dashboard_tab_module

    monkeypatch.setattr(dashboard_tab_module, "QWebEngineView", MockQWebEngineView)

    parent = QtWidgets.QWidget()
    parent.scale_factor = 1.0
    parent.is_dark_mode = False

    tab = dashboard_tab_module.DashboardTab(parent)
    report = PersistenceRecordOverviewReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-30T12:00:00+00:00",
        total_records=12,
        compensados_count=4,
        pendentes_count=8,
        records_with_plantios_count=3,
        records_without_microbacia_count=2,
        records_without_coordinates_count=5,
        top_microbacias=(("Gregorio", 7), ("Medeiros", 5)),
    )
    read_status = LocalRecordReadStatus(
        status="sqlite",
        source="sqlite",
        strategy="sqlite_query",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-31T12:00:00+00:00",
        mirrored_records=12,
        session_records=12,
        filtered_records=6,
    )

    tab.update_dashboard(
        {
            "total_geral": 120,
            "total_pendente": 80,
            "total_compensado": 40,
            "count_total": 12,
        },
        False,
        ["Gregorio", "Medeiros"],
        report,
        read_status,
    )

    text = tab.lbl_local_overview.text()
    assert "Espelho local (SQLite): 12 registro(s)" in text
    assert "Qualidade dos dados: 2 sem microbacia | 5 sem coordenadas" in text
    assert "Top microbacias: Gregorio: 7 | Medeiros: 5" in text
    assert "espelho local (SQLite)" in tab.lbl_read_source.text()
    assert "6 registro(s) no recorte" in tab.lbl_read_source.text()

    tab.close()
    parent.close()
