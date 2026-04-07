from __future__ import annotations

from calendar import monthrange
import os
from datetime import date, datetime
from typing import Optional

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QMenu,
)

from app.application.use_cases.tcra_module_operations import TcraModuleOperations
from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.tcra_excel_service import TcraExcelService
from app.services.tcra_records_service import (
    AGENDA_SCOPE_30D,
    AGENDA_SCOPE_7D,
    AGENDA_SCOPE_HOJE,
    AGENDA_SCOPE_PENDENTES,
    AGENDA_SCOPE_TODOS,
    AGENDA_SCOPE_VENCIDOS,
    QUICK_FILTER_ALERTAS,
    QUICK_FILTER_ALL,
    QUICK_FILTER_PROXIMOS,
    QUICK_FILTER_SEM_NUMERO,
    QUICK_FILTER_SEM_RESPONSAVEL,
    STATUS_ARQUIVADO,
    STATUS_CUMPRIDO,
    STATUS_EM_ACOMPANHAMENTO,
    STATUS_PRAZO_VENCIDO,
    STATUS_RELATORIO_PENDENTE,
    STATUS_SEM_STATUS,
    STATUS_SEM_VALIDADE,
    STATUS_TODOS,
    TcraAgendaItem,
    TcraQualityQueueItem,
    UPCOMING_REPORT_WINDOW_DAYS,
    build_filter_facets,
    normalize_orgao_label,
    normalize_status_label,
    resolve_operational_status,
    tcra_has_prazo_vencido,
    tcra_has_relatorio_pendente,
    tcra_is_mpsp_related,
)
from app.services.tcra_sqlite_service import TcraSqliteService
from app.ui.components.dialogs import TCRA_EVENT_PRESETS, TcraBulkActionDialog, TcraEventoEditorDialog, TcraImportPreviewDialog
from app.ui.components.ui_utils import msg_confirm
from app.ui.components.widgets import CheckableComboBox, KPICard
from app.ui.tabs.tcra_tab_form_support import (
    TcraFormPreviewData,
    build_form_preview_data,
    capture_form_state_snapshot,
    issue_supports_safe_fix,
    resolve_issue_focus_field,
    resolve_safe_fix_updates,
    restore_form_eventos_snapshot,
)
from app.ui.tabs.tcra_tab_support import (
    agenda_row_color,
    build_event_lines,
    build_event_timeline_text,
    build_record_panel_data,
    build_row_hint,
    format_date as _format_date,
    format_date_text as _format_date_text,
    neutral_row_background,
    neutral_row_foreground,
    quality_row_color,
    status_badge_palette,
    stringify as _stringify,
)
from app.ui.tabs.tcra_tab_workspace import (
    AGENDA_SCOPE_LABELS as WORKSPACE_AGENDA_SCOPE_LABELS,
    TcraWorkspaceFilters,
    TcraWorkspaceSnapshot,
    build_workspace_snapshot,
)
from app.utils.logger import get_logger


logger = get_logger("UI.TCRA")


class TcraTab(QWidget):
    FORM_CLEAN_TEXT = "Sem alterações"
    FORM_DIRTY_TEXT = "Alterações pendentes"
    FORM_DRAFT_TEXT = "Rascunho automatico salvo"
    IMPORT_STATUS_IDLE_TEXT = "Importação: nenhuma revisão nesta sessão."
    OVERVIEW_SUMMARY_HEIGHT = 88
    OVERVIEW_SUMMARY_WITH_IMPORT_HEIGHT = 114
    OVERVIEW_DETAIL_HEIGHT = 232
    OVERVIEW_PREVIEW_LIMIT = 3
    FORM_DRAFT_AUTOSAVE_MS = 700
    AGENDA_SCOPE_LABELS = dict(WORKSPACE_AGENDA_SCOPE_LABELS)

    def __init__(self, parent=None, *, sqlite_service: TcraSqliteService | None = None, today: date | None = None):
        super().__init__(parent)
        self.main_window = parent
        self.sf = getattr(parent, "scale_factor", 1.0)
        db_path = getattr(getattr(parent, "persistence_service", None), "db_path", None)
        self.sqlite_service = sqlite_service or TcraSqliteService(db_path=db_path)
        self.today = today or date.today()
        self.module_operations = TcraModuleOperations(
            self.sqlite_service,
            today=self.today,
            audit_service_provider=lambda: getattr(self.main_window, "audit_service", None)
            if self.main_window is not None
            else None,
            session_path_provider=self._current_session_path,
            access_session_provider=lambda: getattr(self.main_window, "access_session", None)
            if self.main_window is not None
            else None,
            access_service=getattr(getattr(self.main_window, "authoritative_persistence", None), "access_service", None)
            if self.main_window is not None
            else None,
        )
        self.all_tcras: list[Tcra] = []
        self.base_filtered_tcras: list[Tcra] = []
        self.filtered_tcras: list[Tcra] = []
        self.agenda_items: list[TcraAgendaItem] = []
        self.quality_items: list[TcraQualityQueueItem] = []
        self.search_index: dict[str, str] = {}
        self.selected_uid: str = ""
        self.current_form_uid: str = ""
        self.form_eventos: list[TcraEvento] = []
        self.quick_filter_mode = QUICK_FILTER_ALL
        self.quick_filter_buttons: dict[str, QPushButton] = {}
        self.agenda_scope = AGENDA_SCOPE_HOJE
        self.agenda_scope_buttons: dict[str, QPushButton] = {}
        self._pending_filter_restore = self._load_saved_filter_state()
        self._tracking_suspended = 0
        self._clean_form_state: dict[str, object] | None = None
        self._pending_event_audit: dict[str, object] | None = None
        self._restoring_selection = False
        self._advanced_filters_visible = False
        self._agenda_expanded = False
        self._quality_expanded = False
        self._bulk_selection_context = False
        self._bulk_selected_uids: list[str] = []
        self._global_search_mode = False
        self._workspace_snapshot: TcraWorkspaceSnapshot | None = None
        self._form_preview_data: TcraFormPreviewData | None = None
        self._form_field_widgets: dict[str, object] = {}
        self._pending_new_form_draft = self._load_saved_form_draft()
        self._last_draft_saved_payload: dict[str, object] | None = None
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._save_form_draft)
        self._setup_ui()
        self.refresh_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        layout.setSpacing(int(10 * self.sf))

        self.workspace_tabs = QTabWidget(self)
        self.workspace_tabs.setDocumentMode(True)
        self.list_page = QWidget(self)
        self.list_page_layout = QVBoxLayout(self.list_page)
        self.list_page_layout.setContentsMargins(0, 0, 0, 0)
        self.list_page_layout.setSpacing(int(10 * self.sf))
        self.editor_page = QWidget(self)
        self.editor_page_layout = QVBoxLayout(self.editor_page)
        self.editor_page_layout.setContentsMargins(0, 0, 0, 0)
        self.editor_page_layout.setSpacing(int(8 * self.sf))

        self.metrics_frame = QFrame(self)
        self.metrics_frame.setVisible(False)
        cards_layout = QGridLayout(self.metrics_frame)
        cards_layout.setHorizontalSpacing(int(10 * self.sf))
        cards_layout.setVerticalSpacing(int(10 * self.sf))
        self.card_total = KPICard("Total TCRAs", "0", "#2176ff")
        self.card_ativos = KPICard("Ativos", "0", "#ff9800")
        self.card_cumpridos = KPICard("Cumpridos", "0", "#2e7d32")
        self.card_alertas = KPICard("Alertas", "0", "#d32f2f")
        self.card_proximos = KPICard("Próx. 30 Dias", "0", "#fb8c00")
        self.card_mpsp = KPICard("MPSP", "0", "#5e35b1")
        for index, card in enumerate(
            [
                self.card_total,
                self.card_ativos,
                self.card_cumpridos,
                self.card_alertas,
                self.card_proximos,
                self.card_mpsp,
            ]
        ):
            card.setMaximumHeight(int(84 * self.sf))
            cards_layout.addWidget(card, 0, index)
        self.list_page_layout.addWidget(self.metrics_frame)

        self.lbl_context = QLabel("Banco local de TCRA: aguardando leitura inicial.")
        self.lbl_context.setWordWrap(False)
        self.lbl_context.setObjectName("FormStateLabel")
        self.lbl_radar_summary = QLabel("Sem dados operacionais no momento.")
        self.lbl_radar_summary.setWordWrap(True)
        self.lbl_radar_summary.setObjectName("FormStateLabel")
        self.lbl_radar_summary.setVisible(False)
        self.lbl_data_quality = QLabel("Qualidade cadastral: aguardando leitura.")
        self.lbl_data_quality.setWordWrap(True)
        self.lbl_data_quality.setObjectName("FormStateLabel")
        self.lbl_data_quality.setVisible(False)
        self.lbl_upcoming_reports = QLabel("Próximos relatórios: --")
        self.lbl_upcoming_reports.setWordWrap(True)
        self.lbl_upcoming_reports.setObjectName("FormStateLabel")
        self.lbl_upcoming_reports.setVisible(False)
        self.lbl_import_status = QLabel(self.IMPORT_STATUS_IDLE_TEXT)
        self.lbl_import_status.setWordWrap(True)
        self.lbl_import_status.setObjectName("FormStateLabel")
        self.lbl_import_status.setVisible(False)
        self.summary_frame = QFrame(self)
        summary_layout = QVBoxLayout(self.summary_frame)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(int(6 * self.sf))
        summary_actions = QHBoxLayout()
        summary_actions.setSpacing(int(8 * self.sf))
        self.btn_summary_inbox = QPushButton("Inbox (0)")
        self.btn_summary_inbox.setProperty("kind", "secondary")
        self.btn_summary_quality = QPushButton("Qualidade (0)")
        self.btn_summary_quality.setProperty("kind", "secondary")
        self.btn_summary_upcoming = QPushButton(f"Próx. {UPCOMING_REPORT_WINDOW_DAYS}d")
        self.btn_summary_upcoming.setProperty("kind", "secondary")
        summary_actions.addWidget(self.lbl_context, 1)
        summary_actions.addWidget(self.btn_summary_inbox)
        summary_actions.addWidget(self.btn_summary_quality)
        summary_actions.addWidget(self.btn_summary_upcoming)
        summary_layout.addLayout(summary_actions)
        summary_layout.addWidget(self.lbl_import_status)
        self.list_page_layout.addWidget(self.summary_frame)

        self.overview_tabs = QTabWidget(self)
        self.overview_tabs.setDocumentMode(True)

        record_page = QWidget(self)
        record_layout = QVBoxLayout(record_page)
        record_layout.setContentsMargins(10, 10, 10, 10)
        record_layout.setSpacing(int(8 * self.sf))
        record_header = QHBoxLayout()
        record_header.setSpacing(int(6 * self.sf))
        self.lbl_record_title = QLabel("Nenhum TCRA selecionado")
        self.lbl_record_title.setObjectName("FormStateLabel")
        self.btn_record_edit = QPushButton("Editar cadastro")
        self.btn_record_edit.setProperty("kind", "primary")
        self.btn_record_edit.setEnabled(False)
        record_header.addWidget(self.lbl_record_title, 1)
        record_header.addWidget(self.btn_record_edit)
        record_layout.addLayout(record_header)

        self.lbl_record_meta = QLabel("Selecione um TCRA na grade para ver detalhes.")
        self.lbl_record_meta.setWordWrap(True)
        self.lbl_record_meta.setObjectName("FormStateLabel")
        record_layout.addWidget(self.lbl_record_meta)

        self.record_details = QPlainTextEdit(self)
        self.record_details.setReadOnly(True)
        self.record_details.setPlaceholderText("Os detalhes do termo selecionado aparecerao aqui.")
        record_layout.addWidget(self.record_details, 1)

        self.lbl_record_timeline_title = QLabel("Eventos recentes")
        self.lbl_record_timeline_title.setObjectName("FormStateLabel")
        record_layout.addWidget(self.lbl_record_timeline_title)
        self.record_timeline = QPlainTextEdit(self)
        self.record_timeline.setReadOnly(True)
        self.record_timeline.setMaximumHeight(int(150 * self.sf))
        self.record_timeline.setPlaceholderText("A timeline recente do termo aparecera aqui.")
        record_layout.addWidget(self.record_timeline)

        agenda_page = QWidget(self)
        agenda_layout = QVBoxLayout(agenda_page)
        agenda_layout.setContentsMargins(10, 10, 10, 10)
        agenda_layout.setSpacing(int(6 * self.sf))
        agenda_header = QHBoxLayout()
        agenda_header.setSpacing(int(6 * self.sf))
        self.lbl_agenda_summary = QLabel("Nenhuma pendencia prioritaria no recorte atual.")
        self.lbl_agenda_summary.setWordWrap(True)
        self.lbl_agenda_summary.setObjectName("FormStateLabel")
        self.btn_agenda_view_all = QPushButton("Ver tudo")
        self.btn_agenda_view_all.setProperty("kind", "secondary")
        agenda_header.addWidget(self.lbl_agenda_summary, 1)
        agenda_header.addWidget(self.btn_agenda_view_all)
        agenda_scope_layout = QHBoxLayout()
        agenda_scope_layout.setSpacing(int(6 * self.sf))
        agenda_scope_layout.addWidget(QLabel("Janela de trabalho:"))
        for scope, label in self.AGENDA_SCOPE_LABELS.items():
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("kind", "secondary")
            button.clicked.connect(lambda _checked=False, selected_scope=scope: self._set_agenda_scope(selected_scope))
            self.agenda_scope_buttons[scope] = button
            agenda_scope_layout.addWidget(button)
        if AGENDA_SCOPE_HOJE in self.agenda_scope_buttons:
            self.agenda_scope_buttons[AGENDA_SCOPE_HOJE].setChecked(True)
        agenda_scope_layout.addStretch(1)
        self.agenda_table = QTableWidget(0, 4, self)
        self.agenda_table.setHorizontalHeaderLabels(["Prioridade", "Termo", "Local", "Acao"])
        self.agenda_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.agenda_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.agenda_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.agenda_table.setAlternatingRowColors(True)
        self.agenda_table.verticalHeader().setVisible(False)
        self.agenda_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.agenda_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.agenda_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.agenda_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        agenda_layout.addLayout(agenda_header)
        agenda_layout.addLayout(agenda_scope_layout)
        agenda_layout.addWidget(self.agenda_table)

        quality_page = QWidget(self)
        quality_layout = QVBoxLayout(quality_page)
        quality_layout.setContentsMargins(10, 10, 10, 10)
        quality_layout.setSpacing(int(6 * self.sf))
        quality_header = QHBoxLayout()
        quality_header.setSpacing(int(6 * self.sf))
        self.lbl_quality_summary = QLabel("Nenhuma pendencia cadastral no recorte atual.")
        self.lbl_quality_summary.setWordWrap(True)
        self.lbl_quality_summary.setObjectName("FormStateLabel")
        self.btn_quality_view_all = QPushButton("Ver tudo")
        self.btn_quality_view_all.setProperty("kind", "secondary")
        quality_header.addWidget(self.lbl_quality_summary, 1)
        quality_header.addWidget(self.btn_quality_view_all)
        self.quality_table = QTableWidget(0, 4, self)
        self.quality_table.setHorizontalHeaderLabels(["Severidade", "Termo", "Local", "Revisao"])
        self.quality_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.quality_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.quality_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.quality_table.setAlternatingRowColors(True)
        self.quality_table.verticalHeader().setVisible(False)
        self.quality_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.quality_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.quality_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.quality_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        quality_layout.addLayout(quality_header)
        quality_layout.addWidget(self.quality_table)

        self.overview_tabs.addTab(record_page, "Registro")
        self.overview_tabs.addTab(agenda_page, "Inbox (0)")
        self.overview_tabs.addTab(quality_page, "Qualidade (0)")
        self.overview_panel = QFrame(self)
        self.overview_panel.setMinimumWidth(int(360 * self.sf))
        self.overview_panel.setMaximumWidth(int(520 * self.sf))
        overview_panel_layout = QVBoxLayout(self.overview_panel)
        overview_panel_layout.setContentsMargins(0, 0, 0, 0)
        overview_panel_layout.setSpacing(int(6 * self.sf))
        overview_header = QHBoxLayout()
        overview_header.setSpacing(int(8 * self.sf))
        self.lbl_overview_title = QLabel("Inbox operacional")
        self.lbl_overview_title.setObjectName("FormStateLabel")
        self.btn_close_overview = QPushButton("Fechar painel")
        self.btn_close_overview.setProperty("kind", "secondary")
        overview_header.addWidget(self.lbl_overview_title)
        overview_header.addStretch(1)
        overview_header.addWidget(self.btn_close_overview)
        overview_panel_layout.addLayout(overview_header)
        overview_panel_layout.addWidget(self.overview_tabs, 1)
        self._overview_panel_visible = False

        self.list_content = QWidget(self)
        self.list_content_layout = QVBoxLayout(self.list_content)
        self.list_content_layout.setContentsMargins(0, 0, 0, 0)
        self.list_content_layout.setSpacing(int(8 * self.sf))

        filters_frame = QFrame(self)
        filters_layout = QGridLayout(filters_frame)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        filters_layout.setHorizontalSpacing(int(8 * self.sf))
        filters_layout.setVerticalSpacing(int(6 * self.sf))

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Buscar TCRA por processo, local, endereço, órgão ou observação...")
        self.search_input.setClearButtonEnabled(True)

        self.filter_status = QComboBox(self)
        self.filter_status.addItem(STATUS_TODOS)
        self.filter_orgao = CheckableComboBox("Todos os Órgãos")
        self.filter_bairro = CheckableComboBox("Todos os Bairros")
        self.filter_year = QComboBox(self)
        self.filter_year.addItem(STATUS_TODOS)

        self.chk_only_mpsp = QCheckBox("Somente MPSP")
        self.chk_only_relatorio_pendente = QCheckBox("Relatório pendente")
        self.chk_only_prazo_vencido = QCheckBox("Prazo vencido")

        self.btn_clear_filters = QPushButton("Limpar Filtros")
        self.btn_clear_filters.setProperty("kind", "secondary")
        self.btn_refresh = QPushButton("Atualizar")
        self.btn_refresh.setProperty("kind", "secondary")
        self.btn_export_excel = QPushButton("Excel")
        self.btn_export_excel.setProperty("kind", "secondary")
        self.btn_export_pdf = QPushButton("PDF")
        self.btn_export_pdf.setProperty("kind", "secondary")
        self.btn_import_legacy = QPushButton("Importar")
        self.btn_import_legacy.setProperty("kind", "secondary")
        self.btn_more_actions = QToolButton(self)
        self.btn_more_actions.setText("Mais acoes")
        self.btn_more_actions.setPopupMode(QToolButton.InstantPopup)
        self.btn_more_actions.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.more_actions_menu = QMenu(self.btn_more_actions)
        self.action_refresh = self.more_actions_menu.addAction("Atualizar TCRAs")
        self.action_select_alerts = self.more_actions_menu.addAction("Selecionar alertas")
        self.more_actions_menu.addSeparator()
        self.action_export_excel = self.more_actions_menu.addAction("Exportar relatório Excel")
        self.action_export_pdf = self.more_actions_menu.addAction("Exportar relatório PDF")
        self.more_actions_menu.addSeparator()
        self.action_import_legacy = self.more_actions_menu.addAction("Importar planilha legada")
        self.btn_more_actions.setMenu(self.more_actions_menu)

        self.lbl_results = QLabel("0 TCRAs")
        self.lbl_results.setObjectName("FormStateLabel")
        self.lbl_selection_summary = QLabel("Nenhum termo selecionado")
        self.lbl_selection_summary.setObjectName("FormStateLabel")

        self.quick_filter_group = QButtonGroup(self)
        self.quick_filter_group.setExclusive(True)
        quick_filters_layout = QHBoxLayout()
        quick_filters_layout.setSpacing(int(6 * self.sf))
        quick_filters_layout.addWidget(QLabel("Atalhos:"))
        for mode, label in [
            (QUICK_FILTER_ALL, "Todos"),
            (QUICK_FILTER_ALERTAS, "Alertas"),
            (QUICK_FILTER_PROXIMOS, "Próx. 30d"),
            (QUICK_FILTER_SEM_NUMERO, "Sem número"),
            (QUICK_FILTER_SEM_RESPONSAVEL, "Sem responsável"),
        ]:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("kind", "secondary")
            button.clicked.connect(lambda _checked=False, selected_mode=mode: self._set_quick_filter_mode(selected_mode))
            self.quick_filter_group.addButton(button)
            self.quick_filter_buttons[mode] = button
            quick_filters_layout.addWidget(button)
        self.quick_filter_buttons[QUICK_FILTER_ALL].setChecked(True)
        quick_filters_layout.addStretch(1)
        filters_layout.addLayout(quick_filters_layout, 0, 0, 1, 7)

        self.lbl_search = QLabel("Busca:")
        filters_layout.addWidget(self.lbl_search, 1, 0)
        filters_layout.addWidget(self.search_input, 1, 1, 1, 3)
        filters_layout.addWidget(QLabel("Status:"), 1, 4)
        filters_layout.addWidget(self.filter_status, 1, 5)
        self.btn_toggle_advanced_filters = QPushButton("Mais filtros")
        self.btn_toggle_advanced_filters.setProperty("kind", "secondary")
        self.btn_toggle_advanced_filters.setCheckable(True)
        filters_layout.addWidget(self.btn_toggle_advanced_filters, 1, 6)

        self.advanced_filters_frame = QFrame(self)
        advanced_filters_layout = QGridLayout(self.advanced_filters_frame)
        advanced_filters_layout.setContentsMargins(0, 0, 0, 0)
        advanced_filters_layout.setHorizontalSpacing(int(8 * self.sf))
        advanced_filters_layout.setVerticalSpacing(int(6 * self.sf))
        advanced_filters_layout.addWidget(QLabel("Órgão:"), 0, 0)
        advanced_filters_layout.addWidget(self.filter_orgao, 0, 1)
        advanced_filters_layout.addWidget(QLabel("Bairro:"), 0, 2)
        advanced_filters_layout.addWidget(self.filter_bairro, 0, 3)
        advanced_filters_layout.addWidget(QLabel("Ano:"), 0, 4)
        advanced_filters_layout.addWidget(self.filter_year, 0, 5)
        advanced_filters_layout.addWidget(self.chk_only_mpsp, 1, 0)
        advanced_filters_layout.addWidget(self.chk_only_relatorio_pendente, 1, 1)
        advanced_filters_layout.addWidget(self.chk_only_prazo_vencido, 1, 2)
        advanced_filters_layout.setColumnStretch(3, 1)
        advanced_filters_layout.setColumnStretch(5, 1)
        filters_layout.addWidget(self.advanced_filters_frame, 2, 0, 1, 7)

        primary_actions_layout = QHBoxLayout()
        primary_actions_layout.setSpacing(int(8 * self.sf))
        self.btn_open_selected = QPushButton("Editar selecionado")
        self.btn_open_selected.setProperty("kind", "primary")
        self.btn_open_selected.setEnabled(False)
        self.btn_bulk_alerts = QPushButton("Selecionar alertas")
        self.btn_bulk_alerts.setProperty("kind", "secondary")
        self.btn_clear_selection = QPushButton("Limpar Seleção")
        self.btn_clear_selection.setProperty("kind", "secondary")
        self.btn_clear_selection.setEnabled(False)
        self.btn_bulk_action = QPushButton("Ações em lote")
        self.btn_bulk_action.setProperty("kind", "secondary")
        self.btn_bulk_action.setEnabled(False)
        primary_actions_layout.addWidget(self.lbl_selection_summary)
        primary_actions_layout.addWidget(self.btn_open_selected)
        primary_actions_layout.addWidget(self.btn_bulk_action)
        primary_actions_layout.addWidget(self.btn_clear_selection)
        primary_actions_layout.addStretch(1)
        self.selection_actions_frame = QFrame(self)
        self.selection_actions_frame.setVisible(False)
        self.selection_actions_frame.setLayout(primary_actions_layout)
        filters_layout.addWidget(self.selection_actions_frame, 3, 0, 1, 7)

        secondary_actions_layout = QHBoxLayout()
        secondary_actions_layout.setSpacing(int(8 * self.sf))
        self.btn_new_list = QPushButton("Novo TCRA")
        self.btn_new_list.setProperty("kind", "primary")
        secondary_actions_layout.addWidget(self.btn_new_list)
        secondary_actions_layout.addWidget(self.btn_more_actions)
        secondary_actions_layout.addStretch(1)
        secondary_actions_layout.addWidget(self.btn_clear_filters)
        secondary_actions_layout.addWidget(self.lbl_results)
        filters_layout.addLayout(secondary_actions_layout, 4, 0, 1, 7)
        self.list_content_layout.addWidget(filters_frame)

        self.table = QTableWidget(0, 8, self)
        self.table.setHorizontalHeaderLabels(
            ["Processo", "TCRA", "Local", "Status", "Prazo", "Próx. Relatório", "Órgão", "MPSP"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.list_content_layout.addWidget(self.table, 1)

        self.list_splitter = QSplitter(Qt.Horizontal, self)
        self.list_splitter.setChildrenCollapsible(False)
        self.list_splitter.addWidget(self.list_content)
        self.list_splitter.addWidget(self.overview_panel)
        self.list_splitter.setStretchFactor(0, 6)
        self.list_splitter.setStretchFactor(1, 3)
        self.list_page_layout.addWidget(self.list_splitter, 1)
        self._set_overview_panel_visible(False)

        self.editor_tabs = QTabWidget(self)
        self.editor_tabs.setDocumentMode(True)
        self.editor_tabs.setTabPosition(QTabWidget.South)

        editor_header = QHBoxLayout()
        editor_header.setSpacing(int(8 * self.sf))
        self.btn_back_to_list = QPushButton("Voltar para Lista")
        self.btn_back_to_list.setProperty("kind", "secondary")
        self.lbl_editor_context = QLabel("Cadastro: novo termo")
        self.lbl_editor_context.setObjectName("FormStateLabel")
        self.lbl_form_state = QLabel(self.FORM_CLEAN_TEXT)
        self.lbl_form_state.setObjectName("FormStateLabel")
        self.btn_new = QPushButton("Novo TCRA")
        self.btn_new.setProperty("kind", "secondary")
        self.btn_save = QPushButton("Salvar TCRA")
        self.btn_save.setProperty("kind", "primary")
        self.btn_delete = QPushButton("Excluir TCRA")
        self.btn_delete.setProperty("kind", "danger")
        editor_header.addWidget(self.lbl_editor_context)
        editor_header.addWidget(self.lbl_form_state)
        editor_header.addStretch(1)
        editor_header.addWidget(self.btn_new)
        editor_header.addWidget(self.btn_save)
        editor_header.addWidget(self.btn_delete)
        editor_header.addWidget(self.btn_back_to_list)
        self.editor_page_layout.addLayout(editor_header)

        form_page = QWidget(self)
        form_page_layout = QVBoxLayout(form_page)
        form_page_layout.setContentsMargins(0, 0, 0, 0)
        form_page_layout.setSpacing(int(6 * self.sf))

        self.form_group = QGroupBox("Cadastro / Edição de TCRA")
        form_layout = QVBoxLayout(self.form_group)
        form_layout.setContentsMargins(10, 10, 10, 10)
        form_layout.setSpacing(int(8 * self.sf))
        form_nav_layout = QHBoxLayout()
        form_nav_layout.setSpacing(int(6 * self.sf))
        form_nav_layout.addWidget(QLabel("Ir para:"))
        self.btn_section_identificacao = QPushButton("Identificação")
        self.btn_section_identificacao.setProperty("kind", "secondary")
        self.btn_section_prazos = QPushButton("Prazos")
        self.btn_section_prazos.setProperty("kind", "secondary")
        self.btn_section_acompanhamento = QPushButton("Acompanhamento")
        self.btn_section_acompanhamento.setProperty("kind", "secondary")
        self.btn_section_observacoes = QPushButton("Observações")
        self.btn_section_observacoes.setProperty("kind", "secondary")
        for button in [
            self.btn_section_identificacao,
            self.btn_section_prazos,
            self.btn_section_acompanhamento,
            self.btn_section_observacoes,
        ]:
            form_nav_layout.addWidget(button)
        form_nav_layout.addStretch(1)
        form_layout.addLayout(form_nav_layout)

        self.lbl_fix_guidance = QLabel("Correção assistida: cadastro pronto para edição.")
        self.lbl_fix_guidance.setWordWrap(True)
        self.lbl_fix_guidance.setObjectName("FormStateLabel")
        form_layout.addWidget(self.lbl_fix_guidance)
        fix_actions_layout = QHBoxLayout()
        fix_actions_layout.setSpacing(int(6 * self.sf))
        self.btn_apply_fix = QPushButton("Aplicar ajuste seguro")
        self.btn_apply_fix.setProperty("kind", "secondary")
        self.btn_focus_fix = QPushButton("Ir para o campo")
        self.btn_focus_fix.setProperty("kind", "secondary")
        self.btn_apply_fix.setVisible(False)
        self.btn_focus_fix.setVisible(False)
        fix_actions_layout.addWidget(self.btn_apply_fix)
        fix_actions_layout.addWidget(self.btn_focus_fix)
        fix_actions_layout.addStretch(1)
        form_layout.addLayout(fix_actions_layout)

        self.in_numero_processo = QLineEdit(self)
        self.in_numero_tcra = QLineEdit(self)
        self.in_local = QLineEdit(self)
        self.in_endereco = QLineEdit(self)
        self.in_bairro = QLineEdit(self)
        self.in_orgao = QLineEdit(self)
        self.in_status = QComboBox(self)
        self.in_status.setEditable(True)
        self.in_data_assinatura = QLineEdit(self)
        self.in_data_assinatura.setPlaceholderText("dd/mm/aaaa")
        self.in_prazo_final = QLineEdit(self)
        self.in_prazo_final.setPlaceholderText("dd/mm/aaaa")
        self.in_periodicidade = QLineEdit(self)
        self.in_data_ultimo_relatorio = QLineEdit(self)
        self.in_data_ultimo_relatorio.setPlaceholderText("dd/mm/aaaa")
        self.in_data_proximo_relatorio = QLineEdit(self)
        self.in_data_proximo_relatorio.setPlaceholderText("dd/mm/aaaa")
        self.in_area_m2 = QLineEdit(self)
        self.in_numero_mudas = QLineEdit(self)
        self.in_responsavel = QLineEdit(self)
        self.chk_mpsp = QCheckBox("Relacionado ao MPSP")
        self.in_inquerito = QLineEdit(self)
        self.in_servicos = QPlainTextEdit(self)
        self.in_servicos.setTabChangesFocus(True)
        self.in_servicos.setMinimumHeight(int(58 * self.sf))
        self.in_observacoes = QPlainTextEdit(self)
        self.in_observacoes.setTabChangesFocus(True)
        self.in_observacoes.setMinimumHeight(int(58 * self.sf))
        self._form_field_widgets = {
            "numero_processo": self.in_numero_processo,
            "numero_tcra": self.in_numero_tcra,
            "local": self.in_local,
            "endereco": self.in_endereco,
            "bairro": self.in_bairro,
            "orgao": self.in_orgao,
            "status": self.in_status,
            "data_assinatura": self.in_data_assinatura,
            "prazo_final": self.in_prazo_final,
            "periodicidade": self.in_periodicidade,
            "data_ultimo_relatorio": self.in_data_ultimo_relatorio,
            "data_proximo_relatorio": self.in_data_proximo_relatorio,
            "area_m2": self.in_area_m2,
            "numero_mudas": self.in_numero_mudas,
            "responsavel": self.in_responsavel,
            "mpsp": self.chk_mpsp,
            "inquerito": self.in_inquerito,
            "servicos": self.in_servicos,
            "observacoes": self.in_observacoes,
        }

        self.section_identificacao = QGroupBox("Identificação")
        identificacao_grid = QGridLayout(self.section_identificacao)
        identificacao_grid.setHorizontalSpacing(int(8 * self.sf))
        identificacao_grid.setVerticalSpacing(int(6 * self.sf))
        self._add_grid_field(identificacao_grid, 0, 0, "Processo:", self.in_numero_processo)
        self._add_grid_field(identificacao_grid, 0, 2, "Número TCRA:", self.in_numero_tcra)
        self._add_grid_field(identificacao_grid, 1, 0, "Local:", self.in_local)
        self._add_grid_field(identificacao_grid, 1, 2, "Endereço:", self.in_endereco)
        self._add_grid_field(identificacao_grid, 2, 0, "Bairro:", self.in_bairro)
        form_layout.addWidget(self.section_identificacao)

        self.section_prazos = QGroupBox("Prazos e relatórios")
        prazos_grid = QGridLayout(self.section_prazos)
        prazos_grid.setHorizontalSpacing(int(8 * self.sf))
        prazos_grid.setVerticalSpacing(int(6 * self.sf))
        self._add_grid_field(prazos_grid, 0, 0, "Status:", self.in_status)
        self._add_grid_field(prazos_grid, 0, 2, "Assinatura:", self.in_data_assinatura)
        self._add_grid_field(prazos_grid, 1, 0, "Prazo final:", self.in_prazo_final)
        self._add_grid_field(prazos_grid, 1, 2, "Periodicidade (meses):", self.in_periodicidade)
        self._add_grid_field(prazos_grid, 2, 0, "Último relatório:", self.in_data_ultimo_relatorio)
        self._add_grid_field(prazos_grid, 2, 2, "Próximo relatório:", self.in_data_proximo_relatorio)
        form_layout.addWidget(self.section_prazos)

        self.section_acompanhamento = QGroupBox("Acompanhamento")
        acompanhamento_grid = QGridLayout(self.section_acompanhamento)
        acompanhamento_grid.setHorizontalSpacing(int(8 * self.sf))
        acompanhamento_grid.setVerticalSpacing(int(6 * self.sf))
        self._add_grid_field(acompanhamento_grid, 0, 0, "Órgão:", self.in_orgao)
        self._add_grid_field(acompanhamento_grid, 0, 2, "Responsável:", self.in_responsavel)
        self._add_grid_field(acompanhamento_grid, 1, 0, "Area (m2):", self.in_area_m2)
        self._add_grid_field(acompanhamento_grid, 1, 2, "Número de mudas:", self.in_numero_mudas)
        self._add_grid_field(acompanhamento_grid, 2, 0, "Inquérito civil:", self.in_inquerito)
        acompanhamento_grid.addWidget(self.chk_mpsp, 2, 2, 1, 2)
        form_layout.addWidget(self.section_acompanhamento)

        self.section_observacoes = QGroupBox("Observações e serviços")
        observacoes_form = QFormLayout(self.section_observacoes)
        observacoes_form.setContentsMargins(10, 10, 10, 10)
        observacoes_form.setHorizontalSpacing(10)
        observacoes_form.setVerticalSpacing(8)
        observacoes_form.addRow("Serviços exigidos:", self.in_servicos)
        observacoes_form.addRow("Observações:", self.in_observacoes)
        form_layout.addWidget(self.section_observacoes)

        self.form_scroll = QScrollArea(self)
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setFrameShape(QFrame.NoFrame)
        self.form_scroll.setWidget(self.form_group)
        form_page_layout.addWidget(self.form_scroll)

        preview_page = QWidget(self)
        preview_layout = QVBoxLayout(preview_page)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(int(8 * self.sf))
        self.lbl_selected_title = QLabel("Preview operacional do termo")
        self.lbl_selected_title.setObjectName("FormStateLabel")
        preview_layout.addWidget(self.lbl_selected_title)

        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Preencha ou selecione um TCRA para ver o resumo operacional.")
        preview_layout.addWidget(self.details, 1)

        events_page = QWidget(self)
        events_layout = QVBoxLayout(events_page)
        events_layout.setContentsMargins(0, 0, 0, 0)
        events_layout.setSpacing(int(8 * self.sf))
        events_header = QHBoxLayout()
        self.lbl_events_title = QLabel("Linha do tempo de eventos")
        self.lbl_events_title.setObjectName("FormStateLabel")
        events_header.addWidget(self.lbl_events_title)
        events_header.addStretch(1)
        self.btn_add_event = QPushButton("Adicionar Evento")
        self.btn_add_event.setProperty("kind", "secondary")
        self.btn_edit_event = QPushButton("Editar Evento")
        self.btn_edit_event.setProperty("kind", "secondary")
        self.btn_delete_event = QPushButton("Excluir Evento")
        self.btn_delete_event.setProperty("kind", "secondary")
        events_header.addWidget(self.btn_add_event)
        events_header.addWidget(self.btn_edit_event)
        events_header.addWidget(self.btn_delete_event)
        events_layout.addLayout(events_header)

        self.lbl_event_hint = QLabel(
            "Use presets para registrar relatórios, vistorias e cumprimentos. O último evento pode atualizar status e prazos do formulário."
        )
        self.lbl_event_hint.setWordWrap(True)
        self.lbl_event_hint.setObjectName("FormStateLabel")
        events_layout.addWidget(self.lbl_event_hint)

        self.timeline_preview = QPlainTextEdit(self)
        self.timeline_preview.setReadOnly(True)
        self.timeline_preview.setPlaceholderText("A timeline do termo aparecera aqui conforme os eventos forem registrados.")
        self.timeline_preview.setMaximumHeight(int(128 * self.sf))
        events_layout.addWidget(self.timeline_preview)

        quick_event_layout = QHBoxLayout()
        quick_event_layout.setSpacing(int(6 * self.sf))
        quick_event_layout.addWidget(QLabel("Atalhos de evento:"))
        self.btn_quick_report = QPushButton("Relatório")
        self.btn_quick_report.setProperty("kind", "secondary")
        self.btn_quick_vistoria = QPushButton("Vistoria")
        self.btn_quick_vistoria.setProperty("kind", "secondary")
        self.btn_quick_despacho = QPushButton("Despacho")
        self.btn_quick_despacho.setProperty("kind", "secondary")
        self.btn_quick_done = QPushButton("Cumprimento")
        self.btn_quick_done.setProperty("kind", "secondary")
        for button in [
            self.btn_quick_report,
            self.btn_quick_vistoria,
            self.btn_quick_despacho,
            self.btn_quick_done,
        ]:
            quick_event_layout.addWidget(button)
        quick_event_layout.addStretch(1)
        events_layout.addLayout(quick_event_layout)

        self.events_table = QTableWidget(0, 6, self)
        self.events_table.setHorizontalHeaderLabels(["Seq.", "Data", "Tipo", "Descricao", "Prazo", "Status"])
        self.events_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.events_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.events_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.events_table.setAlternatingRowColors(True)
        self.events_table.verticalHeader().setVisible(False)
        self.events_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.events_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.events_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.events_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.events_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.events_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        events_layout.addWidget(self.events_table, 1)

        editor_splitter = QSplitter(Qt.Vertical, self)
        editor_splitter.setChildrenCollapsible(False)
        editor_splitter.addWidget(self.form_scroll)
        self.editor_tabs.addTab(preview_page, "Preview")
        self.editor_tabs.addTab(events_page, "Eventos")
        editor_splitter.addWidget(self.editor_tabs)
        editor_splitter.setStretchFactor(0, 5)
        editor_splitter.setStretchFactor(1, 3)
        editor_splitter.setSizes([max(int(560 * self.sf), 500), max(int(300 * self.sf), 260)])
        self.editor_page_layout.addWidget(editor_splitter, 1)

        self.workspace_tabs.addTab(self.list_page, "Lista")
        self.workspace_tabs.addTab(self.editor_page, "Cadastro")
        layout.addWidget(self.workspace_tabs, 1)

        self.search_input.textChanged.connect(self._apply_filters)
        self.filter_status.currentTextChanged.connect(self._apply_filters)
        self.filter_orgao.selectionChanged.connect(self._apply_filters)
        self.filter_bairro.selectionChanged.connect(self._apply_filters)
        self.filter_year.currentTextChanged.connect(self._apply_filters)
        self.chk_only_mpsp.toggled.connect(self._apply_filters)
        self.chk_only_relatorio_pendente.toggled.connect(self._apply_filters)
        self.chk_only_prazo_vencido.toggled.connect(self._apply_filters)
        self.btn_clear_filters.clicked.connect(self.clear_filters)
        self.btn_refresh.clicked.connect(self._request_refresh)
        self.btn_export_excel.clicked.connect(self.export_excel_report)
        self.btn_export_pdf.clicked.connect(self.export_pdf_report)
        self.btn_import_legacy.clicked.connect(self.import_legacy_workbook)
        self.action_refresh.triggered.connect(self._request_refresh)
        self.action_select_alerts.triggered.connect(self._select_alert_rows)
        self.action_export_excel.triggered.connect(self.export_excel_report)
        self.action_export_pdf.triggered.connect(self.export_pdf_report)
        self.action_import_legacy.triggered.connect(self.import_legacy_workbook)
        self.btn_new_list.clicked.connect(self.new_tcra)
        self.btn_open_selected.clicked.connect(self._open_selected_record_in_editor)
        self.btn_bulk_alerts.clicked.connect(self._select_alert_rows)
        self.btn_clear_selection.clicked.connect(self._clear_table_selection)
        self.btn_bulk_action.clicked.connect(self.apply_bulk_action)
        self.btn_back_to_list.clicked.connect(self._switch_to_list_view)
        self.btn_record_edit.clicked.connect(self._open_selected_record_in_editor)
        self.btn_summary_inbox.clicked.connect(self._open_inbox_overview)
        self.btn_summary_quality.clicked.connect(self._open_quality_overview)
        self.btn_summary_upcoming.clicked.connect(self._open_upcoming_overview)
        self.btn_agenda_view_all.clicked.connect(self._toggle_agenda_preview)
        self.btn_quality_view_all.clicked.connect(self._toggle_quality_preview)
        self.btn_close_overview.clicked.connect(lambda: self._set_overview_panel_visible(False))
        self.btn_toggle_advanced_filters.clicked.connect(self._toggle_advanced_filters)
        self.overview_tabs.currentChanged.connect(self._update_overview_panel_height)
        self.btn_new.clicked.connect(self.new_tcra)
        self.btn_save.clicked.connect(self.save_tcra)
        self.btn_delete.clicked.connect(self.delete_tcra)
        self.btn_add_event.clicked.connect(self.add_event)
        self.btn_edit_event.clicked.connect(self.edit_selected_event)
        self.btn_delete_event.clicked.connect(self.delete_selected_event)
        self.btn_section_identificacao.clicked.connect(lambda: self._focus_form_widget(self.in_numero_processo))
        self.btn_section_prazos.clicked.connect(lambda: self._focus_form_widget(self.in_prazo_final))
        self.btn_section_acompanhamento.clicked.connect(lambda: self._focus_form_widget(self.in_orgao))
        self.btn_section_observacoes.clicked.connect(lambda: self._focus_form_widget(self.in_servicos))
        self.btn_apply_fix.clicked.connect(self._apply_safe_fix)
        self.btn_focus_fix.clicked.connect(self._focus_primary_issue)
        self.agenda_table.itemSelectionChanged.connect(self._select_from_agenda)
        self.quality_table.itemSelectionChanged.connect(self._select_from_quality_queue)
        self.btn_quick_report.clicked.connect(lambda: self._add_event_with_preset("relatorio_entregue"))
        self.btn_quick_vistoria.clicked.connect(lambda: self._add_event_with_preset("vistoria"))
        self.btn_quick_despacho.clicked.connect(lambda: self._add_event_with_preset("despacho"))
        self.btn_quick_done.clicked.connect(lambda: self._add_event_with_preset("cumprimento"))
        self.table.itemSelectionChanged.connect(self._refresh_selection)
        self.table.itemDoubleClicked.connect(lambda *_args: self._open_selected_record_in_editor())
        self.events_table.itemSelectionChanged.connect(self._refresh_event_actions)
        self._connect_form_tracking()
        self._set_record_panel_placeholder()
        self._set_advanced_filters_visible(False)

    def _add_grid_field(self, grid: QGridLayout, row: int, column: int, label_text: str, widget):
        grid.addWidget(QLabel(label_text), row, column)
        grid.addWidget(widget, row, column + 1)

    def _connect_form_tracking(self):
        widgets = [
            self.in_numero_processo,
            self.in_numero_tcra,
            self.in_local,
            self.in_endereco,
            self.in_bairro,
            self.in_orgao,
            self.in_data_assinatura,
            self.in_prazo_final,
            self.in_periodicidade,
            self.in_data_ultimo_relatorio,
            self.in_data_proximo_relatorio,
            self.in_area_m2,
            self.in_numero_mudas,
            self.in_responsavel,
            self.in_inquerito,
        ]
        for widget in widgets:
            widget.textChanged.connect(self._on_form_changed)

        self.in_status.currentTextChanged.connect(self._on_form_changed)
        self.chk_mpsp.toggled.connect(self._on_form_changed)
        self.in_servicos.textChanged.connect(self._on_form_changed)
        self.in_observacoes.textChanged.connect(self._on_form_changed)

    def apply_theme(self, theme: dict):
        for card in [
            self.card_total,
            self.card_ativos,
            self.card_cumpridos,
            self.card_alertas,
            self.card_proximos,
            self.card_mpsp,
        ]:
            card.update_style(theme)
        self._repaint_table_styles()
        self._repaint_agenda_styles()
        self._repaint_quality_styles()

    def _is_dark_mode(self) -> bool:
        return bool(getattr(self.main_window, "is_dark_mode", False))

    def _neutral_row_background(self, row_index: int) -> QColor:
        return neutral_row_background(row_index=row_index, is_dark_mode=self._is_dark_mode())

    def _neutral_row_foreground(self) -> QColor:
        return neutral_row_foreground(is_dark_mode=self._is_dark_mode())

    def _apply_item_palette(
        self,
        item: QTableWidgetItem,
        background: QColor | None,
        *,
        row_index: int = 0,
        foreground: QColor | None = None,
    ):
        if background is None:
            item.setBackground(self._neutral_row_background(row_index))
            item.setForeground(foreground or self._neutral_row_foreground())
            return
        item.setBackground(background)
        if foreground is not None:
            item.setForeground(foreground)
            return
        if self._is_dark_mode():
            item.setForeground(QColor("#F8FAFC"))
        else:
            item.setForeground(QColor("#111827"))

    def _load_saved_filter_state(self) -> dict[str, object] | None:
        if self.main_window is not None and hasattr(self.main_window, "settings_controller"):
            state = self.main_window.settings_controller.tcra_filter_state()
            return dict(state) if state else None
        return None

    def _persist_filter_state(self):
        if self.main_window is None or not hasattr(self.main_window, "settings_controller"):
            return
        self.main_window.settings_controller.set_tcra_filter_state(
            {
                "search_text": self.search_input.text().strip(),
                "status": self.filter_status.currentText(),
                "selected_orgaos": list(self.filter_orgao.checked_items()),
                "orgaos_all_selected": bool(self.filter_orgao.is_all_selected()),
                "selected_bairros": list(self.filter_bairro.checked_items()),
                "bairros_all_selected": bool(self.filter_bairro.is_all_selected()),
                "year": self.filter_year.currentText(),
                "only_mpsp": bool(self.chk_only_mpsp.isChecked()),
                "only_relatorio_pendente": bool(self.chk_only_relatorio_pendente.isChecked()),
                "only_prazo_vencido": bool(self.chk_only_prazo_vencido.isChecked()),
                "quick_filter_mode": self.quick_filter_mode,
            }
        )

    def _restore_filter_state_if_pending(self):
        if not self._pending_filter_restore:
            return
        state = dict(self._pending_filter_restore)
        self._pending_filter_restore = None

        widgets = [
            self.search_input,
            self.filter_status,
            self.filter_orgao,
            self.filter_bairro,
            self.filter_year,
            self.chk_only_mpsp,
            self.chk_only_relatorio_pendente,
            self.chk_only_prazo_vencido,
        ]
        for widget in widgets:
            widget.blockSignals(True)
        for button in self.quick_filter_buttons.values():
            button.blockSignals(True)
        try:
            self.search_input.setText(str(state.get("search_text", "") or ""))

            saved_status = str(state.get("status", STATUS_TODOS) or STATUS_TODOS)
            if self.filter_status.findText(saved_status) >= 0:
                self.filter_status.setCurrentText(saved_status)
            else:
                self.filter_status.setCurrentText(STATUS_TODOS)

            self.filter_orgao.set_checked_items(
                list(state.get("selected_orgaos", []) or []),
                all_selected=bool(state.get("orgaos_all_selected", True)),
            )
            self.filter_bairro.set_checked_items(
                list(state.get("selected_bairros", []) or []),
                all_selected=bool(state.get("bairros_all_selected", True)),
            )

            saved_year = str(state.get("year", STATUS_TODOS) or STATUS_TODOS)
            if self.filter_year.findText(saved_year) >= 0:
                self.filter_year.setCurrentText(saved_year)
            else:
                self.filter_year.setCurrentText(STATUS_TODOS)

            self.chk_only_mpsp.setChecked(bool(state.get("only_mpsp", False)))
            self.chk_only_relatorio_pendente.setChecked(bool(state.get("only_relatorio_pendente", False)))
            self.chk_only_prazo_vencido.setChecked(bool(state.get("only_prazo_vencido", False)))

            restored_quick_filter = str(state.get("quick_filter_mode", QUICK_FILTER_ALL) or QUICK_FILTER_ALL)
            self.quick_filter_mode = restored_quick_filter if restored_quick_filter in self.quick_filter_buttons else QUICK_FILTER_ALL
            for mode, button in self.quick_filter_buttons.items():
                button.setChecked(mode == self.quick_filter_mode)
        finally:
            for widget in widgets:
                widget.blockSignals(False)
            for button in self.quick_filter_buttons.values():
                button.blockSignals(False)
        self._set_advanced_filters_visible(False)

    def _current_session_path(self) -> str:
        if self.main_window is not None and hasattr(self.main_window, "shell_controller"):
            return str(self.main_window.shell_controller.current_session_path() or "").strip()
        runtime = getattr(self.main_window, "session_runtime", None)
        if runtime is not None:
            return str(getattr(runtime, "session_path", getattr(runtime, "path", "")) or "").strip()
        return "session://banco-local"

    def build_dashboard_payload(self) -> tuple[object | None, tuple[TcraAgendaItem, ...]]:
        payload = self.module_operations.build_dashboard_payload(self.all_tcras)
        return payload.overview, tuple(payload.agenda_items)

    def _switch_to_list_view(self):
        self.workspace_tabs.setCurrentWidget(self.list_page)

    def _switch_to_editor_view(self):
        self.workspace_tabs.setCurrentWidget(self.editor_page)

    def _current_selected_record(self) -> Tcra | None:
        selected_records = self._selected_table_records()
        if selected_records:
            current_row = self.table.currentRow()
            if 0 <= current_row < len(self.filtered_tcras):
                return self.filtered_tcras[current_row]
            return selected_records[0]
        if self.selected_uid:
            for record in self.filtered_tcras:
                if record.uid == self.selected_uid:
                    return record
        return None

    def _open_selected_record_in_editor(self) -> None:
        record = self._current_selected_record()
        if record is None:
            if self.current_form_uid:
                self._switch_to_editor_view()
            return
        if self.has_pending_form_changes() and record.uid != self.current_form_uid:
            if not msg_confirm(
                self,
                "Trocar TCRA",
                "Existem alterações pendentes no formulário. Deseja descartá-las para editar outro termo?",
            ):
                self._select_uid_in_table(self.current_form_uid or self.selected_uid)
                return
        self._load_record_into_form(record, mark_clean=True)
        self._switch_to_editor_view()

    def _open_record_by_uid_in_editor(self, uid: str) -> Tcra | None:
        target_uid = _stringify(uid)
        if not target_uid:
            return None
        record = next((item for item in self.filtered_tcras if item.uid == target_uid), None)
        if record is None:
            record = self.sqlite_service.get_tcra(target_uid)
        if record is None:
            return None
        if self.has_pending_form_changes() and record.uid != self.current_form_uid:
            if not msg_confirm(
                self,
                "Trocar TCRA",
                "Existem alterações pendentes no formulário. Deseja descartá-las para editar outro termo?",
            ):
                self._select_uid_in_table(self.current_form_uid or self.selected_uid)
                return None
        self._select_uid_in_table(record.uid)
        self._load_record_into_form(record, mark_clean=True)
        self._switch_to_editor_view()
        return record

    def _set_record_panel_placeholder(self) -> None:
        self.lbl_record_title.setText("Nenhum TCRA selecionado")
        self.lbl_record_meta.setText("Selecione um TCRA na grade para ver detalhes e abrir o cadastro quando quiser.")
        self.record_details.setPlainText("Use a grade para consultar termos e abra o cadastro apenas quando for editar.")
        self.record_timeline.setPlainText("Nenhum evento para exibir.")
        self.btn_record_edit.setEnabled(False)

    def _build_record_event_lines(self, eventos: list[TcraEvento], *, limit: int = 6) -> list[str]:
        return build_event_lines(eventos, limit=limit)

    def _update_record_panel(self, record: Tcra | None) -> None:
        if record is None:
            self._set_record_panel_placeholder()
            return
        panel_data = build_record_panel_data(record, today=self.today)
        self.lbl_record_title.setText(panel_data.title)
        self.lbl_record_meta.setText(panel_data.meta)
        self.record_details.setPlainText(panel_data.details)
        self.record_timeline.setPlainText(panel_data.timeline)
        self.btn_record_edit.setEnabled(True)

    def _open_inbox_overview(self):
        self.overview_tabs.setCurrentIndex(1)
        self._set_overview_panel_visible(True)

    def _open_quality_overview(self):
        self.overview_tabs.setCurrentIndex(2)
        self._set_overview_panel_visible(True)

    def _open_upcoming_overview(self):
        self._set_quick_filter_mode(QUICK_FILTER_PROXIMOS)
        self.overview_tabs.setCurrentIndex(1)
        self._set_overview_panel_visible(True)

    def _update_editor_context(self):
        label = (
            self.in_numero_tcra.text().strip()
            or self.in_numero_processo.text().strip()
            or self.in_local.text().strip()
            or "novo termo"
        )
        if self.has_pending_form_changes():
            self.lbl_editor_context.setText(f"Cadastro: {label} *")
        else:
            self.lbl_editor_context.setText(f"Cadastro: {label}")

    def _remember_pending_event_audit(self, *, action: str, event_type: str) -> None:
        self._pending_event_audit = {
            "action": _stringify(action),
            "event_type": _stringify(event_type),
        }

    def _pending_event_audit_metadata(self) -> dict[str, object]:
        if not self._pending_event_audit:
            return {}
        return {
            "event_change_action": _stringify(self._pending_event_audit.get("action")),
            "event_change_type": _stringify(self._pending_event_audit.get("event_type")),
        }

    def handle_tab_activated(self):
        if self.has_pending_form_changes():
            self._refresh_form_state()
            return
        self.refresh_data(preferred_uid=self.current_form_uid or self.selected_uid)

    def _set_quick_filter_mode(self, mode: str):
        normalized_mode = mode if mode in self.quick_filter_buttons else QUICK_FILTER_ALL
        self.quick_filter_mode = normalized_mode
        for button_mode, button in self.quick_filter_buttons.items():
            if button.isChecked() != (button_mode == normalized_mode):
                button.blockSignals(True)
                button.setChecked(button_mode == normalized_mode)
                button.blockSignals(False)
        self._apply_filters(preferred_uid=self.current_form_uid or self.selected_uid)

    def _request_refresh(self):
        if self.has_pending_form_changes() and not msg_confirm(
            self,
            "Atualizar TCRAs",
            "Existem alterações pendentes no formulário. Deseja descartá-las para recarregar os TCRAs da base oficial/cache local?",
        ):
            return
        self.refresh_data(preferred_uid=self.current_form_uid or self.selected_uid, refresh_remote=True)

    def _preferred_export_dir(self) -> str:
        if self.main_window is not None and hasattr(self.main_window, "settings_controller"):
            return self.main_window.settings_controller.preferred_export_dir()
        return ""

    def _remember_export_dir(self, path: str) -> None:
        if not path:
            return
        if self.main_window is not None and hasattr(self.main_window, "settings_controller"):
            self.main_window.settings_controller.save_last_export_dir(os.path.dirname(path))

    def set_global_search_mode(self, enabled: bool) -> None:
        self._global_search_mode = bool(enabled)
        if hasattr(self, "lbl_search"):
            self.lbl_search.setVisible(not self._global_search_mode)
        self.search_input.setVisible(not self._global_search_mode)

    def _load_saved_form_draft(self) -> dict[str, object] | None:
        if self.main_window is None or not hasattr(self.main_window, "settings_controller"):
            return None
        draft = self.main_window.settings_controller.tcra_form_draft()
        return dict(draft) if draft else None

    def _clear_saved_form_draft(self) -> None:
        self._last_draft_saved_payload = None
        self._pending_new_form_draft = None
        if self.main_window is not None and hasattr(self.main_window, "settings_controller"):
            self.main_window.settings_controller.clear_tcra_form_draft()

    def _queue_form_autosave(self) -> None:
        self._autosave_timer.start(self.FORM_DRAFT_AUTOSAVE_MS)

    def _save_form_draft(self) -> None:
        if self.current_form_uid:
            return
        payload = self.capture_form_state()
        has_content = any(
            [
                str(payload.get("numero_processo") or "").strip(),
                str(payload.get("numero_tcra") or "").strip(),
                str(payload.get("local") or "").strip(),
                str(payload.get("endereco") or "").strip(),
                str(payload.get("servicos") or "").strip(),
                str(payload.get("observacoes") or "").strip(),
                payload.get("eventos"),
            ]
        )
        if not has_content or not self.has_pending_form_changes():
            self._clear_saved_form_draft()
            return
        if payload == self._last_draft_saved_payload:
            return
        if self.main_window is None or not hasattr(self.main_window, "settings_controller"):
            return
        self.main_window.settings_controller.set_tcra_form_draft(payload)
        self._pending_new_form_draft = dict(payload)
        self._last_draft_saved_payload = dict(payload)
        self.lbl_form_state.setText(self.FORM_DRAFT_TEXT)

    def _restore_form_snapshot(self, snapshot: dict[str, object]) -> None:
        if not snapshot:
            return
        self._apply_form_snapshot_updates(snapshot)
        self.form_eventos = restore_form_eventos_snapshot(
            list(snapshot.get("eventos") or ()),
            parse_date=self._parse_optional_date,
        )
        self._normalize_form_eventos()
        self._populate_events()
        self._update_live_preview()
        self._refresh_form_state()

    def _restore_new_form_draft_if_available(self) -> bool:
        draft = dict(self._pending_new_form_draft or {})
        if draft.get("uid"):
            return False
        has_content = any(
            [
                str(draft.get("numero_processo") or "").strip(),
                str(draft.get("numero_tcra") or "").strip(),
                str(draft.get("local") or "").strip(),
                str(draft.get("servicos") or "").strip(),
                draft.get("eventos"),
            ]
        )
        if not has_content:
            return False
        self._restore_form_snapshot(draft)
        return True

    def _selected_table_rows(self) -> list[int]:
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return []
        return sorted(index.row() for index in selection_model.selectedRows())

    def _selected_table_records(self) -> list[Tcra]:
        if self._bulk_selected_uids:
            selected_by_uid = {uid for uid in self._bulk_selected_uids if uid}
            selected_records = [record for record in self.filtered_tcras if record.uid in selected_by_uid]
            if selected_records:
                return selected_records
        rows = self._selected_table_rows()
        return [self.filtered_tcras[row] for row in rows if 0 <= row < len(self.filtered_tcras)]

    def _update_overview_panel_height(self):
        current_label = self.overview_tabs.tabText(self.overview_tabs.currentIndex()).split("(")[0].strip()
        self.lbl_overview_title.setText(current_label or "Painel operacional")

    def _set_overview_tab_counts(self, *, inbox_count: int = 0, quality_count: int = 0) -> None:
        normalized_inbox = max(0, int(inbox_count))
        normalized_quality = max(0, int(quality_count))
        self.btn_summary_inbox.setText(f"Inbox ({normalized_inbox})")
        self.btn_summary_quality.setText(f"Qualidade ({normalized_quality})")
        self.btn_summary_inbox.setEnabled(True)
        self.btn_summary_quality.setEnabled(True)
        self.overview_tabs.setTabText(0, "Registro")
        self.overview_tabs.setTabText(1, f"Inbox ({normalized_inbox})")
        self.overview_tabs.setTabText(2, f"Qualidade ({normalized_quality})")

    def _set_selection_actions_visible(self, visible: bool) -> None:
        self.selection_actions_frame.setVisible(bool(visible))

    def _set_overview_panel_visible(self, visible: bool) -> None:
        self._overview_panel_visible = bool(visible)
        self.overview_panel.setVisible(self._overview_panel_visible)
        if self._overview_panel_visible:
            self._update_overview_panel_height()
            self.list_splitter.setSizes([max(int(980 * self.sf), 760), max(int(420 * self.sf), 360)])
        else:
            self.list_splitter.setSizes([1, 0])

    def _advanced_filters_active_count(self) -> int:
        count = 0
        if not self.filter_orgao.is_all_selected():
            count += 1
        if not self.filter_bairro.is_all_selected():
            count += 1
        if self.filter_year.currentText() not in {"", STATUS_TODOS}:
            count += 1
        if self.chk_only_mpsp.isChecked():
            count += 1
        if self.chk_only_relatorio_pendente.isChecked():
            count += 1
        if self.chk_only_prazo_vencido.isChecked():
            count += 1
        return count

    def _set_advanced_filters_visible(self, visible: bool) -> None:
        self._advanced_filters_visible = bool(visible)
        self.advanced_filters_frame.setVisible(self._advanced_filters_visible)
        self.btn_toggle_advanced_filters.blockSignals(True)
        self.btn_toggle_advanced_filters.setChecked(self._advanced_filters_visible)
        active_count = self._advanced_filters_active_count()
        if self._advanced_filters_visible:
            label = "Ocultar filtros"
        elif active_count:
            label = f"Mais filtros ({active_count})"
        else:
            label = "Mais filtros"
        self.btn_toggle_advanced_filters.setText(label)
        self.btn_toggle_advanced_filters.blockSignals(False)

    def _toggle_advanced_filters(self) -> None:
        self._set_advanced_filters_visible(not self._advanced_filters_visible)

    def _toggle_agenda_preview(self) -> None:
        self._agenda_expanded = not self._agenda_expanded
        self._apply_filters(preferred_uid=self.current_form_uid or self.selected_uid)

    def _toggle_quality_preview(self) -> None:
        self._quality_expanded = not self._quality_expanded
        self._apply_filters(preferred_uid=self.current_form_uid or self.selected_uid)

    def _set_agenda_scope(self, scope: str) -> None:
        normalized_scope = scope if scope in self.agenda_scope_buttons else AGENDA_SCOPE_HOJE
        self.agenda_scope = normalized_scope
        for button_scope, button in self.agenda_scope_buttons.items():
            if button.isChecked() != (button_scope == normalized_scope):
                button.blockSignals(True)
                button.setChecked(button_scope == normalized_scope)
                button.blockSignals(False)
        self._apply_filters(preferred_uid=self.current_form_uid or self.selected_uid)

    def _set_import_status(self, text: str, *, visible: bool | None = None) -> None:
        normalized_text = _stringify(text) or self.IMPORT_STATUS_IDLE_TEXT
        self.lbl_import_status.setText(normalized_text)
        should_show = normalized_text != self.IMPORT_STATUS_IDLE_TEXT if visible is None else bool(visible)
        self.lbl_import_status.setVisible(should_show)
        self._update_overview_panel_height()

    def _get_export_path(self, title: str, file_filter: str) -> str:
        path, _selected_filter = QFileDialog.getSaveFileName(self, title, self._preferred_export_dir(), file_filter)
        if path:
            self._remember_export_dir(path)
        return path

    def _build_workspace_filters(self) -> TcraWorkspaceFilters:
        return TcraWorkspaceFilters(
            text=self.search_input.text(),
            status=self.filter_status.currentText() or STATUS_TODOS,
            selected_orgaos=tuple([] if self.filter_orgao.is_all_selected() else self.filter_orgao.checked_items()),
            selected_bairros=tuple([] if self.filter_bairro.is_all_selected() else self.filter_bairro.checked_items()),
            selected_year=self.filter_year.currentText() or STATUS_TODOS,
            only_mpsp=self.chk_only_mpsp.isChecked(),
            only_relatorio_pendente=self.chk_only_relatorio_pendente.isChecked(),
            only_prazo_vencido=self.chk_only_prazo_vencido.isChecked(),
            quick_filter_mode=self.quick_filter_mode,
        )

    def _apply_workspace_snapshot(self, snapshot: TcraWorkspaceSnapshot, *, preferred_uid: str | None = None) -> None:
        self._workspace_snapshot = snapshot
        self.base_filtered_tcras = list(snapshot.base_filtered_records)
        self.filtered_tcras = list(snapshot.filtered_records)
        self._update_cards_and_context(snapshot)
        self._update_operational_agenda(snapshot)
        self._update_quality_queue(snapshot)
        self._populate_table(preferred_uid=preferred_uid)

    def refresh_data(self, *, preferred_uid: str | None = None, refresh_remote: bool = False):
        try:
            load_result = self.module_operations.load_records(refresh_remote=refresh_remote)
            self.all_tcras = list(load_result.records)
            self.search_index = dict(load_result.search_index)
            if load_result.sync_issues:
                logger.warning(
                    "Atualização remota de TCRA concluiu com observações: %s",
                    " | ".join(load_result.sync_issues),
                )
            self._sync_filter_options()
            self._restore_filter_state_if_pending()
            self._apply_filters(preferred_uid=preferred_uid)
        except Exception as exc:
            logger.exception("Falha ao recarregar TCRAs do banco local")
            self._workspace_snapshot = None
            self.all_tcras = []
            self.base_filtered_tcras = []
            self.filtered_tcras = []
            self.agenda_items = []
            self.quality_items = []
            self.search_index = {}
            self.table.setRowCount(0)
            self.agenda_table.setRowCount(0)
            self.quality_table.setRowCount(0)
            self._clear_form(mark_clean=True)
            self.lbl_context.setText(f"Falha ao carregar TCRAs do banco local: {exc}")
            self.lbl_results.setText("0 de 0 TCRAs")
            self.lbl_radar_summary.setText("Sem dados operacionais no momento.")
            self.lbl_data_quality.setText("Qualidade cadastral: indisponível.")
            self.lbl_upcoming_reports.setText("Próximos relatórios: --")
            self.lbl_agenda_summary.setText("Inbox operacional indisponível.")
            self.lbl_quality_summary.setText("Fila de qualidade indisponível.")
            self._set_overview_tab_counts(inbox_count=0, quality_count=0)
            self.overview_tabs.tabBar().setTabToolTip(1, self.lbl_agenda_summary.text())
            self.overview_tabs.tabBar().setTabToolTip(2, self.lbl_quality_summary.text())
            self.btn_summary_inbox.setToolTip(self.lbl_agenda_summary.text())
            self.btn_summary_quality.setToolTip(self.lbl_quality_summary.text())
            self.btn_summary_upcoming.setText(f"Próx. {UPCOMING_REPORT_WINDOW_DAYS}d")
            self.btn_summary_upcoming.setEnabled(False)
            self._set_import_status("Importação: indisponível por falha na leitura do banco local.", visible=True)
            self.btn_export_excel.setEnabled(False)
            self.btn_export_pdf.setEnabled(False)
            self.btn_open_selected.setEnabled(False)
            self._set_selection_actions_visible(False)
            for card in [
                self.card_total,
                self.card_ativos,
                self.card_cumpridos,
                self.card_alertas,
                self.card_proximos,
                self.card_mpsp,
            ]:
                card.update_value("0")

    def clear_filters(self):
        widgets = [
            self.filter_status,
            self.filter_orgao,
            self.filter_bairro,
            self.filter_year,
            self.chk_only_mpsp,
            self.chk_only_relatorio_pendente,
            self.chk_only_prazo_vencido,
        ]
        for button in self.quick_filter_buttons.values():
            button.blockSignals(True)
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self.search_input.clear()
            self.filter_status.setCurrentText(STATUS_TODOS)
            self.filter_orgao.select_all()
            self.filter_bairro.select_all()
            self.filter_year.setCurrentText(STATUS_TODOS)
            self.chk_only_mpsp.setChecked(False)
            self.chk_only_relatorio_pendente.setChecked(False)
            self.chk_only_prazo_vencido.setChecked(False)
            self.quick_filter_mode = QUICK_FILTER_ALL
            if QUICK_FILTER_ALL in self.quick_filter_buttons:
                self.quick_filter_buttons[QUICK_FILTER_ALL].setChecked(True)
        finally:
            for button in self.quick_filter_buttons.values():
                button.blockSignals(False)
            for widget in widgets:
                widget.blockSignals(False)
        self._set_advanced_filters_visible(False)
        self._apply_filters(preferred_uid=self.current_form_uid or self.selected_uid)

    def new_tcra(self):
        if self.has_pending_form_changes() and not msg_confirm(
            self,
            "Novo TCRA",
            "Existem alterações pendentes no formulário. Deseja descartá-las para iniciar um novo termo?",
        ):
            return
        self._restoring_selection = True
        self.table.clearSelection()
        self._restoring_selection = False
        self.selected_uid = ""
        self._clear_form(mark_clean=True)
        self._restore_new_form_draft_if_available()
        self._switch_to_editor_view()
        self._focus_form_widget(self.in_numero_processo)

    def save_tcra(self):
        try:
            record = self._collect_form_record()
        except ValueError as exc:
            QMessageBox.warning(self, "Aviso", str(exc))
            return

        try:
            result = self.module_operations.save_record(
                record,
                pending_audit_metadata=self._pending_event_audit_metadata(),
            )
        except Exception as exc:
            logger.exception("Falha ao salvar TCRA")
            QMessageBox.critical(self, "Erro", f"Falha ao salvar o TCRA no banco local: {exc}")
            return

        if result.status == "duplicate":
            duplicate = result.duplicate_record
            label = duplicate.numero_tcra or duplicate.numero_processo or duplicate.local or duplicate.uid if duplicate else "--"
            QMessageBox.warning(
                self,
                "Aviso",
                f"Já existe um TCRA parecido cadastrado no banco local: {label}. Revise processo/TCRA antes de salvar.",
            )
            self._focus_form_widget(self.in_numero_tcra if record.numero_tcra else self.in_numero_processo)
            return

        consistency_issues = list(result.consistency_issues)
        if consistency_issues:
            QMessageBox.warning(
                self,
                "Aviso",
                "Revise o cadastro do TCRA antes de salvar:\n- " + "\n- ".join(consistency_issues),
            )
            self._focus_issue_in_form(consistency_issues[0])
            return

        self._pending_event_audit = None
        self._clear_saved_form_draft()
        self.refresh_data(preferred_uid=result.saved_uid)
        if result.saved_record is not None:
            self._load_record_into_form(result.saved_record, mark_clean=True)
            self._switch_to_editor_view()

    def delete_tcra(self):
        target_uid = _stringify(self.current_form_uid or self.selected_uid)
        if not target_uid:
            QMessageBox.warning(self, "Aviso", "Selecione um TCRA salvo para excluir.")
            return

        if not msg_confirm(
            self,
            "Excluir TCRA",
            "Deseja realmente excluir este TCRA e todos os eventos associados do banco local?",
        ):
            return

        try:
            self.module_operations.delete_record(target_uid)
        except Exception as exc:
            logger.exception("Falha ao excluir TCRA %s", target_uid)
            QMessageBox.critical(self, "Erro", f"Falha ao excluir o TCRA do banco local: {exc}")
            return
        self._pending_event_audit = None
        self._clear_saved_form_draft()
        self.selected_uid = ""
        self.current_form_uid = ""
        self.refresh_data()
        self._switch_to_list_view()

    def import_legacy_workbook(self):
        if self.has_pending_form_changes() and not msg_confirm(
            self,
            "Importar TCRAs",
            "Existem alterações pendentes no formulário. Deseja descartá-las antes de importar a planilha legada?",
        ):
            return

        path, _filter_name = QFileDialog.getOpenFileName(
            self,
            "Selecionar planilha legada de TCRAs",
            "",
            "Planilhas Excel (*.xlsx *.xlsm)",
        )
        if not path:
            return

        try:
            analysis = self.module_operations.analyze_import_workbook(path)
        except Exception as exc:
            logger.exception("Falha ao analisar planilha legada de TCRA: %s", path)
            QMessageBox.warning(self, "Aviso", f"Falha ao analisar a planilha legada: {exc}")
            return

        if analysis.importable_count <= 0:
            dialog = TcraImportPreviewDialog(self, analysis)
            dialog.exec()
            self._set_import_status("Importação: nenhuma linha importável encontrada.", visible=True)
            return

        preview_dialog = TcraImportPreviewDialog(self, analysis)
        if not preview_dialog.exec():
            self._set_import_status("Importação: cancelada após a revisão da planilha.", visible=True)
            return

        try:
            import_result = self.module_operations.execute_import_merge(analysis)
        except Exception as exc:
            logger.exception("Falha ao importar planilha legada de TCRA: %s", path)
            QMessageBox.critical(self, "Erro", f"Falha ao importar a planilha legada: {exc}")
            return
        self._set_import_status(
            import_result.import_status_text,
            visible=True,
        )
        self._pending_event_audit = None
        self.refresh_data(preferred_uid=import_result.preferred_uid)

    def export_excel_report(self):
        if not self.filtered_tcras:
            QMessageBox.warning(self, "Aviso", "Não há TCRAs no recorte atual para exportar.")
            return
        path = self._get_export_path("Salvar relatório de TCRAs", "Planilha (*.xlsx)")
        if not path:
            return
        try:
            self.module_operations.export_excel_report(path, self.filtered_tcras, filter_summary=self._build_filter_summary())
        except Exception as exc:
            logger.exception("Falha ao exportar relatório de TCRA em Excel: %s", path)
            QMessageBox.critical(self, "Erro", f"Falha ao exportar o relatório em Excel: {exc}")
            return
        QMessageBox.information(self, "Sucesso", "Relatório de TCRAs exportado em Excel.")

    def export_pdf_report(self):
        if not self.filtered_tcras:
            QMessageBox.warning(self, "Aviso", "Não há TCRAs no recorte atual para exportar.")
            return
        path = self._get_export_path("Salvar relatório de TCRAs", "PDF (*.pdf)")
        if not path:
            return
        try:
            self.module_operations.export_pdf_report(path, self.filtered_tcras, filter_summary=self._build_filter_summary())
        except Exception as exc:
            logger.exception("Falha ao exportar relatório de TCRA em PDF: %s", path)
            QMessageBox.critical(self, "Erro", f"Falha ao exportar o relatório em PDF: {exc}")
            return
        QMessageBox.information(self, "Sucesso", "Relatório de TCRAs exportado em PDF.")

    def _clear_table_selection(self) -> None:
        self._bulk_selected_uids = []
        self._restoring_selection = True
        try:
            self.table.clearSelection()
        finally:
            self._restoring_selection = False
        self._refresh_selection()

    def _select_alert_rows(self) -> None:
        if not self.filtered_tcras:
            return
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return
        selected_uids: list[str] = []
        self._restoring_selection = True
        try:
            self.table.clearSelection()
            first_row = None
            for row_index, record in enumerate(self.filtered_tcras):
                if not (
                    tcra_has_prazo_vencido(record, today=self.today)
                    or tcra_has_relatorio_pendente(record, today=self.today)
                ):
                    continue
                selected_uids.append(record.uid)
                selection_model.select(
                    self.table.model().index(row_index, 0),
                    QItemSelectionModel.Select | QItemSelectionModel.Rows,
                )
                if first_row is None:
                    first_row = row_index
            if first_row is not None:
                self.table.setCurrentCell(first_row, 0)
        finally:
            self._restoring_selection = False
        self._bulk_selected_uids = selected_uids
        self._refresh_selection()

    def apply_bulk_action(self) -> None:
        selected_records = self._selected_table_records()
        if not selected_records:
            QMessageBox.warning(self, "Aviso", "Selecione ao menos um TCRA na grade para aplicar uma ação em lote.")
            return

        dialog = TcraBulkActionDialog(self, selected_count=len(selected_records), today=self.today)
        if not dialog.exec():
            return

        values = dialog.values()
        try:
            result = self.module_operations.apply_bulk_action(
                selected_records,
                values,
                parse_date=self._parse_optional_date,
                event_presets=TCRA_EVENT_PRESETS,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Aviso", str(exc))
            return
        except Exception as exc:
            logger.exception("Falha ao aplicar ação em lote de TCRA")
            QMessageBox.critical(self, "Erro", f"Falha ao aplicar a ação em lote: {exc}")
            return
        self.refresh_data(preferred_uid=result.updated_uids[0] if result.updated_uids else "")

    def _open_add_event_dialog(self, *, preset_key: str = ""):
        self._switch_to_editor_view()
        self.editor_tabs.setCurrentIndex(1)
        next_sequence = max((evento.sequence for evento in self.form_eventos), default=0) + 1
        dialog_kwargs: dict[str, object] = {}
        if preset_key:
            dialog_kwargs["preset_key"] = preset_key
            dialog_kwargs["apply_preset_on_start"] = True
        dialog = TcraEventoEditorDialog(self, **dialog_kwargs)
        if not dialog.exec():
            return

        try:
            evento = self._build_event_from_editor(next_sequence, dialog.values())
        except ValueError as exc:
            QMessageBox.warning(self, "Aviso", str(exc))
            return

        self.form_eventos.append(evento)
        self._normalize_form_eventos()
        self._apply_latest_event_effect_to_form()
        self._populate_events()
        self._remember_pending_event_audit(action="add", event_type=evento.tipo_evento)
        self._on_form_changed()

    def add_event(self):
        self._open_add_event_dialog()

    def _add_event_with_preset(self, preset_key: str):
        self._open_add_event_dialog(preset_key=preset_key)

    def edit_selected_event(self):
        self._switch_to_editor_view()
        self.editor_tabs.setCurrentIndex(1)
        row = self.events_table.currentRow()
        if row < 0 or row >= len(self.form_eventos):
            QMessageBox.warning(self, "Aviso", "Selecione um evento para editar.")
            return

        evento = self.form_eventos[row]
        dialog = TcraEventoEditorDialog(
            self,
            data_evento=_format_date_text(evento.data_evento),
            tipo_evento=evento.tipo_evento,
            descricao=evento.descricao,
            prazo_resultante=_format_date_text(evento.prazo_resultante),
            status_resultante=evento.status_resultante,
        )
        if not dialog.exec():
            return

        try:
            self.form_eventos[row] = self._build_event_from_editor(evento.sequence, dialog.values())
        except ValueError as exc:
            QMessageBox.warning(self, "Aviso", str(exc))
            return

        self._normalize_form_eventos()
        self._apply_latest_event_effect_to_form()
        self._populate_events(selected_row=row)
        self._remember_pending_event_audit(action="edit", event_type=self.form_eventos[row].tipo_evento)
        self._on_form_changed()

    def delete_selected_event(self):
        self._switch_to_editor_view()
        self.editor_tabs.setCurrentIndex(1)
        row = self.events_table.currentRow()
        if row < 0 or row >= len(self.form_eventos):
            QMessageBox.warning(self, "Aviso", "Selecione um evento para excluir.")
            return

        deleted_event = self.form_eventos[row]
        del self.form_eventos[row]
        self._normalize_form_eventos()
        self._apply_latest_event_effect_to_form()
        self._populate_events(selected_row=min(row, len(self.form_eventos) - 1))
        self._remember_pending_event_audit(action="delete", event_type=deleted_event.tipo_evento)
        self._on_form_changed()

    def _sync_filter_options(self):
        facets = build_filter_facets(self.all_tcras, today=self.today)

        current_status = self.filter_status.currentText() or STATUS_TODOS
        current_year = self.filter_year.currentText() or STATUS_TODOS
        current_orgaos = self.filter_orgao.checked_items()
        current_bairros = self.filter_bairro.checked_items()
        orgaos_all = self.filter_orgao.is_all_selected()
        bairros_all = self.filter_bairro.is_all_selected()
        current_form_status = normalize_status_label(self.in_status.currentText().strip())

        self.filter_status.blockSignals(True)
        self.filter_year.blockSignals(True)
        self.filter_orgao.blockSignals(True)
        self.filter_bairro.blockSignals(True)
        self.in_status.blockSignals(True)
        try:
            self.filter_status.clear()
            self.filter_status.addItems([STATUS_TODOS] + list(facets.statuses))
            if current_status in [self.filter_status.itemText(index) for index in range(self.filter_status.count())]:
                self.filter_status.setCurrentText(current_status)
            else:
                self.filter_status.setCurrentText(STATUS_TODOS)

            self.filter_year.clear()
            self.filter_year.addItems([STATUS_TODOS] + list(facets.anos_processo))
            if current_year in [self.filter_year.itemText(index) for index in range(self.filter_year.count())]:
                self.filter_year.setCurrentText(current_year)
            else:
                self.filter_year.setCurrentText(STATUS_TODOS)

            self.filter_orgao.set_items(list(facets.orgaos_acompanhamento))
            if current_orgaos and not orgaos_all:
                self.filter_orgao.set_checked_items(current_orgaos, all_selected=False)
            else:
                self.filter_orgao.select_all()

            self.filter_bairro.set_items(list(facets.bairros))
            if current_bairros and not bairros_all:
                self.filter_bairro.set_checked_items(current_bairros, all_selected=False)
            else:
                self.filter_bairro.select_all()

            status_options = [
                STATUS_EM_ACOMPANHAMENTO,
                STATUS_CUMPRIDO,
                STATUS_PRAZO_VENCIDO,
                STATUS_RELATORIO_PENDENTE,
                STATUS_ARQUIVADO,
                STATUS_SEM_VALIDADE,
                STATUS_SEM_STATUS,
            ]
            for status in facets.statuses:
                if status and status not in status_options:
                    status_options.append(status)
            self.in_status.clear()
            self.in_status.addItems(status_options)
            if current_form_status:
                self.in_status.setCurrentText(current_form_status)
            else:
                self.in_status.setCurrentText(STATUS_EM_ACOMPANHAMENTO)
        finally:
            self.filter_status.blockSignals(False)
            self.filter_year.blockSignals(False)
            self.filter_orgao.blockSignals(False)
            self.filter_bairro.blockSignals(False)
            self.in_status.blockSignals(False)

    def _apply_filters(self, *_args, preferred_uid: str | None = None):
        snapshot = build_workspace_snapshot(
            self.all_tcras,
            filters=self._build_workspace_filters(),
            search_index=self.search_index,
            agenda_scope=self.agenda_scope,
            agenda_expanded=self._agenda_expanded,
            quality_expanded=self._quality_expanded,
            preview_limit=self.OVERVIEW_PREVIEW_LIMIT,
            today=self.today,
        )
        self._apply_workspace_snapshot(snapshot, preferred_uid=preferred_uid)
        self._set_advanced_filters_visible(self._advanced_filters_visible)
        self._persist_filter_state()

    def _update_cards_and_context(self, snapshot: TcraWorkspaceSnapshot):
        self.card_total.update_value(str(snapshot.metrics["count_total"]))
        self.card_ativos.update_value(str(snapshot.metrics["count_ativos"]))
        self.card_cumpridos.update_value(str(snapshot.metrics["count_cumpridos"]))
        self.card_alertas.update_value(str(snapshot.metrics["count_alertas"]))
        self.card_proximos.update_value(str(snapshot.metrics["count_relatorio_proximo_30d"]))
        self.card_mpsp.update_value(str(snapshot.metrics["count_mpsp_relacionados"]))
        self.btn_export_excel.setEnabled(bool(self.filtered_tcras))
        self.btn_export_pdf.setEnabled(bool(self.filtered_tcras))
        self.lbl_results.setText(snapshot.results_text)
        self._update_quick_filter_labels(snapshot.quick_filter_labels)
        self.lbl_context.setText(snapshot.context_text)
        self.lbl_radar_summary.setText(snapshot.radar_summary_text)
        self.lbl_data_quality.setText(snapshot.data_quality_text)
        self.lbl_upcoming_reports.setText(snapshot.upcoming_summary_text)
        self._set_overview_tab_counts(
            inbox_count=snapshot.agenda_button_count,
            quality_count=snapshot.quality_button_count,
        )
        self.btn_summary_inbox.setToolTip(snapshot.agenda_summary_text)
        self.btn_summary_quality.setToolTip(snapshot.data_quality_text)
        self.btn_summary_upcoming.setText(snapshot.upcoming_button_text)
        self.btn_summary_upcoming.setEnabled(snapshot.upcoming_button_enabled)
        self.btn_summary_upcoming.setToolTip(snapshot.upcoming_summary_text)

    def _update_operational_agenda(self, snapshot: TcraWorkspaceSnapshot):
        self.agenda_items = list(snapshot.agenda_items)
        self.agenda_table.setRowCount(len(self.agenda_items))
        for row_index, agenda_item in enumerate(self.agenda_items):
            row_values = [
                agenda_item.prioridade_label,
                agenda_item.termo_label,
                agenda_item.local or "--",
                agenda_item.detalhe or "--",
            ]
            row_color = self._agenda_row_color(agenda_item.priority_rank)
            for column_index, value in enumerate(row_values):
                item = QTableWidgetItem(_stringify(value) or "--")
                if column_index == 0:
                    item.setData(Qt.UserRole, agenda_item.uid)
                self._apply_item_palette(item, row_color, row_index=row_index)
                item.setToolTip(agenda_item.detalhe or agenda_item.prioridade_label)
                self.agenda_table.setItem(row_index, column_index, item)
        self.agenda_table.clearSelection()
        self.lbl_agenda_summary.setText(snapshot.agenda_summary_text)
        self.overview_tabs.tabBar().setTabToolTip(1, self.lbl_agenda_summary.text())
        self.btn_summary_inbox.setToolTip(self.lbl_agenda_summary.text())
        self.btn_agenda_view_all.setEnabled(snapshot.agenda_view_all_enabled)
        self.btn_agenda_view_all.setText(snapshot.agenda_view_all_text)

    def _update_quality_queue(self, snapshot: TcraWorkspaceSnapshot):
        self.quality_items = list(snapshot.quality_items)
        self.quality_table.setRowCount(len(self.quality_items))
        for row_index, quality_item in enumerate(self.quality_items):
            row_values = [
                quality_item.severity_label,
                quality_item.termo_label,
                quality_item.local or "--",
                quality_item.detalhe or "--",
            ]
            row_color = self._quality_row_color(quality_item.severity_rank)
            tooltip = "\n".join(quality_item.issues) if quality_item.issues else quality_item.detalhe
            for column_index, value in enumerate(row_values):
                item = QTableWidgetItem(_stringify(value) or "--")
                if column_index == 0:
                    item.setData(Qt.UserRole, quality_item.uid)
                self._apply_item_palette(item, row_color, row_index=row_index)
                item.setToolTip(tooltip or quality_item.severity_label)
                self.quality_table.setItem(row_index, column_index, item)
        self.quality_table.clearSelection()
        self.lbl_quality_summary.setText(snapshot.quality_summary_text)
        self.overview_tabs.tabBar().setTabToolTip(2, self.lbl_quality_summary.text())
        self.btn_summary_quality.setToolTip(self.lbl_quality_summary.text())
        self.btn_quality_view_all.setEnabled(snapshot.quality_view_all_enabled)
        self.btn_quality_view_all.setText(snapshot.quality_view_all_text)

    def _select_from_agenda(self):
        selected_row = self.agenda_table.currentRow()
        if selected_row < 0 or selected_row >= len(self.agenda_items):
            return
        agenda_item = self.agenda_items[selected_row]
        uid = _stringify(agenda_item.uid)
        record = self._open_record_by_uid_in_editor(uid)
        if record is not None:
            self._focus_agenda_item(agenda_item)

    def _select_from_quality_queue(self):
        selected_row = self.quality_table.currentRow()
        if selected_row < 0 or selected_row >= len(self.quality_items):
            return
        quality_item = self.quality_items[selected_row]
        uid = _stringify(quality_item.uid)
        record = self._open_record_by_uid_in_editor(uid)
        if record is not None:
            self._focus_quality_item(quality_item)

    def _populate_table(self, *, preferred_uid: str | None = None):
        self.table.setRowCount(len(self.filtered_tcras))
        bold_font = QFont()
        bold_font.setBold(True)
        for row_index, record in enumerate(self.filtered_tcras):
            operational_status = resolve_operational_status(record, today=self.today)
            row_items = [
                record.numero_processo,
                record.numero_tcra,
                record.local,
                operational_status,
                _format_date(record.prazo_final),
                _format_date(record.data_proximo_relatorio),
                record.orgao_acompanhamento,
                "Sim" if tcra_is_mpsp_related(record) else "Não",
            ]
            row_hint = self._build_row_hint(record, operational_status)
            for column_index, value in enumerate(row_items):
                item = QTableWidgetItem(_stringify(value) or "--")
                if column_index == 0:
                    item.setData(Qt.UserRole, record.uid)
                if column_index == 3:
                    badge_color, badge_foreground = self._status_badge_palette(record)
                    self._apply_item_palette(
                        item,
                        badge_color,
                        row_index=row_index,
                        foreground=badge_foreground,
                    )
                else:
                    self._apply_item_palette(item, None, row_index=row_index)
                item.setToolTip(row_hint)
                if column_index in {3, 4, 5}:
                    item.setFont(bold_font)
                if column_index == 3:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, column_index, item)

        if not self.filtered_tcras:
            self.selected_uid = ""
            self.btn_open_selected.setEnabled(False)
            self._set_selection_actions_visible(False)
            if not self.has_pending_form_changes() and not self.current_form_uid:
                self._clear_form(mark_clean=True)
            return

        target_uid = preferred_uid or self.current_form_uid or self.selected_uid
        if not target_uid:
            self._restoring_selection = True
            try:
                self.table.clearSelection()
            finally:
                self._restoring_selection = False
            self.selected_uid = ""
            self.btn_open_selected.setEnabled(False)
            self._set_selection_actions_visible(False)
            if not self.has_pending_form_changes() and not self.current_form_uid:
                self._clear_form(mark_clean=True)
            return
        if not any(record.uid == target_uid for record in self.filtered_tcras):
            target_uid = self.filtered_tcras[0].uid
        self._select_uid_in_table(target_uid)

    def _update_quick_filter_labels(self, label_by_mode: dict[str, str]):
        for mode, button in self.quick_filter_buttons.items():
            button.setText(label_by_mode.get(mode, button.text()))

    def _row_color_for_record(self, record: Tcra) -> QColor | None:
        return None

    def _status_badge_palette(self, record: Tcra) -> tuple[QColor | None, QColor | None]:
        return status_badge_palette(record, today=self.today, is_dark_mode=self._is_dark_mode())

    def _status_badge_color(self, record: Tcra) -> QColor | None:
        background, _foreground = self._status_badge_palette(record)
        return background

    def _agenda_row_color(self, priority_rank: int) -> QColor | None:
        return agenda_row_color(priority_rank=priority_rank, is_dark_mode=self._is_dark_mode())

    def _quality_row_color(self, severity_rank: int) -> QColor:
        return quality_row_color(severity_rank=severity_rank, is_dark_mode=self._is_dark_mode())

    def _repaint_table_styles(self):
        for row_index, record in enumerate(self.filtered_tcras):
            for column_index in range(self.table.columnCount()):
                item = self.table.item(row_index, column_index)
                if item is None:
                    continue
                if column_index == 3:
                    badge_color, badge_foreground = self._status_badge_palette(record)
                    self._apply_item_palette(
                        item,
                        badge_color,
                        row_index=row_index,
                        foreground=badge_foreground,
                    )
                else:
                    self._apply_item_palette(item, self._row_color_for_record(record), row_index=row_index)

    def _repaint_agenda_styles(self):
        for row_index, agenda_item in enumerate(self.agenda_items):
            row_color = self._agenda_row_color(agenda_item.priority_rank)
            for column_index in range(self.agenda_table.columnCount()):
                item = self.agenda_table.item(row_index, column_index)
                if item is None:
                    continue
                self._apply_item_palette(item, row_color, row_index=row_index)

    def _repaint_quality_styles(self):
        for row_index, quality_item in enumerate(self.quality_items):
            row_color = self._quality_row_color(quality_item.severity_rank)
            for column_index in range(self.quality_table.columnCount()):
                item = self.quality_table.item(row_index, column_index)
                if item is None:
                    continue
                self._apply_item_palette(item, row_color, row_index=row_index)

    def _build_row_hint(self, record: Tcra, operational_status: str) -> str:
        return build_row_hint(record, today=self.today)

    def _build_filter_summary(self) -> str:
        active_quick_button = self.quick_filter_buttons.get(self.quick_filter_mode)
        parts = [
            f"Busca: {self.search_input.text().strip() or 'nenhuma'}",
            f"Status: {self.filter_status.currentText() or STATUS_TODOS}",
            f"Ano: {self.filter_year.currentText() or STATUS_TODOS}",
            f"Atalho: {(active_quick_button.text() if active_quick_button is not None else 'Todos')}",
            f"Agenda: {self.AGENDA_SCOPE_LABELS.get(self.agenda_scope, 'Hoje')}",
        ]
        if not self.filter_orgao.is_all_selected():
            parts.append("Órgãos: " + ", ".join(self.filter_orgao.checked_items()))
        if not self.filter_bairro.is_all_selected():
            parts.append("Bairros: " + ", ".join(self.filter_bairro.checked_items()))
        flags = []
        if self.chk_only_mpsp.isChecked():
            flags.append("somente MPSP")
        if self.chk_only_relatorio_pendente.isChecked():
            flags.append("relatório pendente")
        if self.chk_only_prazo_vencido.isChecked():
            flags.append("prazo vencido")
        if flags:
            parts.append("Flags: " + ", ".join(flags))
        return " | ".join(parts)

    def _apply_form_snapshot_updates(self, snapshot: dict[str, object]) -> None:
        if not snapshot:
            return
        with self._suspend_tracking():
            for field_name, widget in self._form_field_widgets.items():
                if field_name not in snapshot:
                    continue
                value = snapshot.get(field_name)
                if isinstance(widget, QPlainTextEdit):
                    widget.setPlainText(str(value or ""))
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, QComboBox):
                    widget.setCurrentText(str(value or STATUS_EM_ACOMPANHAMENTO))
                else:
                    widget.setText(str(value or ""))

    def _rebuild_form_preview_data(self) -> TcraFormPreviewData:
        snapshot = self.capture_form_state()
        try:
            preview_record = self._collect_form_record()
        except ValueError:
            preview_record = None
        preview_data = build_form_preview_data(
            snapshot=snapshot,
            preview_record=preview_record,
            recent_event_lines=self._build_recent_event_lines(),
            today=self.today,
        )
        self._form_preview_data = preview_data
        return preview_data

    def _focus_form_widget(self, widget) -> None:
        self._switch_to_editor_view()
        if hasattr(self, "form_scroll"):
            self.form_scroll.ensureWidgetVisible(widget)
        widget.setFocus(Qt.OtherFocusReason)
        if hasattr(widget, "selectAll"):
            widget.selectAll()

    def _focus_issue_in_form(self, issue: str) -> None:
        widget = self._form_field_widgets.get(resolve_issue_focus_field(issue))
        if widget is not None:
            self._focus_form_widget(widget)

    def _focus_agenda_item(self, agenda_item: TcraAgendaItem) -> None:
        normalized_label = _stringify(agenda_item.prioridade_label).lower()
        if "prazo" in normalized_label:
            self._focus_form_widget(self.in_prazo_final)
            return
        if "relatorio" in normalized_label:
            self._focus_form_widget(self.in_data_proximo_relatorio)
            return
        if "responsavel" in normalized_label:
            self._focus_form_widget(self.in_responsavel)
            return
        if "orgao" in normalized_label:
            self._focus_form_widget(self.in_orgao)
            return
        if "cadastro" in normalized_label or "revisar" in normalized_label:
            self._focus_issue_in_form(agenda_item.detalhe)

    def _focus_quality_item(self, quality_item: TcraQualityQueueItem) -> None:
        if quality_item.issues:
            self._focus_issue_in_form(quality_item.issues[0])

    def _current_primary_issue(self) -> str:
        return (self._form_preview_data or self._rebuild_form_preview_data()).primary_issue

    def _focus_primary_issue(self) -> None:
        primary_issue = self._current_primary_issue()
        if primary_issue:
            self._focus_issue_in_form(primary_issue)

    def _apply_safe_fix(self) -> None:
        primary_issue = self._current_primary_issue()
        if not _stringify(primary_issue):
            return
        updates = resolve_safe_fix_updates(primary_issue, self.capture_form_state())
        if not updates:
            self._focus_issue_in_form(primary_issue)
            return
        self._apply_form_snapshot_updates(updates)
        self._on_form_changed()

    def _refresh_fix_actions(self) -> None:
        primary_issue = (self._form_preview_data or self._rebuild_form_preview_data()).primary_issue
        if not primary_issue:
            self.btn_apply_fix.setVisible(False)
            self.btn_focus_fix.setVisible(False)
            return
        self.btn_focus_fix.setVisible(True)
        self.btn_apply_fix.setVisible(issue_supports_safe_fix(primary_issue))

    def _select_uid_in_table(self, uid: str):
        for row_index, record in enumerate(self.filtered_tcras):
            if record.uid != uid:
                continue
            self._restoring_selection = True
            try:
                self.table.selectRow(row_index)
            finally:
                self._restoring_selection = False
            self.selected_uid = uid
            self._update_record_panel(record)
            self.overview_tabs.setCurrentIndex(0)
            self._set_overview_panel_visible(True)
            return

    def _refresh_selection(self):
        if self._restoring_selection:
            return

        selected_rows = self._selected_table_rows()
        selected_records = self._selected_table_records()
        self.btn_bulk_action.setEnabled(bool(selected_rows))
        self.btn_clear_selection.setEnabled(bool(selected_rows))
        if not selected_rows:
            self._bulk_selected_uids = []
            self.btn_open_selected.setEnabled(False)
            self.btn_bulk_action.setText("Ações em lote")
            self.lbl_selection_summary.setText("Nenhum termo selecionado")
            self._set_selection_actions_visible(False)
            self.btn_record_edit.setEnabled(False)
            self.selected_uid = ""
            self._set_record_panel_placeholder()
            if self.overview_tabs.currentIndex() == 0:
                self._set_overview_panel_visible(False)
            if not self.current_form_uid and not self.has_pending_form_changes():
                self._clear_form(mark_clean=True)
            return
        self._bulk_selected_uids = [record.uid for record in selected_records if record.uid]
        selected_count = len(selected_records)
        self.btn_bulk_action.setText(f"Ações em lote ({selected_count})" if selected_count > 1 else "Ações em lote")
        if selected_count > 1:
            self.lbl_selection_summary.setText(f"{selected_count} termos selecionados para ação em lote")
        else:
            self.lbl_selection_summary.setText("1 termo selecionado")
        self._set_selection_actions_visible(True)

        current_row = self.table.currentRow()
        if current_row < 0 or current_row >= len(self.filtered_tcras):
            current_row = selected_rows[0]
        record = self.filtered_tcras[current_row] if 0 <= current_row < len(self.filtered_tcras) else None
        if record is None:
            return
        self.selected_uid = record.uid
        self.btn_open_selected.setEnabled(bool(selected_records))
        self.btn_open_selected.setText("Editar selecionado")
        self.btn_record_edit.setEnabled(True)
        self._update_record_panel(record)
        self.overview_tabs.setCurrentIndex(0)
        self._set_overview_panel_visible(True)

    def _load_record_into_form(self, record: Tcra, *, mark_clean: bool):
        self.current_form_uid = record.uid
        self.selected_uid = record.uid
        self.btn_open_selected.setEnabled(True)
        self.btn_open_selected.setText("Editar selecionado")
        self.lbl_selection_summary.setText("1 termo selecionado")
        self._set_selection_actions_visible(True)
        self._update_record_panel(record)
        with self._suspend_tracking():
            self.in_numero_processo.setText(record.numero_processo)
            self.in_numero_tcra.setText(record.numero_tcra)
            self.in_local.setText(record.local)
            self.in_endereco.setText(record.endereco)
            self.in_bairro.setText(record.bairro)
            self.in_orgao.setText(normalize_orgao_label(record.orgao_acompanhamento))
            self.in_status.setCurrentText(normalize_status_label(record.status) or STATUS_EM_ACOMPANHAMENTO)
            self.in_data_assinatura.setText(_format_date_text(record.data_assinatura))
            self.in_prazo_final.setText(_format_date_text(record.prazo_final))
            self.in_periodicidade.setText("" if record.periodicidade_relatorio_meses is None else str(record.periodicidade_relatorio_meses))
            self.in_data_ultimo_relatorio.setText(_format_date_text(record.data_ultimo_relatorio))
            self.in_data_proximo_relatorio.setText(_format_date_text(record.data_proximo_relatorio))
            self.in_area_m2.setText("" if record.area_m2 is None else str(record.area_m2))
            self.in_numero_mudas.setText("" if record.numero_mudas_previsto is None else str(record.numero_mudas_previsto))
            self.in_responsavel.setText(record.responsavel_execucao)
            self.chk_mpsp.setChecked(tcra_is_mpsp_related(record))
            self.in_inquerito.setText(record.inquerito_civil)
            self.in_servicos.setPlainText(record.servicos_exigidos)
            self.in_observacoes.setPlainText(record.observacoes)
        self.form_eventos = list(record.eventos)
        self._normalize_form_eventos()
        self._populate_events()
        self._update_live_preview()
        self._refresh_fix_actions()
        if mark_clean:
            self._mark_form_clean()
        else:
            self._refresh_form_state()

    def _clear_form(self, *, mark_clean: bool):
        self.current_form_uid = ""
        self.selected_uid = ""
        self.btn_open_selected.setEnabled(False)
        self.btn_open_selected.setText("Editar selecionado")
        self.lbl_selection_summary.setText("Nenhum termo selecionado")
        self._set_selection_actions_visible(bool(self._selected_table_rows()))
        self._set_record_panel_placeholder()
        with self._suspend_tracking():
            self.in_numero_processo.clear()
            self.in_numero_tcra.clear()
            self.in_local.clear()
            self.in_endereco.clear()
            self.in_bairro.clear()
            self.in_orgao.clear()
            self.in_status.setCurrentText(STATUS_EM_ACOMPANHAMENTO)
            self.in_data_assinatura.clear()
            self.in_prazo_final.clear()
            self.in_periodicidade.clear()
            self.in_data_ultimo_relatorio.clear()
            self.in_data_proximo_relatorio.clear()
            self.in_area_m2.clear()
            self.in_numero_mudas.clear()
            self.in_responsavel.clear()
            self.chk_mpsp.setChecked(False)
            self.in_inquerito.clear()
            self.in_servicos.clear()
            self.in_observacoes.clear()
        self.form_eventos = []
        self._populate_events()
        self._update_live_preview()
        self._refresh_fix_actions()
        if mark_clean:
            self._mark_form_clean()
        else:
            self._refresh_form_state()

    def _collect_form_record(self) -> Tcra:
        numero_processo = self.in_numero_processo.text().strip()
        numero_tcra = self.in_numero_tcra.text().strip()
        local = self.in_local.text().strip()
        endereco = self.in_endereco.text().strip()

        if not any([numero_processo, numero_tcra, local]):
            raise ValueError("Informe ao menos número de processo, número do TCRA ou local para salvar o termo.")

        return Tcra(
            uid=self.current_form_uid,
            numero_processo=numero_processo,
            numero_tcra=numero_tcra,
            local=local,
            endereco=endereco,
            bairro=self.in_bairro.text().strip(),
            orgao_acompanhamento=normalize_orgao_label(self.in_orgao.text().strip()),
            status=normalize_status_label(self.in_status.currentText().strip()),
            data_assinatura=self._parse_optional_date(self.in_data_assinatura.text(), "Data de assinatura"),
            prazo_final=self._parse_optional_date(self.in_prazo_final.text(), "Prazo final"),
            periodicidade_relatorio_meses=self._parse_optional_int(self.in_periodicidade.text(), "Periodicidade"),
            data_ultimo_relatorio=self._parse_optional_date(self.in_data_ultimo_relatorio.text(), "Último relatório"),
            data_proximo_relatorio=self._parse_optional_date(
                self.in_data_proximo_relatorio.text(),
                "Próximo relatório",
            ),
            area_m2=self._parse_optional_float(self.in_area_m2.text(), "Area"),
            numero_mudas_previsto=self._parse_optional_int(self.in_numero_mudas.text(), "Número de mudas"),
            servicos_exigidos=self.in_servicos.toPlainText().strip(),
            responsavel_execucao=self.in_responsavel.text().strip(),
            observacoes=self.in_observacoes.toPlainText().strip(),
            mpsp_relacionado="Sim" if self.chk_mpsp.isChecked() else "Não",
            inquerito_civil=self.in_inquerito.text().strip(),
            eventos=list(self.form_eventos),
        )

    def _parse_optional_date(self, text: str, label: str) -> date | None:
        clean = text.strip()
        if not clean:
            return None
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(clean, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"{label}: use o formato dd/mm/aaaa.")

    def _parse_optional_int(self, text: str, label: str) -> int | None:
        clean = text.strip()
        if not clean:
            return None
        try:
            return int(clean)
        except ValueError as exc:
            raise ValueError(f"{label}: informe um número inteiro válido.") from exc

    def _parse_optional_float(self, text: str, label: str) -> float | None:
        clean = text.strip()
        if not clean:
            return None
        try:
            return float(clean.replace(",", "."))
        except ValueError as exc:
            raise ValueError(f"{label}: informe um número válido.") from exc

    def _build_event_from_editor(self, sequence: int, values: dict[str, str]) -> TcraEvento:
        tipo_evento = _stringify(values.get("tipo_evento"))
        descricao = _stringify(values.get("descricao"))
        if not tipo_evento and not descricao:
            raise ValueError("Informe ao menos o tipo ou a descricao do evento.")

        return TcraEvento(
            sequence=sequence,
            data_evento=self._parse_optional_date(_stringify(values.get("data_evento")), "Data do evento"),
            tipo_evento=tipo_evento,
            descricao=descricao,
            prazo_resultante=self._parse_optional_date(
                _stringify(values.get("prazo_resultante")),
                "Prazo resultante",
            ),
            status_resultante=normalize_status_label(_stringify(values.get("status_resultante"))),
        )

    @staticmethod
    def _event_sort_key(evento: TcraEvento) -> tuple[date, int]:
        return (evento.data_evento or date.min, evento.sequence)

    def _latest_event(self) -> TcraEvento | None:
        if not self.form_eventos:
            return None
        return max(self.form_eventos, key=self._event_sort_key)

    def _latest_report_event(self) -> TcraEvento | None:
        report_events = [evento for evento in self.form_eventos if "RELATORIO" in _stringify(evento.tipo_evento).upper()]
        if not report_events:
            return None
        return max(report_events, key=self._event_sort_key)

    def _add_months(self, base_date: date, months: int) -> date:
        normalized_months = max(int(months or 0), 0)
        total_month = base_date.month - 1 + normalized_months
        year = base_date.year + total_month // 12
        month = total_month % 12 + 1
        day = min(base_date.day, monthrange(year, month)[1])
        return date(year, month, day)

    def _apply_latest_event_effect_to_form(self):
        latest_event = self._latest_event()
        latest_report = self._latest_report_event()
        if latest_event is None and latest_report is None:
            return

        with self._suspend_tracking():
            if latest_event is not None:
                normalized_status = normalize_status_label(latest_event.status_resultante)
                if normalized_status:
                    self.in_status.setCurrentText(normalized_status)
                if latest_event.prazo_resultante is not None:
                    self.in_prazo_final.setText(_format_date_text(latest_event.prazo_resultante))
                if normalized_status in {STATUS_CUMPRIDO, STATUS_ARQUIVADO}:
                    self.in_data_proximo_relatorio.clear()

            if latest_report is not None and latest_report.data_evento is not None:
                self.in_data_ultimo_relatorio.setText(_format_date_text(latest_report.data_evento))
                next_report = latest_report.prazo_resultante
                if next_report is None:
                    try:
                        periodicidade = self._parse_optional_int(self.in_periodicidade.text(), "Periodicidade")
                    except ValueError:
                        periodicidade = None
                    if periodicidade is not None:
                        next_report = self._add_months(latest_report.data_evento, periodicidade)
                current_status = normalize_status_label(self.in_status.currentText().strip())
                if next_report is not None and current_status not in {STATUS_CUMPRIDO, STATUS_ARQUIVADO}:
                    self.in_data_proximo_relatorio.setText(_format_date_text(next_report))

    def _normalize_form_eventos(self):
        normalized = []
        for index, evento in enumerate(
            sorted(self.form_eventos, key=self._event_sort_key),
            start=1,
        ):
            normalized.append(
                TcraEvento(
                    sequence=index,
                    data_evento=evento.data_evento,
                    tipo_evento=_stringify(evento.tipo_evento),
                    descricao=_stringify(evento.descricao),
                    prazo_resultante=evento.prazo_resultante,
                    status_resultante=normalize_status_label(_stringify(evento.status_resultante)),
                )
            )
        self.form_eventos = normalized

    def _populate_events(self, *, selected_row: int = 0):
        self.events_table.setRowCount(len(self.form_eventos))
        for row_index, evento in enumerate(self.form_eventos):
            values = [
                str(evento.sequence),
                _format_date(evento.data_evento),
                evento.tipo_evento or "--",
                evento.descricao or "--",
                _format_date(evento.prazo_resultante),
                evento.status_resultante or "--",
            ]
            for column_index, value in enumerate(values):
                self.events_table.setItem(row_index, column_index, QTableWidgetItem(value))

        if self.form_eventos:
            target_row = min(max(selected_row, 0), len(self.form_eventos) - 1)
            self.events_table.selectRow(target_row)
        else:
            self.events_table.clearSelection()
        self._refresh_event_actions()
        self._update_event_timeline()
        self._update_live_preview()
        self._refresh_fix_actions()

    def _refresh_event_actions(self):
        has_event = 0 <= self.events_table.currentRow() < len(self.form_eventos)
        self.btn_edit_event.setEnabled(has_event)
        self.btn_delete_event.setEnabled(has_event)

    def _build_recent_event_lines(self) -> list[str]:
        return build_event_lines(self.form_eventos, limit=5)

    def _update_event_timeline(self) -> None:
        self.timeline_preview.setPlainText(build_event_timeline_text(self.form_eventos))

    def _on_form_changed(self, *_args):
        if self._tracking_suspended:
            return
        self._refresh_form_state()
        self._update_live_preview()
        self._refresh_fix_actions()
        self._queue_form_autosave()

    def _update_live_preview(self):
        preview_data = self._rebuild_form_preview_data()
        self.lbl_fix_guidance.setText(preview_data.guidance_text)
        self.details.setPlainText(preview_data.details_text)

    def capture_form_state(self) -> dict[str, object]:
        return capture_form_state_snapshot(
            uid=self.current_form_uid,
            numero_processo=self.in_numero_processo.text(),
            numero_tcra=self.in_numero_tcra.text(),
            local=self.in_local.text(),
            endereco=self.in_endereco.text(),
            bairro=self.in_bairro.text(),
            orgao=self.in_orgao.text(),
            status=self.in_status.currentText(),
            data_assinatura=self.in_data_assinatura.text(),
            prazo_final=self.in_prazo_final.text(),
            periodicidade=self.in_periodicidade.text(),
            data_ultimo_relatorio=self.in_data_ultimo_relatorio.text(),
            data_proximo_relatorio=self.in_data_proximo_relatorio.text(),
            area_m2=self.in_area_m2.text(),
            numero_mudas=self.in_numero_mudas.text(),
            responsavel=self.in_responsavel.text(),
            mpsp=self.chk_mpsp.isChecked(),
            inquerito=self.in_inquerito.text(),
            servicos=self.in_servicos.toPlainText(),
            observacoes=self.in_observacoes.toPlainText(),
            eventos=self.form_eventos,
        )

    def _mark_form_clean(self):
        self._pending_event_audit = None
        self._clean_form_state = self.capture_form_state()
        self._refresh_form_state()

    def has_pending_form_changes(self) -> bool:
        if self._clean_form_state is None:
            return False
        return self.capture_form_state() != self._clean_form_state

    def _refresh_form_state(self):
        is_dirty = self.has_pending_form_changes()
        self.lbl_form_state.setText(self.FORM_DIRTY_TEXT if is_dirty else self.FORM_CLEAN_TEXT)
        has_record_identity = bool(self.current_form_uid)
        has_form_content = any(
            [
                self.in_numero_processo.text().strip(),
                self.in_numero_tcra.text().strip(),
                self.in_local.text().strip(),
                self.in_endereco.text().strip(),
                self.in_servicos.toPlainText().strip(),
                self.in_observacoes.toPlainText().strip(),
                self.form_eventos,
            ]
        )
        self.btn_save.setEnabled(has_form_content or is_dirty)
        self.btn_delete.setEnabled(has_record_identity)
        self.btn_add_event.setEnabled(True)
        if not is_dirty and self.current_form_uid:
            self.lbl_form_state.setText(self.FORM_CLEAN_TEXT)
        self._update_editor_context()

    def _suspend_tracking(self):
        class _TrackingContext:
            def __init__(self, tab: "TcraTab"):
                self.tab = tab

            def __enter__(self):
                self.tab._tracking_suspended += 1

            def __exit__(self, exc_type, exc, tb):
                self.tab._tracking_suspended = max(0, self.tab._tracking_suspended - 1)

        return _TrackingContext(self)
