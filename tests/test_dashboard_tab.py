from PySide6 import QtWidgets
from PySide6.QtCore import Signal

from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.application.use_cases.persistence_monitoring import PersistenceRecordOverviewReport
from app.services.tcra_records_service import TcraAgendaItem, TcraRecordOverview


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
    assert tab.scope_tabs.count() == 2
    assert tab.comp_web_host.minimumHeight() >= 250
    assert tab.tcra_web_host.minimumHeight() >= 250
    assert tab.compensation_details_panel.isHidden() is True
    assert getattr(tab, "compensacoes_web_placeholder_container") is not None
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
    integrity_report = type(
        "IntegrityReport",
        (),
        {
            "issue_count": 1,
            "error_count": 0,
            "warning_count": 1,
            "affected_records_count": 1,
            "issues": (type("Issue", (), {"message": "Coordenadas ausentes"})(),),
        },
    )()

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
        integrity_report,
        read_status,
    )

    text = tab.lbl_local_overview.text()
    assert "Cache local sincronizado: 12 registro(s)" in text
    assert "Qualidade dos dados: 2 sem microbacia | 5 sem coordenadas" in text
    assert "Top microbacias: Gregorio: 7 | Medeiros: 5" in text
    assert "Integridade cadastral" in tab.lbl_record_integrity.text()
    assert "Coordenadas ausentes" in tab.lbl_record_integrity.text()
    assert "cache local sincronizado" in tab.lbl_read_source.text()
    assert "6 registro(s) no recorte" in tab.lbl_read_source.text()
    assert tab.card_total.maximumHeight() > 0
    assert "12 processo(s)" in tab.lbl_comp_summary.text()
    assert "integridade com 1 alerta(s)" in tab.lbl_panel_context.text()
    assert tab.btn_export_diagnostics.text() == "Exportar diagnóstico"

    tab.btn_toggle_comp_details.click()
    assert tab.compensation_details_panel.isHidden() is False

    tab._ensure_dashboard_webview("compensacoes")
    assert getattr(tab, "compensacoes_web_placeholder_container") is None

    tab.close()
    parent.close()


def test_dashboard_tab_shows_tcra_overview_and_agenda(monkeypatch, qt_app):
    import app.ui.tabs.dashboard_tab as dashboard_tab_module

    monkeypatch.setattr(dashboard_tab_module, "QWebEngineView", MockQWebEngineView)

    parent = QtWidgets.QWidget()
    parent.scale_factor = 1.0
    parent.is_dark_mode = False

    tab = dashboard_tab_module.DashboardTab(parent)
    overview = TcraRecordOverview(
        total_count=18,
        ativos_count=12,
        cumpridos_count=6,
        prazo_vencido_count=2,
        relatorio_pendente_count=3,
        mpsp_relacionados_count=5,
        com_eventos_count=10,
        sem_numero_tcra_count=4,
        upcoming_30d_count=2,
        sem_responsavel_count=3,
        alertas_count=5,
    )
    agenda = (
        TcraAgendaItem(
            uid="tcra-1",
            priority_rank=0,
            prioridade_label="Prazo vencido",
            termo_label="TCRA-2024-001",
            local="Parque Linear",
            detalhe="Prazo final em 01/04/2026.",
            status_operacional="Prazo vencido",
        ),
        TcraAgendaItem(
            uid="tcra-2",
            priority_rank=1,
            prioridade_label="Relatório pendente",
            termo_label="26207/2019",
            local="Sistema de Lazer",
            detalhe="Relatório previsto em 03/04/2026.",
            status_operacional="Relatório pendente",
        ),
    )

    tab.update_tcra_overview(overview, agenda)
    tab.scope_tabs.setCurrentWidget(tab.tcra_page)

    assert tab.card_tcra_total.lbl_value.text() == "18"
    assert tab.card_tcra_alertas.lbl_value.text() == "5"
    assert tab.card_tcra_proximos.lbl_value.text() == "2"
    assert tab.card_tcra_cumpridos.lbl_value.text() == "6"
    assert "18 | 12 ativos" in tab.lbl_tcra_summary.text()
    assert "Prazo vencido: TCRA-2024-001" in tab.lbl_tcra_agenda.text()
    assert "Relatório pendente: 26207/2019" in tab.lbl_tcra_agenda.text()
    assert "TCRAs: 5 alerta(s)" in tab.lbl_agenda_summary.text()
    assert tab.current_export_context() is not None

    tab.close()
    parent.close()


def test_dashboard_tab_agenda_buttons_navigate_to_target_tabs(monkeypatch, qt_app):
    import app.ui.tabs.dashboard_tab as dashboard_tab_module

    monkeypatch.setattr(dashboard_tab_module, "QWebEngineView", MockQWebEngineView)

    tabs = QtWidgets.QTabWidget()
    parent = QtWidgets.QWidget()
    parent.scale_factor = 1.0
    parent.is_dark_mode = False
    parent.tabs = tabs
    parent.operations_tab = QtWidgets.QWidget()
    parent.tcra_tab = QtWidgets.QWidget()
    tabs.addTab(QtWidgets.QWidget(), "Dados")
    tabs.addTab(parent.operations_tab, "Operacoes")
    tabs.addTab(parent.tcra_tab, "TCRAs")

    tab = dashboard_tab_module.DashboardTab(parent)
    parent.tcra_tab._set_agenda_scope = lambda scope: setattr(parent, "_last_scope", scope)
    parent.tcra_tab._open_inbox_overview = lambda: setattr(parent, "_opened_inbox", True)

    tab.btn_open_operations.click()
    assert tabs.currentWidget() is parent.operations_tab

    tab.btn_open_tcra_agenda.click()
    assert tabs.currentWidget() is parent.tcra_tab
    assert parent._last_scope == "hoje"
    assert parent._opened_inbox is True

    tab.close()
    parent.close()
