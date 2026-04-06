import json
import os
import tempfile
import uuid
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.application.use_cases.persistence_monitoring import PersistenceRecordOverviewReport
from app.services.tcra_records_service import TcraAgendaItem, TcraRecordOverview
from app.ui.components.ui_utils import resource_path
from app.ui.components.widgets import KPICard
from app.ui.tabs.dashboard_tab_support import (
    DashboardExportContext,
    build_compensation_chart_payload,
    build_dashboard_agenda_summary_text,
    build_local_overview_text,
    build_read_source_text,
    build_tcra_agenda_text,
    build_tcra_chart_payload,
    build_tcra_dashboard_export_context,
    build_tcra_summary_text,
)


class DashboardTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.sf = getattr(parent, "scale_factor", 1.0)
        self._page_loaded = {"compensacoes": False, "tcra": False}
        self._last_chart_payload = {"compensacoes": None, "tcra": None}
        self._last_metrics: Dict | None = None
        self._last_record_overview: Optional[PersistenceRecordOverviewReport] = None
        self._last_record_read_status: Optional[LocalRecordReadStatus] = None
        self._last_tcra_overview: Optional[TcraRecordOverview] = None
        self._last_tcra_agenda: tuple[TcraAgendaItem, ...] = ()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        layout.setSpacing(int(10 * self.sf))

        actions_layout = QHBoxLayout()
        self.btn_export_pdf = QPushButton("Exportar Painel (PDF)")
        self.btn_export_pdf.setMinimumHeight(int(30 * self.sf))
        actions_layout.addStretch(1)
        actions_layout.addWidget(self.btn_export_pdf)
        layout.addLayout(actions_layout)

        self.scope_tabs = QTabWidget(self)
        layout.addWidget(self.scope_tabs, 1)

        self.comp_page = QWidget(self)
        self.tcra_page = QWidget(self)
        self.scope_tabs.addTab(self.comp_page, "Compensações")
        self.scope_tabs.addTab(self.tcra_page, "TCRAs")

        self._build_compensation_page()
        self._build_tcra_page()

        self.btn_open_operations.clicked.connect(self._open_operations_tab)
        self.btn_open_tcra_agenda.clicked.connect(self._open_tcra_tab)

    def _build_compensation_page(self) -> None:
        layout = QVBoxLayout(self.comp_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(10 * self.sf))

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(int(10 * self.sf))
        self.card_total = KPICard("Total Mudas", "0", "#2176ff")
        self.card_pend = KPICard("Pendentes", "0", "#d32f2f")
        self.card_comp = KPICard("Compensadas", "0", "#2e7d32")
        self.card_records = KPICard("Total Processos", "0", "#ff9800")
        for card in [self.card_total, self.card_pend, self.card_comp, self.card_records]:
            cards_layout.addWidget(card)
        layout.addLayout(cards_layout)

        self.lbl_local_overview = QLabel(
            "Resumo local (SQLite): carregue uma sessão para acompanhar a qualidade dos dados."
        )
        self.lbl_local_overview.setWordWrap(True)
        self.lbl_local_overview.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_local_overview)

        self.lbl_read_source = QLabel(
            "Leitura operacional atual: aguardando aplicação dos filtros."
        )
        self.lbl_read_source.setWordWrap(True)
        self.lbl_read_source.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_read_source)

        self.lbl_agenda_summary = QLabel("Agenda executiva: aguardando leitura inicial.")
        self.lbl_agenda_summary.setWordWrap(True)
        self.lbl_agenda_summary.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_agenda_summary)

        agenda_actions = QHBoxLayout()
        agenda_actions.setSpacing(int(8 * self.sf))
        self.btn_open_operations = QPushButton("Abrir Operações")
        self.btn_open_operations.setProperty("kind", "secondary")
        self.btn_open_tcra_agenda = QPushButton("Abrir TCRAs")
        self.btn_open_tcra_agenda.setProperty("kind", "secondary")
        agenda_actions.addWidget(self.btn_open_operations)
        agenda_actions.addWidget(self.btn_open_tcra_agenda)
        agenda_actions.addStretch(1)
        layout.addLayout(agenda_actions)

        self.comp_web = self._build_dashboard_webview("compensacoes")
        self.web = self.comp_web
        layout.addWidget(self.comp_web, 1)

    def _build_tcra_page(self) -> None:
        layout = QVBoxLayout(self.tcra_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(10 * self.sf))

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(int(10 * self.sf))
        self.card_tcra_total = KPICard("TCRAs", "0", "#0b6e4f")
        self.card_tcra_alertas = KPICard("Alertas", "0", "#d32f2f")
        self.card_tcra_proximos = KPICard("Próx. 30 dias", "0", "#fb8c00")
        self.card_tcra_cumpridos = KPICard("Cumpridos", "0", "#3949ab")
        for card in [self.card_tcra_total, self.card_tcra_alertas, self.card_tcra_proximos, self.card_tcra_cumpridos]:
            cards_layout.addWidget(card)
        layout.addLayout(cards_layout)

        self.lbl_tcra_summary = QLabel("TCRAs: nenhum termo carregado no banco local.")
        self.lbl_tcra_summary.setWordWrap(True)
        self.lbl_tcra_summary.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_tcra_summary)

        self.lbl_tcra_agenda = QLabel("Agenda TCRA: --")
        self.lbl_tcra_agenda.setWordWrap(True)
        self.lbl_tcra_agenda.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_tcra_agenda)

        tcra_actions = QHBoxLayout()
        tcra_actions.setSpacing(int(8 * self.sf))
        self.btn_open_tcra_page = QPushButton("Abrir Módulo TCRA")
        self.btn_open_tcra_page.setProperty("kind", "secondary")
        self.btn_open_tcra_page.clicked.connect(self._open_tcra_tab)
        tcra_actions.addWidget(self.btn_open_tcra_page)
        tcra_actions.addStretch(1)
        layout.addLayout(tcra_actions)

        self.tcra_web = self._build_dashboard_webview("tcra")
        layout.addWidget(self.tcra_web, 1)

    def _build_dashboard_webview(self, kind: str) -> QWebEngineView:
        web = QWebEngineView()
        web.setStyleSheet("background: transparent;")
        web.page().setBackgroundColor(Qt.transparent)
        web.loadFinished.connect(lambda ok, scope=kind: self._on_load_finished(scope, ok))
        html_path = resource_path("app", "ui", "dashboard_echarts.html")
        if os.path.exists(html_path):
            web.setUrl(QUrl.fromLocalFile(html_path))
        return web

    def _on_load_finished(self, kind: str, ok: bool) -> None:
        if not ok:
            return
        self._page_loaded[kind] = True
        payload = self._last_chart_payload.get(kind)
        if payload:
            self._send_to_js(kind, payload)

    def _send_to_js(self, kind: str, data: Dict) -> None:
        target = self.comp_web if kind == "compensacoes" else self.tcra_web
        script = f"if(window.updateDashboard) window.updateDashboard({json.dumps(json.dumps(data))});"
        target.page().runJavaScript(script)

    def update_dashboard(
        self,
        m: Dict,
        is_dark: bool,
        micro_palette_keys: List[str],
        record_overview: Optional[PersistenceRecordOverviewReport] = None,
        record_read_status: Optional[LocalRecordReadStatus] = None,
    ):
        self._last_metrics = dict(m)
        self._last_record_overview = record_overview
        self._last_record_read_status = record_read_status

        self.card_total.update_value(f"{m['total_geral']:,.0f}".replace(",", "."))
        self.card_pend.update_value(f"{m['total_pendente']:,.0f}".replace(",", "."))
        self.card_comp.update_value(f"{m['total_compensado']:,.0f}".replace(",", "."))
        self.card_records.update_value(f"{m['count_total']}")
        self.lbl_local_overview.setText(build_local_overview_text(record_overview))
        self.lbl_read_source.setText(build_read_source_text(record_read_status))

        payload = build_compensation_chart_payload(
            m,
            is_dark=is_dark,
            micro_palette_keys=micro_palette_keys,
        )
        self._last_chart_payload["compensacoes"] = payload
        if self._page_loaded["compensacoes"]:
            self._send_to_js("compensacoes", payload)
        self._refresh_agenda_summary()

    def update_tcra_overview(
        self,
        overview: Optional[TcraRecordOverview],
        agenda_items: Sequence[TcraAgendaItem] = (),
    ):
        self._last_tcra_overview = overview
        self._last_tcra_agenda = tuple(agenda_items)
        if overview is None:
            self.card_tcra_total.update_value("0")
            self.card_tcra_alertas.update_value("0")
            self.card_tcra_proximos.update_value("0")
            self.card_tcra_cumpridos.update_value("0")
            self.lbl_tcra_summary.setText(build_tcra_summary_text(None))
            self.lbl_tcra_agenda.setText(build_tcra_agenda_text(()))
        else:
            self.card_tcra_total.update_value(str(overview.total_count))
            self.card_tcra_alertas.update_value(str(overview.alertas_count))
            self.card_tcra_proximos.update_value(str(overview.upcoming_30d_count))
            self.card_tcra_cumpridos.update_value(str(overview.cumpridos_count))
            self.lbl_tcra_summary.setText(build_tcra_summary_text(overview))
            self.lbl_tcra_agenda.setText(build_tcra_agenda_text(agenda_items))

        payload = build_tcra_chart_payload(
            overview,
            is_dark=bool(getattr(self.main_window, "is_dark_mode", False)),
        )
        self._last_chart_payload["tcra"] = payload
        if self._page_loaded["tcra"]:
            self._send_to_js("tcra", payload)
        self._refresh_agenda_summary()

    def _refresh_agenda_summary(self):
        self.lbl_agenda_summary.setText(
            build_dashboard_agenda_summary_text(
                self._last_metrics,
                self._last_tcra_overview,
                self._last_tcra_agenda,
            )
        )

    def _open_operations_tab(self):
        if getattr(self.main_window, "tabs", None) is not None:
            self.main_window.tabs.setCurrentWidget(getattr(self.main_window, "operations_tab", self))

    def _open_tcra_tab(self):
        if getattr(self.main_window, "tabs", None) is None:
            return
        tcra_tab = getattr(self.main_window, "tcra_tab", None)
        if tcra_tab is None:
            return
        self.main_window.tabs.setCurrentWidget(tcra_tab)
        if hasattr(tcra_tab, "_set_agenda_scope"):
            tcra_tab._set_agenda_scope("hoje")
        if hasattr(tcra_tab, "_open_inbox_overview"):
            tcra_tab._open_inbox_overview()

    def apply_theme(self, theme):
        for card in [
            self.card_total,
            self.card_pend,
            self.card_comp,
            self.card_records,
            self.card_tcra_total,
            self.card_tcra_alertas,
            self.card_tcra_proximos,
            self.card_tcra_cumpridos,
        ]:
            card.update_style(theme)

        is_dark = getattr(self.main_window, "is_dark_mode", False)
        if self._last_metrics is not None:
            payload = build_compensation_chart_payload(
                self._last_metrics,
                is_dark=is_dark,
                micro_palette_keys=list(
                    (self._last_chart_payload.get("compensacoes") or {}).get("micro_palette_keys", [])
                ),
            )
            self._last_chart_payload["compensacoes"] = payload
            if self._page_loaded["compensacoes"]:
                self._send_to_js("compensacoes", payload)
        if self._last_tcra_overview is not None or self._last_chart_payload.get("tcra") is not None:
            payload = build_tcra_chart_payload(self._last_tcra_overview, is_dark=is_dark)
            self._last_chart_payload["tcra"] = payload
            if self._page_loaded["tcra"]:
                self._send_to_js("tcra", payload)

    def export_images(self) -> Tuple[str, str]:
        active_web = self.comp_web if self.scope_tabs.currentWidget() is self.comp_page else self.tcra_web
        pixmap = active_web.grab()
        if pixmap.isNull():
            return "", ""

        width = pixmap.width()
        height = pixmap.height()
        if width <= 1 or height <= 1:
            return "", ""

        pie_width = max(1, int(width * 0.45))
        bar_width = max(1, width - pie_width)

        pie_pixmap = pixmap.copy(0, 0, pie_width, height)
        bar_pixmap = pixmap.copy(pie_width, 0, bar_width, height)

        token = uuid.uuid4().hex
        pie_path = os.path.join(tempfile.gettempdir(), f"dash_pie_{token}.png")
        bar_path = os.path.join(tempfile.gettempdir(), f"dash_bar_{token}.png")

        pie_pixmap.save(pie_path)
        bar_pixmap.save(bar_path)
        return pie_path, bar_path

    def current_export_context(self) -> Optional[DashboardExportContext]:
        if self.scope_tabs.currentWidget() is self.tcra_page:
            return build_tcra_dashboard_export_context(self._last_tcra_overview, self._last_tcra_agenda)
        return None
