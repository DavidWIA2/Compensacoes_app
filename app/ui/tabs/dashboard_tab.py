import json
import os
import tempfile
import uuid
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
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
        self.comp_web: QWebEngineView | None = None
        self.tcra_web: QWebEngineView | None = None
        self.web: QWebEngineView | None = None
        self._chart_min_height = self._resolve_chart_min_height()
        self._card_max_height = self._resolve_card_max_height()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        layout.setSpacing(int(6 * self.sf))

        hero_frame = QFrame(self)
        hero_frame.setProperty("panel", "hero")
        hero_layout = QHBoxLayout(hero_frame)
        hero_layout.setContentsMargins(int(12 * self.sf), int(10 * self.sf), int(12 * self.sf), int(10 * self.sf))
        hero_layout.setSpacing(int(10 * self.sf))
        hero_text = QVBoxLayout()
        hero_text.setSpacing(int(2 * self.sf))
        self.lbl_panel_kicker = QLabel("VISÃO EXECUTIVA")
        self.lbl_panel_kicker.setProperty("role", "eyebrow")
        self.lbl_panel_title = QLabel("Painel consolidado da base sincronizada")
        self.lbl_panel_title.setProperty("role", "page-title")
        self.lbl_panel_subtitle = QLabel(
            "Acompanhe indicadores, pendências e leituras executivas sem sair do contexto operacional."
        )
        self.lbl_panel_subtitle.setProperty("role", "page-subtitle")
        self.lbl_panel_subtitle.setWordWrap(True)
        self.lbl_panel_context = QLabel("Base sincronizada pronta para leitura.")
        self.lbl_panel_context.setProperty("role", "page-meta")
        self.lbl_panel_context.setWordWrap(True)
        hero_text.addWidget(self.lbl_panel_kicker)
        hero_text.addWidget(self.lbl_panel_title)
        hero_text.addWidget(self.lbl_panel_subtitle)
        hero_text.addWidget(self.lbl_panel_context)
        hero_layout.addLayout(hero_text, 1)
        hero_actions = QVBoxLayout()
        hero_actions.setSpacing(int(5 * self.sf))
        hero_actions.addStretch(1)
        self.btn_export_pdf = QPushButton("Exportar painel (PDF)")
        self.btn_export_pdf.setProperty("kind", "ghost")
        self.btn_export_pdf.setMinimumHeight(int(26 * self.sf))
        hero_actions.addWidget(self.btn_export_pdf, 0, Qt.AlignRight)
        hero_layout.addLayout(hero_actions, 0)
        layout.addWidget(hero_frame)

        self.scope_tabs = QTabWidget(self)
        self.scope_tabs.setDocumentMode(True)
        layout.addWidget(self.scope_tabs, 1)

        self.comp_page = QWidget(self)
        self.tcra_page = QWidget(self)
        self.scope_tabs.addTab(self.comp_page, "Compensações")
        self.scope_tabs.addTab(self.tcra_page, "TCRAs")

        self._build_compensation_page()
        self._build_tcra_page()
        self.scope_tabs.currentChanged.connect(self._ensure_current_scope_webview)

        self.btn_open_operations.clicked.connect(self._open_operations_tab)
        self.btn_open_tcra_agenda.clicked.connect(self._open_tcra_tab)
        self._apply_responsive_layout()

    def _current_root_dimensions(self) -> tuple[int, int]:
        root = self.window()
        current_width = root.width() if root is not None and root.width() > 0 else self.width()
        current_height = root.height() if root is not None and root.height() > 0 else self.height()

        screen = None
        if root is not None:
            try:
                screen = root.screen()
            except Exception:
                screen = None
        if screen is None:
            app = QApplication.instance()
            screen = app.primaryScreen() if app is not None else None

        if screen is not None:
            available = screen.availableGeometry() if hasattr(screen, "availableGeometry") else screen.geometry()
            available_width = available.width()
            available_height = available.height()
            if (current_width <= 0 or current_width < 900) and not self.isVisible():
                current_width = available_width
            elif current_width > 0:
                current_width = min(current_width, available_width)
            if (current_height <= 0 or current_height < 640) and not self.isVisible():
                current_height = available_height
            elif current_height > 0:
                current_height = min(current_height, available_height)

        if current_width <= 0:
            current_width = 1920
        if current_height <= 0:
            current_height = 1080
        return current_width, current_height

    def _is_short_layout(self) -> bool:
        _, current_height = self._current_root_dimensions()
        return current_height <= 1032

    def _is_very_short_layout(self) -> bool:
        _, current_height = self._current_root_dimensions()
        return current_height <= 920

    def _resolve_chart_min_height(self) -> int:
        compact_mode = self._is_compact_layout()
        short_mode = self._is_short_layout()
        very_short_mode = self._is_very_short_layout()
        target_height = (
            250 if very_short_mode else
            320 if short_mode else
            420 if compact_mode else
            520
        )
        minimum_height = 220 if very_short_mode else 260 if short_mode else 300
        return max(int(target_height * self.sf), minimum_height)

    def _resolve_card_max_height(self) -> int:
        compact_mode = self._is_compact_layout()
        short_mode = self._is_short_layout()
        target_height = 34 if short_mode else 40 if compact_mode else 46
        return max(int(target_height * self.sf), 30)

    def _configure_compact_info_label(self, label: QLabel, *, max_height: int) -> None:
        label.setWordWrap(True)
        label.setObjectName("FormStateLabel")
        label.setMaximumHeight(max_height)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

    def _set_compensation_details_visible(self, visible: bool) -> None:
        show_details = bool(visible)
        self.compensation_details_panel.setVisible(show_details)
        self.btn_toggle_comp_details.setText("Ocultar detalhes" if show_details else "Detalhes")

    def _refresh_compensation_summary(self) -> None:
        metrics = dict(self._last_metrics or {})
        total_processos = int(metrics.get("count_total", 0) or 0)
        total_pendente = int(metrics.get("total_pendente", 0) or 0)
        total_compensado = int(metrics.get("total_compensado", 0) or 0)
        if total_processos <= 0:
            self.lbl_comp_summary.setText("Painel operacional: aguardando leitura da base.")
            return
        self.lbl_comp_summary.setText(
            f"Recorte atual: {total_processos} processo(s) | {total_pendente} pendente(s) | {total_compensado} compensado(s)"
        )

    def _build_compensation_page(self) -> None:
        layout = QVBoxLayout(self.comp_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(4 * self.sf))

        header_frame = QFrame(self.comp_page)
        header_frame.setProperty("panel", "toolbar")
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(int(10 * self.sf), int(8 * self.sf), int(10 * self.sf), int(8 * self.sf))
        header_layout.setSpacing(int(3 * self.sf))
        comp_kicker = QLabel("COMPENSAÇÕES")
        comp_kicker.setProperty("role", "eyebrow")
        comp_title = QLabel("Resumo executivo do recorte atual")
        comp_title.setProperty("role", "section-title")
        self.comp_subtitle = QLabel("Indicadores-chave, leitura operacional e gráficos do recorte carregado.")
        self.comp_subtitle.setProperty("role", "helper")
        self.comp_subtitle.setWordWrap(True)
        header_layout.addWidget(comp_kicker)
        header_layout.addWidget(comp_title)
        header_layout.addWidget(self.comp_subtitle)
        layout.addWidget(header_frame)

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(int(6 * self.sf))
        self.card_total = KPICard("Total de mudas", "0", "#2176ff", compact=True)
        self.card_pend = KPICard("Pendentes", "0", "#d32f2f", compact=True)
        self.card_comp = KPICard("Compensadas", "0", "#2e7d32", compact=True)
        self.card_records = KPICard("Total de processos", "0", "#ff9800", compact=True)
        for card in [self.card_total, self.card_pend, self.card_comp, self.card_records]:
            card.setMaximumHeight(self._card_max_height)
            cards_layout.addWidget(card)
        layout.addLayout(cards_layout)

        comp_summary_row = QHBoxLayout()
        comp_summary_row.setContentsMargins(0, 0, 0, 0)
        comp_summary_row.setSpacing(int(6 * self.sf))
        self.lbl_comp_summary = QLabel("Painel operacional: aguardando leitura da base.")
        self._configure_compact_info_label(self.lbl_comp_summary, max_height=int(26 * self.sf))
        self.btn_open_operations = QPushButton("Operações")
        self.btn_open_operations.setProperty("kind", "chip-quiet")
        self.btn_open_operations.setMinimumHeight(int(24 * self.sf))
        self.btn_open_tcra_agenda = QPushButton("Agenda TCRA")
        self.btn_open_tcra_agenda.setProperty("kind", "chip-quiet")
        self.btn_open_tcra_agenda.setMinimumHeight(int(24 * self.sf))
        self.btn_toggle_comp_details = QPushButton("Detalhes")
        self.btn_toggle_comp_details.setProperty("kind", "chip-quiet")
        self.btn_toggle_comp_details.setMaximumWidth(int(104 * self.sf))
        self.btn_toggle_comp_details.setMinimumHeight(int(24 * self.sf))
        comp_summary_row.addWidget(self.lbl_comp_summary, 1)
        comp_summary_row.addWidget(self.btn_open_operations, 0)
        comp_summary_row.addWidget(self.btn_open_tcra_agenda, 0)
        comp_summary_row.addWidget(self.btn_toggle_comp_details, 0)
        layout.addLayout(comp_summary_row)

        self.compensation_details_panel = QWidget(self.comp_page)
        self.compensation_details_panel.setProperty("panel", "subtle")
        details_layout = QVBoxLayout(self.compensation_details_panel)
        details_layout.setContentsMargins(int(10 * self.sf), int(8 * self.sf), int(10 * self.sf), int(8 * self.sf))
        details_layout.setSpacing(int(4 * self.sf))
        details_title = QLabel("Leitura operacional detalhada")
        details_title.setProperty("role", "sidebar-title")
        details_caption = QLabel("Use este bloco para validar o cache sincronizado, o recorte local e a agenda executiva.")
        details_caption.setProperty("role", "sidebar-helper")
        details_caption.setWordWrap(True)
        details_layout.addWidget(details_title)
        details_layout.addWidget(details_caption)
        self.btn_toggle_comp_details.clicked.connect(
            lambda: self._set_compensation_details_visible(not self.compensation_details_panel.isVisible())
        )

        self.lbl_local_overview = QLabel(
            "Resumo local (SQLite): carregue uma sessão para acompanhar a qualidade dos dados."
        )
        self._configure_compact_info_label(self.lbl_local_overview, max_height=int(34 * self.sf))
        details_layout.addWidget(self.lbl_local_overview)

        self.lbl_read_source = QLabel(
            "Leitura operacional atual: aguardando aplicação dos filtros."
        )
        self._configure_compact_info_label(self.lbl_read_source, max_height=int(34 * self.sf))
        details_layout.addWidget(self.lbl_read_source)

        self.lbl_agenda_summary = QLabel("Agenda executiva: aguardando leitura inicial.")
        self._configure_compact_info_label(self.lbl_agenda_summary, max_height=int(34 * self.sf))
        details_layout.addWidget(self.lbl_agenda_summary)
        layout.addWidget(self.compensation_details_panel)
        self._set_compensation_details_visible(False)

        self.comp_web_host = self._build_dashboard_host("compensacoes")
        layout.addWidget(self.comp_web_host, 1)

    def _build_tcra_page(self) -> None:
        layout = QVBoxLayout(self.tcra_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(4 * self.sf))

        header_frame = QFrame(self.tcra_page)
        header_frame.setProperty("panel", "toolbar")
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(int(10 * self.sf), int(8 * self.sf), int(10 * self.sf), int(8 * self.sf))
        header_layout.setSpacing(int(3 * self.sf))
        tcra_kicker = QLabel("TCRAs")
        tcra_kicker.setProperty("role", "eyebrow")
        tcra_title = QLabel("Acompanhamento executivo dos termos")
        tcra_title.setProperty("role", "section-title")
        self.tcra_subtitle = QLabel("Alertas, próximos relatórios e situação do módulo TCRA no mesmo painel.")
        self.tcra_subtitle.setProperty("role", "helper")
        self.tcra_subtitle.setWordWrap(True)
        header_layout.addWidget(tcra_kicker)
        header_layout.addWidget(tcra_title)
        header_layout.addWidget(self.tcra_subtitle)
        layout.addWidget(header_frame)

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(int(8 * self.sf))
        self.card_tcra_total = KPICard("Total de TCRAs", "0", "#0b6e4f", compact=True)
        self.card_tcra_alertas = KPICard("Alertas", "0", "#d32f2f", compact=True)
        self.card_tcra_proximos = KPICard("Próx. 30 dias", "0", "#fb8c00", compact=True)
        self.card_tcra_cumpridos = KPICard("Cumpridos", "0", "#3949ab", compact=True)
        for card in [self.card_tcra_total, self.card_tcra_alertas, self.card_tcra_proximos, self.card_tcra_cumpridos]:
            card.setMaximumHeight(self._card_max_height)
            cards_layout.addWidget(card)
        layout.addLayout(cards_layout)

        tcra_summary_row = QHBoxLayout()
        tcra_summary_row.setContentsMargins(0, 0, 0, 0)
        tcra_summary_row.setSpacing(int(6 * self.sf))
        self.lbl_tcra_summary = QLabel("TCRAs: nenhum termo carregado no banco local.")
        self._configure_compact_info_label(self.lbl_tcra_summary, max_height=int(28 * self.sf))
        self.btn_open_tcra_page = QPushButton("Abrir módulo TCRA")
        self.btn_open_tcra_page.setProperty("kind", "chip-quiet")
        self.btn_open_tcra_page.setMinimumHeight(int(24 * self.sf))
        self.btn_open_tcra_page.clicked.connect(self._open_tcra_tab)
        tcra_summary_row.addWidget(self.lbl_tcra_summary, 1)
        tcra_summary_row.addWidget(self.btn_open_tcra_page, 0)
        layout.addLayout(tcra_summary_row)

        tcra_agenda_frame = QFrame(self.tcra_page)
        tcra_agenda_frame.setProperty("panel", "subtle")
        tcra_agenda_layout = QVBoxLayout(tcra_agenda_frame)
        tcra_agenda_layout.setContentsMargins(int(10 * self.sf), int(8 * self.sf), int(10 * self.sf), int(8 * self.sf))
        tcra_agenda_layout.setSpacing(int(4 * self.sf))
        tcra_agenda_title = QLabel("Agenda prioritária")
        tcra_agenda_title.setProperty("role", "panel-caption")
        self.lbl_tcra_agenda = QLabel("Agenda TCRA: --")
        self._configure_compact_info_label(self.lbl_tcra_agenda, max_height=int(30 * self.sf))
        tcra_agenda_layout.addWidget(tcra_agenda_title)
        tcra_agenda_layout.addWidget(self.lbl_tcra_agenda)
        layout.addWidget(tcra_agenda_frame)

        self.tcra_web_host = self._build_dashboard_host("tcra")
        layout.addWidget(self.tcra_web_host, 1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_responsive_layout()
        self._ensure_current_scope_webview()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _is_compact_layout(self) -> bool:
        current_width, current_height = self._current_root_dimensions()
        return current_width <= 1460 or current_height <= 1032

    def _apply_responsive_layout(self) -> None:
        compact_mode = self._is_compact_layout()
        short_mode = self._is_short_layout()
        very_short_mode = self._is_very_short_layout()
        tight_mode = compact_mode and very_short_mode
        self.lbl_panel_subtitle.setVisible(not compact_mode and not short_mode)
        self.lbl_panel_context.setVisible(not tight_mode)
        self.comp_subtitle.setVisible(not short_mode)
        self.tcra_subtitle.setVisible(not short_mode)

        self._chart_min_height = self._resolve_chart_min_height()
        self._card_max_height = self._resolve_card_max_height()
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
            card.setMaximumHeight(self._card_max_height)

        self.lbl_comp_summary.setMaximumHeight(max(int((22 if short_mode else 26) * self.sf), 20))
        self.lbl_tcra_summary.setMaximumHeight(max(int((24 if short_mode else 28) * self.sf), 22))
        self.lbl_local_overview.setMaximumHeight(max(int((28 if short_mode else 34) * self.sf), 24))
        self.lbl_read_source.setMaximumHeight(max(int((28 if short_mode else 34) * self.sf), 24))
        self.lbl_agenda_summary.setMaximumHeight(max(int((28 if short_mode else 34) * self.sf), 24))
        self.lbl_tcra_agenda.setMaximumHeight(max(int((24 if short_mode else 30) * self.sf), 22))

        self.comp_web_host.setMinimumHeight(self._chart_min_height)
        self.tcra_web_host.setMinimumHeight(self._chart_min_height)
        if self.comp_web is not None:
            self.comp_web.setMinimumHeight(self._chart_min_height)
        if self.tcra_web is not None:
            self.tcra_web.setMinimumHeight(self._chart_min_height)
        placeholder_container = getattr(self, "compensacoes_web_placeholder_container", None)
        if placeholder_container is not None:
            placeholder_container.setMinimumHeight(self._chart_min_height)
        placeholder_container = getattr(self, "tcra_web_placeholder_container", None)
        if placeholder_container is not None:
            placeholder_container.setMinimumHeight(self._chart_min_height)

        if compact_mode and self.compensation_details_panel.isVisible():
            self._set_compensation_details_visible(False)

    def _build_dashboard_host(self, kind: str) -> QWidget:
        host = QWidget(self)
        host.setMinimumHeight(self._chart_min_height)
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        placeholder_container = QWidget(host)
        placeholder_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        placeholder_layout = QVBoxLayout(placeholder_container)
        placeholder_layout.setContentsMargins(0, 0, 0, 0)
        placeholder_layout.setSpacing(0)

        placeholder = QLabel("Os gráficos serão carregados quando esta visão for aberta.")
        placeholder.setWordWrap(True)
        placeholder.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        placeholder.setObjectName("FormStateLabel")
        placeholder.setMaximumWidth(int(420 * self.sf))
        placeholder_container.setMinimumHeight(self._chart_min_height)

        placeholder_layout.addWidget(placeholder, 0, Qt.AlignTop)
        placeholder_layout.addStretch(1)
        host_layout.addWidget(placeholder_container, 1)

        setattr(self, f"{kind}_web_host_layout", host_layout)
        setattr(self, f"{kind}_web_placeholder_container", placeholder_container)
        setattr(self, f"{kind}_web_placeholder", placeholder)
        return host

    def _ensure_current_scope_webview(self, *_args) -> None:
        if self.scope_tabs.currentWidget() is self.tcra_page:
            self._ensure_dashboard_webview("tcra")
            return
        self._ensure_dashboard_webview("compensacoes")

    def _ensure_dashboard_webview(self, kind: str) -> QWebEngineView:
        current_web = self.comp_web if kind == "compensacoes" else self.tcra_web
        if current_web is not None:
            return current_web

        host_layout = getattr(self, f"{kind}_web_host_layout")
        placeholder = getattr(self, f"{kind}_web_placeholder", None)
        placeholder_container = getattr(self, f"{kind}_web_placeholder_container", None)
        if placeholder_container is not None:
            host_layout.removeWidget(placeholder_container)
            placeholder_container.hide()
            placeholder_container.deleteLater()
            setattr(self, f"{kind}_web_placeholder_container", None)
        if placeholder is not None:
            placeholder.hide()
            placeholder.deleteLater()
            setattr(self, f"{kind}_web_placeholder", None)

        web = self._build_dashboard_webview(kind)
        host_layout.addWidget(web, 1)
        if kind == "compensacoes":
            self.comp_web = web
            self.web = web
        else:
            self.tcra_web = web
        return web

    def _build_dashboard_webview(self, kind: str) -> QWebEngineView:
        web = QWebEngineView()
        web.setMinimumHeight(self._chart_min_height)
        web.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
        target = self._ensure_dashboard_webview(kind)
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
        self._refresh_compensation_summary()
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
        if active_web is None:
            return "", ""
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

