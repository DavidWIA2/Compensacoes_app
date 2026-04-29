import os
from typing import List, Dict, Optional

from PySide6.QtCore import Qt, QUrl, QUrlQuery
from PySide6.QtGui import QIntValidator, QDoubleValidator, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTableView, QHeaderView,
    QGroupBox, QGridLayout, QLabel, QLineEdit, QCheckBox, QComboBox,
    QPushButton, QSizePolicy, QButtonGroup, QStyle, QStyleOptionButton, QFrame,
    QMenu, QToolButton,
    QDialog,
)
from app.models.compensacao import Compensacao
from app.models.display_columns import DISPLAY_COLUMN_ATTRS, display_column_index
from app.config import MAP_DEFAULT_BASE_LAYER
from app.services.map_engine import resolve_map_engine_resource
from app.services.records_service import display_tipo_value
from app.ui.components.widgets import (
    CheckableComboBox,
    ClickableComboBox,
    NumericSortProxy,
    MapBridge,
    DebugPage,
    LockedSplitter,
)
from app.ui.components.model import CompensacoesTableModel
from app.ui.components.timer_utils import schedule_owned_single_shot
from app.ui.controllers.data_controller_support import (
    COMPENSACOES_QUICK_FILTER_ALL,
    COMPENSACOES_QUICK_FILTER_COM_PLANTIO,
    COMPENSACOES_QUICK_FILTER_COMPENSADOS,
    COMPENSACOES_QUICK_FILTER_DUPLICIDADE_AV_TEC,
    COMPENSACOES_QUICK_FILTER_OFICIOS,
    COMPENSACOES_QUICK_FILTER_PENDENTES,
    COMPENSACOES_QUICK_FILTER_QUALIDADE,
    COMPENSACOES_QUICK_FILTER_SEM_GPS,
    COMPENSACOES_QUICK_FILTER_SEM_MICRO,
)
from app.ui.tabs.data_tab_support import (
    build_column_texts_for_records,
    build_micro_rows,
    build_totals_rows,
    compute_crud_buttons_minimum_width,
    compute_preferred_left_panel_width,
    compute_splitter_anchor_left_width,
    compute_splitter_sizes,
    compute_target_column_width,
    resolve_column_width_bounds,
    resolve_splitter_anchor_character_index,
)

QWebEngineView = None
QWebChannel = None
QWebEngineSettings = None


def _ensure_webengine_classes():
    global QWebEngineView, QWebChannel, QWebEngineSettings
    if QWebEngineView is None:
        from PySide6.QtWebEngineWidgets import QWebEngineView as _QWebEngineView

        QWebEngineView = _QWebEngineView
    if QWebChannel is None:
        from PySide6.QtWebChannel import QWebChannel as _QWebChannel

        QWebChannel = _QWebChannel
    if QWebEngineSettings is None:
        from PySide6.QtWebEngineCore import QWebEngineSettings as _QWebEngineSettings

        QWebEngineSettings = _QWebEngineSettings
    return QWebEngineView, QWebChannel, QWebEngineSettings


class DataTab(QWidget):
    OFICIO_COLUMN_INDEX = display_column_index("oficio_processo")
    TIPO_COLUMN_INDEX = display_column_index("eletronico")
    PLANTIO_COLUMN_INDEX = display_column_index("endereco_plantio")
    _SPLITTER_VISUAL_ANCHOR_NUDGE = 4
    _COLUMN_WIDTH_RULES = {
        "oficio_processo": {"min": 160, "max": 380},
        "eletronico": {"min": 110, "max": 150},
        "caixa": {"min": 95, "max": 150},
        "av_tec": {"min": 110, "max": 180},
        "compensacao": {"min": 100, "max": 140},
        "endereco": {"min": 220, "max": 420},
        "microbacia": {"min": 130, "max": 220},
        "compensado": {"min": 110, "max": 140},
        "endereco_plantio": {"min": 220, "max": 420},
    }
    _COLUMN_STATIC_TEXTS = {
        "eletronico": ("Eletrônico", "Ofício", "Físico", "Nulo"),
        "caixa": ("Arquivado",),
        "compensado": ("SIM", "NÃO"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.sf = getattr(parent, "scale_factor", 1.0)
        self._map_loaded = False
        self._map_engine = ""
        self._map_fallback_loaded = False
        self._web_view_initialized = False
        self._locked_table_height: Optional[int] = None
        self._locked_splitter_height: Optional[int] = None
        self.web = None
        self.channel = None
        self.bridge = None
        self.form_dialog = None
        self.setup_ui()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_form_group_height()
        self._sync_left_panel_heights()
        self._apply_responsive_layout()
        self._update_responsive_constraints()
        schedule_owned_single_shot(self, 0, self._finalize_responsive_layout)
        schedule_owned_single_shot(self, 0, self.align_splitter_to_table_width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_form_group_height()
        self._sync_left_panel_heights()
        self._apply_responsive_layout()
        self._update_responsive_constraints()
        schedule_owned_single_shot(self, 0, self._finalize_responsive_layout)

    def setup_ui(self):
        panel_gap = max(int(10 * self.sf), 8)
        panel_bottom_gap = max(int(12 * self.sf), 12)
        self._panel_gap = panel_gap
        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        layout.setSpacing(int(8 * self.sf))

        filters_frame = QFrame(self)
        filters_frame.setProperty("panel", "toolbar")
        self.filters_frame = filters_frame
        filters_host_layout = QVBoxLayout(filters_frame)
        self.filters_host_layout = filters_host_layout
        filters_host_layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        filters_host_layout.setSpacing(int(6 * self.sf))

        header_row = QHBoxLayout()
        self.filters_header_row = header_row
        header_row.setSpacing(int(8 * self.sf))
        header_text_layout = QVBoxLayout()
        header_text_layout.setSpacing(int(2 * self.sf))
        self.lbl_workspace_kicker = QLabel("COMPENSAÇÕES")
        self.lbl_workspace_kicker.setProperty("role", "eyebrow")
        self.lbl_workspace_title = QLabel("Base de compensa\u00e7\u00f5es")
        self.lbl_workspace_title.setProperty("role", "section-title")
        self.lbl_workspace_subtitle = QLabel("Consulta, triagem e abertura rápida do cadastro.")
        self.lbl_workspace_subtitle.setProperty("role", "page-subtitle")
        self.lbl_workspace_helper = QLabel("Localize processos na grade; revise o contexto à direita.")
        self.lbl_workspace_helper.setProperty("role", "helper")
        self.lbl_workspace_helper.setWordWrap(True)
        header_text_layout.addWidget(self.lbl_workspace_kicker)
        header_text_layout.addWidget(self.lbl_workspace_title)
        header_text_layout.addWidget(self.lbl_workspace_subtitle)
        header_text_layout.addWidget(self.lbl_workspace_helper)
        header_row.addLayout(header_text_layout, 1)
        self.lbl_results = QLabel("0 registros")
        self.lbl_results.setObjectName("StatusChip")
        header_row.addWidget(self.lbl_results, 0, Qt.AlignRight | Qt.AlignVCenter)
        filters_host_layout.addLayout(header_row)

        filters = QHBoxLayout()
        self.filters_row = filters
        filters.setSpacing(int(12 * self.sf))

        def mk_f(lbl, w):
            v = QVBoxLayout()
            v.setSpacing(int(2 * self.sf))
            l = QLabel(lbl)
            l.setProperty("role", "muted")
            v.addWidget(l)
            v.addWidget(w)
            filters.addLayout(v)

        self.filter_micro = CheckableComboBox("Todas as Microbacias")
        self.filter_micro.setMinimumWidth(int(220 * self.sf))
        self.filter_eletronico = CheckableComboBox("Todos os Tipos")
        self.filter_eletronico.setMinimumWidth(int(140 * self.sf))
        self.filter_caixa = CheckableComboBox("Todas as Caixas")
        self.filter_caixa.setMinimumWidth(int(150 * self.sf))
        self.filter_status = ClickableComboBox()
        self.filter_status.addItems(["Todos", "Compensados", "Pendentes"])
        self.filter_status.setMinimumWidth(int(130 * self.sf))
        self.filter_year = ClickableComboBox()
        self.filter_year.addItem("Todos")
        self.filter_year.setMinimumWidth(int(90 * self.sf))

        self.btn_clear_filters = QPushButton("Limpar filtros")
        self.btn_reset_sort = QPushButton("Restaurar ordem")
        self.btn_columns = QPushButton("Exibir colunas")
        self.btn_table_full = QPushButton("Expandir tabela")
        self.btn_clear_filters.setProperty("kind", "chip-quiet")
        for b in [self.btn_reset_sort, self.btn_columns, self.btn_table_full]:
            b.setProperty("kind", "chip-quiet")
        for b in [self.btn_clear_filters, self.btn_reset_sort, self.btn_columns, self.btn_table_full]:
            b.setMinimumHeight(int(28 * self.sf))
        self.btn_clear_filters.setToolTip("Remove busca e filtros aplicados na lista principal.")
        self.btn_reset_sort.setToolTip("Restaura a ordem padrão da tabela.")
        self.btn_columns.setToolTip("Escolhe quais colunas ficam visíveis.")
        self.btn_table_full.setToolTip("Expande a tabela de compensações.")

        mk_f("Microbacias", self.filter_micro)
        mk_f("Tipo", self.filter_eletronico)
        mk_f("Caixa", self.filter_caixa)
        mk_f("Situa\u00e7\u00e3o", self.filter_status)
        mk_f("Ano", self.filter_year)

        btns = QHBoxLayout()
        self.filters_buttons_layout = btns
        btns.setSpacing(int(6 * self.sf))
        btns.setContentsMargins(0, int(12 * self.sf), 0, 0)
        btns.addWidget(self.btn_clear_filters)
        btns.addWidget(self.btn_reset_sort)
        btns.addWidget(self.btn_columns)
        btns.addWidget(self.btn_table_full)
        filters.addLayout(btns)
        filters.addStretch(1)
        filters_host_layout.addLayout(filters)

        self.quick_filter_mode = COMPENSACOES_QUICK_FILTER_ALL
        self.quick_filter_buttons: Dict[str, QPushButton] = {}
        self.quick_filter_group = QButtonGroup(self)
        self.quick_filter_group.setExclusive(True)
        quick_filters_layout = QHBoxLayout()
        self.quick_filters_layout = quick_filters_layout
        quick_filters_layout.setSpacing(int(6 * self.sf))
        quick_caption = QLabel("Recorte")
        quick_caption.setProperty("role", "panel-caption")
        quick_filters_layout.addWidget(quick_caption)
        for mode, label, tooltip in [
            (
                COMPENSACOES_QUICK_FILTER_ALL,
                "Todos (0)",
                "Mostra o recorte completo após busca e filtros avançados.",
            ),
            (
                COMPENSACOES_QUICK_FILTER_PENDENTES,
                "Pendentes (0)",
                "Lista apenas compensações ainda não marcadas como compensadas.",
            ),
            (
                COMPENSACOES_QUICK_FILTER_COMPENSADOS,
                "Compensados (0)",
                "Lista apenas registros compensados.",
            ),
            (
                COMPENSACOES_QUICK_FILTER_COM_PLANTIO,
                "Com plantio (0)",
                "Lista registros com endereço de plantio ou plantios vinculados.",
            ),
            (
                COMPENSACOES_QUICK_FILTER_OFICIOS,
                "Ofícios (0)",
                "Lista registros marcados como tipo Ofício.",
            ),
        ]:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("kind", "chip-quiet")
            button.setToolTip(tooltip)
            self.quick_filter_group.addButton(button)
            self.quick_filter_buttons[mode] = button
            quick_filters_layout.addWidget(button)
        self.quick_filter_buttons[COMPENSACOES_QUICK_FILTER_ALL].setChecked(True)

        filters_host_layout.addLayout(quick_filters_layout)

        self.quality_filter_buttons: Dict[str, QPushButton] = {}
        quality_filters_layout = QHBoxLayout()
        self.quality_filters_layout = quality_filters_layout
        quality_filters_layout.setSpacing(int(6 * self.sf))
        quality_caption = QLabel("Qualidade")
        quality_caption.setProperty("role", "panel-caption")
        quality_filters_layout.addWidget(quality_caption)
        for mode, label, tooltip in [
            (
                COMPENSACOES_QUICK_FILTER_QUALIDADE,
                "Revisão (0)",
                "Mostra registros com inconsistências ou campos operacionais faltando.",
            ),
            (
                COMPENSACOES_QUICK_FILTER_SEM_MICRO,
                "Sem micro (0)",
                "Lista registros ainda sem microbacia preenchida.",
            ),
            (
                COMPENSACOES_QUICK_FILTER_SEM_GPS,
                "Sem GPS (0)",
                "Lista registros sem latitude/longitude válidas no endereço principal.",
            ),
            (
                COMPENSACOES_QUICK_FILTER_DUPLICIDADE_AV_TEC,
                "Dup. Av. Tec. (0)",
                "Lista registros cuja Av. Tec. se repete na base.",
            ),
        ]:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("kind", "chip-quiet")
            button.setToolTip(tooltip)
            self.quick_filter_group.addButton(button)
            self.quick_filter_buttons[mode] = button
            self.quality_filter_buttons[mode] = button
            quality_filters_layout.addWidget(button)
        self.lbl_quality_summary = QLabel("Qualidade: aguardando leitura da base.")
        self.lbl_quality_summary.setObjectName("FormStateLabel")
        self.lbl_quality_summary.setWordWrap(False)
        self.lbl_quality_summary.setVisible(False)

        quality_filters_layout.addStretch(1)
        filters_host_layout.addLayout(quality_filters_layout)

        actions_row = QHBoxLayout()
        self.actions_row = actions_row
        actions_row.setSpacing(int(6 * self.sf))
        self.lbl_form_feedback = QLabel("")
        self.lbl_form_feedback.setProperty("role", "helper")
        self.lbl_form_feedback.setWordWrap(False)
        self.lbl_form_feedback.setMinimumWidth(max(int(300 * self.sf), 260))
        self.lbl_form_feedback.setMaximumWidth(max(int(460 * self.sf), 340))
        self.lbl_form_feedback.setMaximumHeight(max(int(24 * self.sf), 22))
        self.lbl_form_feedback.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lbl_form_feedback.setVisible(False)
        self.lbl_form_geocode = QLabel("")
        self.lbl_form_geocode.setProperty("role", "status-note")
        self.lbl_form_geocode.setWordWrap(False)
        self.lbl_form_geocode.setMinimumWidth(0)
        self.lbl_form_geocode.setMaximumWidth(int(420 * self.sf))
        self.lbl_form_geocode.setMaximumHeight(max(int(24 * self.sf), 22))
        self.lbl_form_geocode.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.lbl_form_geocode.setVisible(False)
        actions_row.addWidget(self.lbl_form_feedback, 0)
        self.lbl_selection_summary = QLabel("Nenhum registro selecionado")
        self.lbl_selection_summary.setObjectName("FormStateLabel")
        self.lbl_selection_summary.setWordWrap(False)
        self.lbl_selection_summary.setMinimumWidth(0)
        self.lbl_selection_summary.setMaximumWidth(int(260 * self.sf))
        actions_row.addWidget(self.lbl_selection_summary, 0)
        actions_row.addStretch(1)
        self.btn_process_history = QPushButton("Histórico")
        self.btn_process_history.setProperty("kind", "chip-quiet")
        self.btn_process_history.setToolTip("Abre o histórico filtrado pelo processo/ofício do registro atual.")
        self.btn_process_history.setEnabled(False)
        self.btn_bulk_action = QPushButton("Ações em lote")
        self.btn_bulk_action.setProperty("kind", "chip-quiet")
        self.btn_bulk_action.setToolTip("Aplica tipo, microbacia, caixa ou situação a vários registros selecionados.")
        self.btn_bulk_action.setEnabled(False)
        self.btn_more_actions = QToolButton(self)
        self.btn_more_actions.setText("Mais ações")
        self.btn_more_actions.setProperty("kind", "chip-quiet")
        self.btn_more_actions.setPopupMode(QToolButton.InstantPopup)
        self.btn_more_actions.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.more_actions_menu = QMenu(self.btn_more_actions)
        self.action_save_view = self.more_actions_menu.addAction("Salvar visão atual")
        self.saved_views_menu = self.more_actions_menu.addMenu("Aplicar visão salva")
        self.more_actions_menu.addSeparator()
        self.action_selected_process_history = self.more_actions_menu.addAction("Histórico do processo selecionado")
        self.action_clear_saved_draft = self.more_actions_menu.addAction("Limpar rascunho local")
        self.action_open_command_palette = self.more_actions_menu.addAction("Paleta de comandos")
        self.btn_more_actions.setMenu(self.more_actions_menu)
        for button in [self.btn_process_history, self.btn_bulk_action]:
            button.setMinimumHeight(int(28 * self.sf))
        actions_row.addWidget(self.btn_process_history)
        actions_row.addWidget(self.btn_bulk_action)
        actions_row.addWidget(self.btn_more_actions)
        filters_host_layout.addLayout(actions_row)
        layout.addWidget(filters_frame)

        self.splitter = LockedSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(int(8 * self.sf))
        self.splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        layout.addWidget(self.splitter, 1)

        self.left_panel = QWidget()
        self.left_panel.setMinimumHeight(0)
        self.left_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        l_lay = QVBoxLayout(self.left_panel)
        l_lay.setContentsMargins(0, 0, panel_gap, panel_bottom_gap)
        l_lay.setSpacing(int(6 * self.sf))
        self.table_model = CompensacoesTableModel()
        self.proxy = NumericSortProxy()
        self.proxy.setSourceModel(self.table_model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.verticalHeader().setDefaultSectionSize(int(28 * self.sf))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(0)
        self.table.setMinimumWidth(0)
        self.table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.resize_table_columns_for_records([])
        l_lay.addWidget(self.table, 1)

        self.group_totals = self._create_totals_group()
        l_lay.addWidget(self.group_totals)
        self.bar_export = self._create_export_bar()
        l_lay.addWidget(self.bar_export)
        self.splitter.addWidget(self.left_panel)

        self.right_panel = QWidget()
        self.right_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        r_lay = QVBoxLayout(self.right_panel)
        r_lay.setContentsMargins(panel_gap, 0, 0, 0)
        r_lay.setSpacing(int(8 * self.sf))
        self.record_context_panel = self._create_record_context_panel()
        self.record_summary_group = self.record_context_panel
        self.record_actions_group = self.record_context_panel
        r_lay.addWidget(self.record_context_panel, 0)
        r_lay.addStretch(1)

        self.form_workspace = QWidget(self)
        self.form_workspace.setVisible(False)
        self.form_workspace.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        form_workspace_layout = QVBoxLayout(self.form_workspace)
        self.form_workspace_layout = form_workspace_layout
        form_workspace_layout.setContentsMargins(0, 0, 0, 0)
        form_workspace_layout.setSpacing(int(6 * self.sf))

        cadastro_body = QFrame(self.form_workspace)
        cadastro_body.setProperty("panel", "section")
        self.cadastro_body = cadastro_body
        cadastro_body_layout = QHBoxLayout(cadastro_body)
        cadastro_body_layout.setContentsMargins(int(8 * self.sf), int(8 * self.sf), int(8 * self.sf), int(8 * self.sf))
        cadastro_body_layout.setSpacing(int(10 * self.sf))

        self.cadastro_left_panel = QWidget(cadastro_body)
        self.cadastro_left_panel.setMinimumWidth(max(int(500 * self.sf), 460))
        self.cadastro_left_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        cadastro_left_layout = QVBoxLayout(self.cadastro_left_panel)
        cadastro_left_layout.setContentsMargins(0, 0, 0, 0)
        cadastro_left_layout.setSpacing(int(6 * self.sf))

        self.cadastro_map_panel = QWidget(cadastro_body)
        self.cadastro_map_panel.setMinimumWidth(max(int(520 * self.sf), 460))
        self.cadastro_map_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cadastro_map_layout = QVBoxLayout(self.cadastro_map_panel)
        cadastro_map_layout.setContentsMargins(0, 0, 0, 0)
        cadastro_map_layout.setSpacing(int(6 * self.sf))

        self.form_group = self._create_form_group()
        self._update_form_group_height()
        cadastro_left_layout.addWidget(self.form_group, 0)

        crud_frame = QFrame(self.right_panel)
        crud_frame.setProperty("panel", "subtle")
        self.crud_frame = crud_frame
        crud = QHBoxLayout(crud_frame)
        self.crud_layout = crud
        crud.setContentsMargins(int(8 * self.sf), int(5 * self.sf), int(8 * self.sf), int(9 * self.sf))
        crud.setSpacing(int(8 * self.sf))
        self._crud_spacing = crud.spacing()
        self.btn_clear = QPushButton("Novo cadastro")
        self.btn_add = QPushButton("Adicionar")
        self.btn_save_edit = QPushButton("Salvar")
        self.btn_delete = QPushButton("Excluir")
        self.btn_ficha_pdf = QPushButton("Gerar ficha")
        self.btn_add.setProperty("kind", "success")
        self.btn_save_edit.setProperty("kind", "primary")
        self.btn_delete.setProperty("kind", "danger")
        self.btn_clear.setProperty("kind", "secondary")
        self.btn_ficha_pdf.setProperty("kind", "secondary")
        self.btn_clear.setToolTip("Limpa o formulário atual e prepara um novo cadastro.")
        self.btn_add.setToolTip("Adiciona um novo registro de compensação.")
        self.btn_save_edit.setToolTip("Salva as alterações do registro selecionado.")
        self.btn_delete.setToolTip("Exclui o registro selecionado após confirmação.")
        self.btn_ficha_pdf.setToolTip("Gera a ficha PDF do registro atual selecionado.")
        for b in [self.btn_clear, self.btn_add, self.btn_save_edit, self.btn_delete, self.btn_ficha_pdf]:
            b.setFixedHeight(max(int(28 * self.sf), 28))
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            crud.addWidget(b)
        cadastro_left_layout.addWidget(crud_frame, 0)
        self.cadastro_review_panel = self._create_cadastro_review_panel()
        cadastro_left_layout.addWidget(self.cadastro_review_panel, 0)
        cadastro_left_layout.addStretch(1)

        self.map_group = self._create_map_group()
        cadastro_map_layout.addWidget(self.map_group, 0)
        self._connect_cadastro_review_actions()

        self.map_host = QWidget()
        self.map_host.setMinimumHeight(max(int(420 * self.sf), 360))
        self.map_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.map_host_layout = QVBoxLayout(self.map_host)
        self.map_host_layout.setContentsMargins(0, 0, 0, 0)
        self.map_host_layout.setSpacing(0)
        self._build_map_placeholder()
        cadastro_map_layout.addWidget(self.map_host, 1)
        cadastro_body_layout.addWidget(self.cadastro_left_panel, 0)
        cadastro_body_layout.addWidget(self.cadastro_map_panel, 1)
        form_workspace_layout.addWidget(cadastro_body, 1)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self._update_responsive_constraints()
        self._apply_responsive_layout()
        self.splitter.setSizes([max(int(980 * self.sf), 720), self.right_panel.minimumWidth()])
        self.refresh_cadastro_review()
        schedule_owned_single_shot(self, 0, self._sync_left_panel_heights)
        schedule_owned_single_shot(self, 0, self._update_responsive_constraints)
        schedule_owned_single_shot(self, 0, self.align_splitter_to_table_width)

    def _create_record_context_panel(self):
        panel = QFrame()
        panel.setProperty("panel", "sidebar")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(int(12 * self.sf), int(12 * self.sf), int(12 * self.sf), int(12 * self.sf))
        layout.setSpacing(int(10 * self.sf))

        self.lbl_context_caption = QLabel("REGISTRO")
        self.lbl_context_caption.setProperty("role", "eyebrow")
        self.lbl_summary_oficio = QLabel("Nenhum registro selecionado")
        self.lbl_summary_oficio.setProperty("role", "section-title")
        self.lbl_summary_oficio.setWordWrap(True)
        self.lbl_summary_status = QLabel("Aguardando seleção")
        self.lbl_summary_status.setObjectName("StatusChip")
        self.lbl_summary_status.setAlignment(Qt.AlignCenter)

        title_row = QHBoxLayout()
        title_row.setSpacing(int(8 * self.sf))
        title_text = QVBoxLayout()
        title_text.setSpacing(int(2 * self.sf))
        title_text.addWidget(self.lbl_context_caption)
        title_text.addWidget(self.lbl_summary_oficio)
        title_row.addLayout(title_text, 1)
        title_row.addWidget(self.lbl_summary_status, 0, Qt.AlignTop | Qt.AlignRight)
        layout.addLayout(title_row)

        self.lbl_summary_hint = QLabel("Selecione uma linha para revisar o contexto sem sair da consulta.")
        self.lbl_summary_hint.setProperty("role", "helper")
        self.lbl_summary_hint.setWordWrap(True)
        layout.addWidget(self.lbl_summary_hint)

        action_row = QHBoxLayout()
        action_row.setSpacing(int(6 * self.sf))
        self.btn_new_cadastro_window = QPushButton("Novo")
        self.btn_open_cadastro_window = QPushButton("Abrir cadastro")
        self.btn_open_map_window = QPushButton("Mapa")
        self.btn_new_cadastro_window.setProperty("kind", "success")
        self.btn_open_cadastro_window.setProperty("kind", "primary")
        self.btn_open_map_window.setProperty("kind", "secondary")
        self.btn_new_cadastro_window.setToolTip("Abre a janela de cadastro para inserir um novo processo.")
        self.btn_open_cadastro_window.setToolTip("Abre a janela de cadastro do registro selecionado.")
        self.btn_open_map_window.setToolTip("Abre o mapa em janela ampliada com os overlays atuais.")
        for button in [self.btn_new_cadastro_window, self.btn_open_cadastro_window, self.btn_open_map_window]:
            button.setMinimumHeight(max(int(30 * self.sf), 28))
            action_row.addWidget(button)
        self.btn_open_cadastro_window.setEnabled(False)
        layout.addLayout(action_row)

        detail_frame = QFrame(panel)
        detail_frame.setProperty("panel", "subtle")
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(int(12 * self.sf), int(10 * self.sf), int(12 * self.sf), int(10 * self.sf))
        detail_layout.setSpacing(int(6 * self.sf))
        self.lbl_summary_tipo = self._add_summary_row(detail_layout, "Tipo", "--")
        self.lbl_summary_mudas = self._add_summary_row(detail_layout, "Mudas a compensar", "--")
        self.lbl_summary_micro = self._add_summary_row(detail_layout, "Microbacia", "--")
        self.lbl_summary_endereco = self._add_summary_row(detail_layout, "Endereço", "--")
        self.lbl_summary_plantio = self._add_summary_row(detail_layout, "Plantio", "--", add_separator=False)
        layout.addWidget(detail_frame)
        return panel

    def _create_cadastro_review_panel(self):
        panel = QFrame()
        panel.setProperty("panel", "subtle")
        self._cadastro_review_base_height = max(int(385 * self.sf), 340)
        panel.setMinimumHeight(self._cadastro_review_base_height)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(int(12 * self.sf), int(10 * self.sf), int(12 * self.sf), int(10 * self.sf))
        layout.setSpacing(int(8 * self.sf))

        header = QHBoxLayout()
        header.setSpacing(int(8 * self.sf))
        title = QLabel("Revisão rápida")
        title.setProperty("role", "sidebar-title")
        header.addWidget(title)
        header.addStretch(1)
        self.lbl_cadastro_review_score = QLabel("0/6")
        self.lbl_cadastro_review_score.setObjectName("StatusChip")
        self.lbl_cadastro_review_score.setAlignment(Qt.AlignCenter)
        header.addWidget(self.lbl_cadastro_review_score, 0, Qt.AlignRight)
        layout.addLayout(header)

        self.lbl_cadastro_review_next = QLabel("Selecione ou preencha um cadastro para ver os pontos de atenção.")
        self.lbl_cadastro_review_next.setWordWrap(True)
        self.lbl_cadastro_review_next.setObjectName("FormStateLabel")
        layout.addWidget(self.lbl_cadastro_review_next)

        cards_frame = QFrame(panel)
        cards_frame.setProperty("panel", "micro")
        cards_layout = QGridLayout(cards_frame)
        cards_layout.setContentsMargins(int(10 * self.sf), int(8 * self.sf), int(10 * self.sf), int(8 * self.sf))
        cards_layout.setHorizontalSpacing(int(8 * self.sf))
        cards_layout.setVerticalSpacing(int(8 * self.sf))
        self.cadastro_review_labels = {}
        self.cadastro_review_cards = {}
        for index, key in enumerate(["Endereço", "Microbacia", "GPS", "Plantio", "Mudas", "Tipo"]):
            card = QFrame(cards_frame)
            card.setProperty("panel", "subtle")
            card.setProperty("reviewState", "neutral")
            card.setMinimumHeight(max(int(42 * self.sf), 38))
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(int(9 * self.sf), int(7 * self.sf), int(9 * self.sf), int(7 * self.sf))
            card_layout.setSpacing(int(2 * self.sf))
            label = QLabel(key)
            label.setProperty("role", "panel-caption")
            value = QLabel("--")
            value.setProperty("role", "helper-strong")
            value.setWordWrap(True)
            value.setMinimumHeight(max(int(18 * self.sf), 16))
            self.cadastro_review_labels[key] = value
            self.cadastro_review_cards[key] = card
            card_layout.addWidget(label)
            card_layout.addWidget(value)
            cards_layout.addWidget(card, index // 3, index % 3)
        for col in range(3):
            cards_layout.setColumnStretch(col, 1)
        layout.addWidget(cards_frame)

        details_row = QHBoxLayout()
        details_row.setSpacing(int(8 * self.sf))
        self.cadastro_review_detail_labels = {}
        for section_title, keys in [
            ("Localização", ["Endereço cadastrado", "Coordenadas", "Plantio"]),
            ("Compensação", ["Mudas", "Status", "Caixa"]),
        ]:
            section = QFrame(panel)
            section.setProperty("panel", "micro")
            section.setMinimumHeight(max(int(88 * self.sf), 76))
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(int(10 * self.sf), int(8 * self.sf), int(10 * self.sf), int(8 * self.sf))
            section_layout.setSpacing(int(5 * self.sf))
            section_label = QLabel(section_title)
            section_label.setProperty("role", "panel-caption")
            section_layout.addWidget(section_label)
            for key in keys:
                row = QHBoxLayout()
                row.setSpacing(int(6 * self.sf))
                name = QLabel(key)
                name.setProperty("role", "muted")
                value = QLabel("--")
                value.setProperty("role", "helper-strong")
                value.setWordWrap(True)
                value.setMinimumHeight(max(int(16 * self.sf), 14))
                self.cadastro_review_detail_labels[key] = value
                row.addWidget(name, 0, Qt.AlignTop)
                row.addWidget(value, 1)
                section_layout.addLayout(row)
            details_row.addWidget(section, 1)
        layout.addLayout(details_row)

        pending_frame = QFrame(panel)
        pending_frame.setProperty("panel", "micro")
        self.cadastro_review_pending_frame = pending_frame
        pending_layout = QVBoxLayout(pending_frame)
        pending_layout.setContentsMargins(int(10 * self.sf), int(8 * self.sf), int(10 * self.sf), int(8 * self.sf))
        pending_layout.setSpacing(int(4 * self.sf))
        pending_title = QLabel("Pendências e conferência")
        pending_title.setProperty("role", "panel-caption")
        self.lbl_cadastro_review_pending = QLabel("--")
        self.lbl_cadastro_review_pending.setProperty("role", "helper")
        self.lbl_cadastro_review_pending.setWordWrap(True)
        pending_layout.addWidget(pending_title)
        pending_layout.addWidget(self.lbl_cadastro_review_pending)
        layout.addWidget(pending_frame)

        shortcut_row = QHBoxLayout()
        shortcut_row.setSpacing(int(6 * self.sf))
        self.btn_review_search_address = QPushButton("Buscar endereço")
        self.btn_review_open_plantios = QPushButton("Plantios")
        self.btn_review_save = QPushButton("Salvar")
        for button in [self.btn_review_search_address, self.btn_review_open_plantios, self.btn_review_save]:
            button.setProperty("kind", "chip-quiet")
            button.setMinimumHeight(max(int(24 * self.sf), 22))
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            shortcut_row.addWidget(button)
        layout.addLayout(shortcut_row)
        layout.addStretch(1)
        return panel

    @staticmethod
    def _repolish_widget(widget) -> None:
        try:
            style = widget.style()
            if style is not None:
                style.unpolish(widget)
                style.polish(widget)
            widget.update()
        except RuntimeError:
            return

    def _connect_cadastro_review_actions(self) -> None:
        if not hasattr(self, "btn_review_search_address"):
            return
        self.btn_review_search_address.clicked.connect(self._trigger_review_search_address)
        self.btn_review_open_plantios.clicked.connect(self._trigger_review_open_plantios)
        self.btn_review_save.clicked.connect(self._trigger_review_save)

    def shutdown_review_actions(self) -> None:
        for button, callback in [
            (getattr(self, "btn_review_search_address", None), getattr(self, "_trigger_review_search_address", None)),
            (getattr(self, "btn_review_open_plantios", None), getattr(self, "_trigger_review_open_plantios", None)),
            (getattr(self, "btn_review_save", None), getattr(self, "_trigger_review_save", None)),
        ]:
            if button is None or callback is None:
                continue
            try:
                button.clicked.disconnect(callback)
            except (RuntimeError, TypeError):
                continue

    def shutdown_transient_widgets(self) -> None:
        self.shutdown_review_actions()
        completer = getattr(self, "address_completer", None)
        if completer is None:
            return
        try:
            popup = completer.popup()
            if popup is not None:
                popup.hide()
                popup.deleteLater()
        except RuntimeError:
            pass
        try:
            self.in_end.setCompleter(None)
        except RuntimeError:
            pass
        try:
            completer.deleteLater()
        except RuntimeError:
            pass
        self.address_completer = None

    def _trigger_review_search_address(self) -> None:
        if hasattr(self, "btn_maps") and self.btn_maps.isEnabled():
            self.btn_maps.click()

    def _trigger_review_open_plantios(self) -> None:
        if hasattr(self, "btn_manage_plantios") and self.btn_manage_plantios.isEnabled():
            self.btn_manage_plantios.click()

    def _trigger_review_save(self) -> None:
        if hasattr(self, "btn_save_edit") and self.btn_save_edit.isEnabled():
            self.btn_save_edit.click()

    def _set_recommended_button(self, button, recommended: bool) -> None:
        button.setProperty("recommended", "true" if recommended else "false")
        self._repolish_widget(button)

    def _set_review_card_state(self, key: str, state: str) -> None:
        card = getattr(self, "cadastro_review_cards", {}).get(key)
        if card is None:
            return
        card.setProperty("reviewState", state)
        self._repolish_widget(card)

    def _update_contextual_form_states(self, *, compensado: bool, arquivado: bool) -> None:
        for widget, active in [
            (self.in_end_plantio, compensado),
            (self.btn_manage_plantios, compensado),
            (self.in_caixa, arquivado),
        ]:
            widget.setProperty("contextState", "active" if active else "quiet")
            self._repolish_widget(widget)

    def show_form_feedback(self, message: str, *, role: str = "feedback-info", timeout_ms: int = 4500) -> None:
        if not hasattr(self, "lbl_form_feedback"):
            return
        text = str(message or "").strip()
        self.lbl_form_feedback.setText(text)
        self.lbl_form_feedback.setToolTip(text)
        self.lbl_form_feedback.setProperty("role", role)
        self.lbl_form_feedback.setVisible(bool(text))
        self._repolish_widget(self.lbl_form_feedback)
        if text and timeout_ms > 0:
            schedule_owned_single_shot(self.lbl_form_feedback, timeout_ms, self.lbl_form_feedback.hide)

    def _adjust_form_dialog_for_review(self, pending_count: int) -> None:
        pending_count = max(int(pending_count or 0), 1)
        extra_height = max(0, pending_count - 1) * max(int(22 * self.sf), 20)
        base_review_height = getattr(self, "_cadastro_review_base_height", max(int(310 * self.sf), 270))
        target_review_height = base_review_height + extra_height
        if hasattr(self, "cadastro_review_panel"):
            self.cadastro_review_panel.setMinimumHeight(target_review_height)
            self.cadastro_review_panel.setMaximumHeight(target_review_height)
        if hasattr(self, "cadastro_review_pending_frame"):
            self.cadastro_review_pending_frame.setMinimumHeight(max(int(52 * self.sf), 48) + extra_height)

        dialog = getattr(self, "form_dialog", None)
        if dialog is None or not dialog.isVisible() or dialog.isMaximized():
            return
        base_dialog_height = max(int(860 * self.sf), 780)
        target_height = base_dialog_height + extra_height
        if dialog.height() >= target_height:
            return
        try:
            available_height = dialog.screen().availableGeometry().height()
        except RuntimeError:
            available_height = QApplication.primaryScreen().availableGeometry().height()
        max_height = max(base_dialog_height, available_height - int(32 * self.sf))
        dialog.resize(dialog.width(), min(target_height, max_height))

    def _review_value_text(self, value: object, *, fallback: str = "Pendente") -> str:
        text = str(value or "").strip()
        return text if text else fallback

    def refresh_cadastro_review(self, record: Optional[Compensacao] = None):
        if not hasattr(self, "cadastro_review_labels"):
            return
        source = record
        if source is None and self.main_window is not None:
            form_controller = getattr(self.main_window, "form_controller", None)
            read_form = getattr(form_controller, "read_form", None)
            if callable(read_form):
                try:
                    source = read_form()
                except Exception:
                    source = getattr(self.main_window, "selected", None)
            else:
                source = getattr(self.main_window, "selected", None)

        if source is None:
            values = {
                "Endereço": "--",
                "Microbacia": "--",
                "GPS": "--",
                "Plantio": "--",
                "Mudas": "--",
                "Tipo": "--",
            }
            details = {
                "Endereço cadastrado": "--",
                "Coordenadas": "--",
                "Plantio": "--",
                "Mudas": "--",
                "Status": "--",
                "Caixa": "--",
            }
            next_step = "Selecione ou preencha um cadastro para ver os pontos de atenção."
            pending_text = "Abra um cadastro existente ou preencha um novo processo para revisar os dados."
            pending_count = 1
            score_text = "0/6"
            recommended_action = ""
            card_states = {key: "neutral" for key in values}
            compensado = False
            arquivado = False
        else:
            endereco = str(getattr(source, "endereco", "") or "").strip()
            micro = str(getattr(source, "microbacia", "") or "").strip()
            lat = str(getattr(source, "latitude", "") or "").strip()
            lon = str(getattr(source, "longitude", "") or "").strip()
            plantios = tuple(getattr(source, "plantios", ()) or ())
            plantio_text = str(getattr(source, "endereco_plantio", "") or "").strip()
            mudas = self._format_summary_number(getattr(source, "compensacao", ""))
            tipo = display_tipo_value(getattr(source, "eletronico", "") or "") or "Pendente"
            caixa = str(getattr(source, "caixa", "") or "").strip() or "--"
            compensado = str(getattr(source, "compensado", "") or "").strip().upper() == "SIM"
            arquivado = caixa.strip().upper() == "ARQUIVADO"
            has_gps = bool(lat and lon)
            if plantios:
                plantio_status = f"{len(plantios)} plantio(s)"
            elif plantio_text:
                plantio_status = "Informado"
            else:
                plantio_status = "Nenhum"
            values = {
                "Endereço": "OK" if endereco else "Pendente",
                "Microbacia": micro or "Pendente",
                "GPS": "Com ponto" if has_gps else "Sem ponto",
                "Plantio": plantio_status,
                "Mudas": mudas if mudas != "--" else "Pendente",
                "Tipo": tipo,
            }
            details = {
                "Endereço cadastrado": endereco or "--",
                "Coordenadas": f"{lat}, {lon}" if has_gps else "Sem ponto",
                "Plantio": plantio_text or plantio_status,
                "Mudas": mudas if mudas != "--" else "Pendente",
                "Status": "Compensado" if compensado else "Pendente",
                "Caixa": caixa,
            }
            pending = []
            if not endereco:
                next_step = "Próximo passo: preencher o endereço principal."
                pending.append("Endereço principal pendente.")
                recommended_action = "endereco"
            elif not has_gps:
                next_step = "Próximo passo: usar Buscar Endereço para validar o ponto no mapa."
                pending.append("Ponto no mapa ainda não validado.")
                recommended_action = "buscar_endereco"
            elif not micro:
                next_step = "Próximo passo: confirmar a microbacia pelo mapa."
                pending.append("Microbacia ainda não confirmada.")
                recommended_action = "buscar_endereco"
            elif mudas == "--":
                next_step = "Próximo passo: informar o número de mudas a compensar."
                pending.append("Número de mudas pendente.")
                recommended_action = "mudas"
            else:
                next_step = "Cadastro com dados principais prontos para revisão final."
                recommended_action = "salvar" if self.main_window is not None and self.main_window.selected is not None else ""
            if compensado and not (plantios or plantio_text):
                pending.append("Cadastro compensado sem plantio vinculado.")
                recommended_action = "plantios"
            if tipo == "Pendente":
                pending.append("Tipo do processo pendente.")
                if not recommended_action:
                    recommended_action = "tipo"
            if not pending:
                pending.append("Sem pendências principais. Confira dados antes de salvar.")
            visible_pending = pending[:4]
            pending_count = len(visible_pending)
            pending_text = "\n".join(f"- {item}" for item in visible_pending)
            completed = sum(
                [
                    bool(endereco),
                    bool(micro),
                    has_gps,
                    bool(plantios or plantio_text or not compensado),
                    mudas != "--",
                    tipo != "Pendente",
                ]
            )
            score_text = f"{completed}/6"
            card_states = {
                "Endereço": "ok" if endereco else "warning",
                "Microbacia": "ok" if micro else "warning",
                "GPS": "ok" if has_gps else "warning",
                "Plantio": "ok" if plantios or plantio_text or not compensado else "warning",
                "Mudas": "ok" if mudas != "--" else "warning",
                "Tipo": "ok" if tipo != "Pendente" else "warning",
            }

        for key, label in self.cadastro_review_labels.items():
            label.setText(values.get(key, "--"))
            self._set_review_card_state(key, card_states.get(key, "neutral"))
        for key, label in getattr(self, "cadastro_review_detail_labels", {}).items():
            label.setText(details.get(key, "--"))
        self.lbl_cadastro_review_next.setText(next_step)
        self.lbl_cadastro_review_score.setText(score_text)
        self.lbl_cadastro_review_pending.setText(pending_text)
        self._adjust_form_dialog_for_review(pending_count)
        self._update_contextual_form_states(compensado=compensado, arquivado=arquivado)
        for button in [
            self.btn_maps,
            self.btn_maps_plantio,
            self.btn_manage_plantios,
            self.btn_save_edit,
            self.btn_review_search_address,
            self.btn_review_open_plantios,
            self.btn_review_save,
        ]:
            self._set_recommended_button(button, False)
        if recommended_action == "buscar_endereco":
            self._set_recommended_button(self.btn_maps, True)
            self._set_recommended_button(self.btn_review_search_address, True)
        elif recommended_action == "plantios":
            self._set_recommended_button(self.btn_manage_plantios, True)
            self._set_recommended_button(self.btn_review_open_plantios, True)
        elif recommended_action == "salvar":
            self._set_recommended_button(self.btn_save_edit, True)
            self._set_recommended_button(self.btn_review_save, True)
        self.btn_review_search_address.setEnabled(bool(recommended_action in {"buscar_endereco", "endereco"}))
        self.btn_review_open_plantios.setEnabled(bool(compensado))
        self.btn_review_save.setEnabled(bool(self.btn_save_edit.isEnabled()))

    def _summary_value_label(self, text: str):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    def _add_summary_row(self, layout: QVBoxLayout, label: str, value: str, *, add_separator: bool = True):
        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(int(2 * self.sf))

        key = QLabel(label)
        key.setProperty("role", "muted")
        key.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_label = QLabel(value)
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row_layout.addWidget(key)
        row_layout.addWidget(value_label)
        layout.addWidget(row)

        if add_separator:
            separator = QFrame()
            separator.setFrameShape(QFrame.HLine)
            separator.setFrameShadow(QFrame.Plain)
            layout.addWidget(separator)
        return value_label

    @staticmethod
    def _format_summary_number(value: object) -> str:
        if value is None:
            return "--"
        text = str(value).strip()
        if not text:
            return "--"
        try:
            return f"{float(text.replace(',', '.')):g}"
        except ValueError:
            return text

    def update_record_summary(self, record: Optional[Compensacao]):
        if record is None:
            self.lbl_summary_oficio.setText("Nenhum registro selecionado")
            self.lbl_summary_status.setText("Aguardando seleção")
            self.lbl_summary_hint.setText("Selecione uma linha para revisar o contexto sem sair da consulta.")
            self.lbl_summary_tipo.setText("--")
            self.lbl_summary_mudas.setText("--")
            self.lbl_summary_endereco.setText("--")
            self.lbl_summary_plantio.setText("--")
            self.lbl_summary_micro.setText("--")
            if hasattr(self, "btn_open_cadastro_window"):
                self.btn_open_cadastro_window.setEnabled(False)
            self._update_form_dialog_header(None)
            self.refresh_cadastro_review(None)
            return

        oficio = str(getattr(record, "oficio_processo", "") or "").strip() or "S/N"
        tipo = display_tipo_value(getattr(record, "eletronico", "") or "") or "--"
        mudas = self._format_summary_number(getattr(record, "compensacao", ""))
        compensado = str(getattr(record, "compensado", "") or "").strip().upper() == "SIM"
        status = "Compensado" if compensado else "Pendente"
        endereco = str(getattr(record, "endereco", "") or "").strip() or "--"
        plantio = str(getattr(record, "endereco_plantio", "") or "").strip() or "--"
        micro = str(getattr(record, "microbacia", "") or "").strip() or "--"

        self.lbl_summary_oficio.setText(oficio)
        self.lbl_summary_status.setText(status)
        self.lbl_summary_hint.setText("Duplo clique na linha também abre o cadastro.")
        self.lbl_summary_tipo.setText(tipo)
        self.lbl_summary_mudas.setText(mudas)
        self.lbl_summary_endereco.setText(endereco)
        self.lbl_summary_plantio.setText(plantio)
        self.lbl_summary_micro.setText(micro)
        if hasattr(self, "btn_open_cadastro_window"):
            self.btn_open_cadastro_window.setEnabled(True)
        self._update_form_dialog_header(record)
        self.refresh_cadastro_review(record)

    def open_new_cadastro_window(self):
        if self.main_window is not None:
            self.main_window.clear_form(force=True)
        self.open_cadastro_window()

    def open_cadastro_window(self):
        dialog = self._ensure_form_dialog()
        self._update_form_dialog_header(self.main_window.selected if self.main_window is not None else None)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.form_workspace.setVisible(True)
        self.refresh_cadastro_review(self.main_window.selected if self.main_window is not None else None)
        schedule_owned_single_shot(self, 0, self._prepare_compact_map_for_dialog)

    def _ensure_form_dialog(self):
        if self.form_dialog is not None:
            return self.form_dialog

        dialog = QDialog(self.window())
        dialog.setWindowTitle("Cadastro de compensação")
        dialog.setModal(False)
        dialog.resize(max(int(1260 * self.sf), 1080), max(int(860 * self.sf), 780))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(int(12 * self.sf), int(12 * self.sf), int(12 * self.sf), int(12 * self.sf))
        layout.setSpacing(int(8 * self.sf))

        header = QFrame(dialog)
        header.setProperty("panel", "toolbar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(int(12 * self.sf), int(10 * self.sf), int(12 * self.sf), int(10 * self.sf))
        header_layout.setSpacing(int(10 * self.sf))
        title_box = QVBoxLayout()
        title_box.setSpacing(int(2 * self.sf))
        self.form_dialog_kicker = QLabel("CADASTRO")
        self.form_dialog_kicker.setProperty("role", "eyebrow")
        self.form_dialog_title = QLabel("Novo cadastro")
        self.form_dialog_title.setProperty("role", "section-title")
        self.form_dialog_meta = QLabel("Sem registro selecionado")
        self.form_dialog_meta.setProperty("role", "helper")
        self.form_dialog_meta.setWordWrap(True)
        title_box.addWidget(self.form_dialog_kicker)
        title_box.addWidget(self.form_dialog_title)
        title_box.addWidget(self.form_dialog_meta)
        header_layout.addLayout(title_box, 1)
        self.form_dialog_status = QLabel("Novo")
        self.form_dialog_status.setObjectName("StatusChip")
        self.form_dialog_status.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.form_dialog_status, 0, Qt.AlignTop | Qt.AlignRight)
        layout.addWidget(header)

        layout.addWidget(self.form_workspace, 1)
        self.form_dialog = dialog
        self._update_form_dialog_header(self.main_window.selected if self.main_window is not None else None)
        return dialog

    def _update_form_dialog_header(self, record: Optional[Compensacao]):
        if not hasattr(self, "form_dialog_title"):
            return
        if record is None:
            self.form_dialog_kicker.setText("CADASTRO")
            self.form_dialog_title.setText("Novo cadastro")
            self.form_dialog_meta.setText("Preencha os dados e salve para incluir um novo processo.")
            self.form_dialog_status.setText("Novo")
            return
        oficio = str(getattr(record, "oficio_processo", "") or "").strip() or "S/N"
        mudas = self._format_summary_number(getattr(record, "compensacao", ""))
        micro = str(getattr(record, "microbacia", "") or "").strip() or "--"
        compensado = str(getattr(record, "compensado", "") or "").strip().upper() == "SIM"
        self.form_dialog_kicker.setText("REGISTRO EM EDIÇÃO")
        self.form_dialog_title.setText(oficio)
        self.form_dialog_meta.setText(f"Mudas: {mudas} | Microbacia: {micro}")
        self.form_dialog_status.setText("Compensado" if compensado else "Pendente")

    def _prepare_compact_map_for_dialog(self):
        try:
            self.load_map()
        except Exception:
            return
        if self.has_map_web_view():
            self.web.setMinimumHeight(max(int(460 * self.sf), 380))

    def _current_root_dimensions(self) -> tuple[int, int]:
        try:
            root = self.window()
            current_width = root.width() if root is not None and root.width() > 0 else self.width()
            current_height = root.height() if root is not None and root.height() > 0 else self.height()
            is_visible = self.isVisible()
        except RuntimeError:
            return 1920, 1080

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
            if (current_width <= 0 or current_width < 900) and not is_visible:
                current_width = available_width
            elif current_width > 0:
                current_width = min(current_width, available_width)
            if (current_height <= 0 or current_height < 640) and not is_visible:
                current_height = available_height
            elif current_height > 0:
                current_height = min(current_height, available_height)

        if current_width <= 0:
            current_width = 1920
        if current_height <= 0:
            current_height = 1080
        return current_width, current_height

    def _build_map_placeholder(self):
        self.map_placeholder = QWidget(self.map_host)
        placeholder_layout = QVBoxLayout(self.map_placeholder)
        placeholder_layout.setContentsMargins(int(12 * self.sf), int(12 * self.sf), int(12 * self.sf), int(12 * self.sf))
        placeholder_layout.setSpacing(int(6 * self.sf))

        self.map_placeholder_label = QLabel("Mapa não carregado. Abra quando precisar validar endereço, plantio ou microbacia.")
        self.map_placeholder_label.setWordWrap(True)
        self.map_placeholder_label.setObjectName("FormStateLabel")

        self.btn_load_map = QPushButton("Abrir mapa")
        self.btn_load_map.setProperty("kind", "primary")
        self.btn_load_map.setMinimumHeight(int(30 * self.sf))
        self.btn_load_map.clicked.connect(self.load_map)

        placeholder_layout.addWidget(self.map_placeholder_label, 0, Qt.AlignTop | Qt.AlignHCenter)
        placeholder_layout.addWidget(self.btn_load_map, 0, Qt.AlignTop | Qt.AlignHCenter)
        placeholder_layout.addStretch(1)
        self.map_host_layout.addWidget(self.map_placeholder, 1)

    def _detach_map_placeholder(self):
        if getattr(self, "map_placeholder", None) is None:
            return
        self.map_host_layout.removeWidget(self.map_placeholder)
        self.map_placeholder.hide()
        self.map_placeholder.deleteLater()
        self.map_placeholder = None
        self.map_placeholder_label = None
        self.btn_load_map = None

    def _create_map_web_view(self):
        webengine_view_cls, webchannel_cls, webengine_settings_cls = _ensure_webengine_classes()
        web = webengine_view_cls()
        web.setMinimumHeight(max(int(460 * self.sf), 380))
        web.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        web.setPage(DebugPage(web))
        settings = web.page().settings()
        settings.setAttribute(webengine_settings_cls.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(webengine_settings_cls.LocalContentCanAccessRemoteUrls, True)

        self.channel = webchannel_cls(web.page())
        self.bridge = MapBridge(
            getattr(self.main_window, "_on_map_click", None) if self.main_window else None,
            getattr(self.main_window, "save_map_layer_preference", None) if self.main_window else None,
        )
        self.channel.registerObject("bridge", self.bridge)
        web.page().setWebChannel(self.channel)

        if self.main_window is not None and hasattr(self.main_window, "_on_map_loaded"):
            web.loadFinished.connect(self.main_window._on_map_loaded)
        web.loadFinished.connect(self._handle_map_load_finished)
        return web

    def ensure_map_web_view(self):
        if self._web_view_initialized and self.web is not None:
            return self.web

        self._detach_map_placeholder()
        self.web = self._create_map_web_view()
        self.map_host_layout.addWidget(self.web, 1)
        self._web_view_initialized = True
        return self.web

    def has_map_web_view(self) -> bool:
        return bool(self._web_view_initialized and self.web is not None)

    def _sync_left_panel_heights(self):
        try:
            if not hasattr(self, "left_panel") or not self.left_panel:
                return

            layout = self.left_panel.layout()
            if layout is None:
                return
            layout.activate()

            margins = layout.contentsMargins()
            available = self.left_panel.height() - margins.top() - margins.bottom()
            if available <= 0:
                return

            fixed_children_height = 0
            if hasattr(self, "group_totals") and self.group_totals:
                if self.group_totals.minimumHeight() == self.group_totals.maximumHeight():
                    fixed_children_height += self.group_totals.maximumHeight()
                else:
                    fixed_children_height += self.group_totals.height() or self.group_totals.sizeHint().height()
            if hasattr(self, "bar_export") and self.bar_export:
                if self.bar_export.minimumHeight() == self.bar_export.maximumHeight():
                    fixed_children_height += self.bar_export.maximumHeight()
                else:
                    fixed_children_height += self.bar_export.height() or self.bar_export.sizeHint().height()

            spacing_count = max(layout.count() - 1, 0)
            available_table_height = available - fixed_children_height - (layout.spacing() * spacing_count)
            target_height = max(available_table_height, 0)
            if self._locked_table_height is not None:
                target_height = min(target_height, self._locked_table_height)
                self.table.setFixedHeight(target_height)
                self.table.updateGeometry()
                return

            # Keep the table bounded by the free space, but do not fix its height:
            # a fixed height raises the window's minimum size after reloads and can
            # push the totals/export area below the screen.
            self.table.setMinimumHeight(0)
            self.table.setMaximumHeight(target_height)
            self.table.updateGeometry()
            layout.activate()
        except RuntimeError:
            return

    def lock_table_height(self):
        current_height = self.table.height()
        if current_height <= 0:
            return

        self._locked_table_height = current_height
        self.table.setFixedHeight(self._locked_table_height)

    def lock_splitter_height(self):
        current_height = self.splitter.height()
        if current_height <= 0:
            return

        self._locked_splitter_height = current_height
        self.splitter.setFixedHeight(current_height)

    def preferred_left_panel_width(self) -> int:
        header = self.table.horizontalHeader()
        visible_columns_width = sum(
            header.sectionSize(index)
            for index in range(header.count())
            if not self.table.isColumnHidden(index)
        )
        table_chrome_width = (
            self.table.verticalHeader().width()
            + (self.table.frameWidth() * 2)
            + self.table.verticalScrollBar().sizeHint().width()
        )
        totals_min_width = self.group_totals.minimumSizeHint().width()
        export_min_width = self.bar_export.minimumSizeHint().width()
        return compute_preferred_left_panel_width(
            visible_columns_width=visible_columns_width,
            table_chrome_width=table_chrome_width,
            totals_min_width=totals_min_width,
            export_min_width=export_min_width,
            panel_gap=self._panel_gap,
        )

    def _crud_buttons_minimum_width(self) -> int:
        buttons = [self.btn_clear, self.btn_add, self.btn_save_edit, self.btn_delete, self.btn_ficha_pdf]
        return compute_crud_buttons_minimum_width(
            [button.minimumSizeHint().width() for button in buttons],
            spacing=self._crud_spacing,
        )

    def preferred_right_panel_width(self) -> int:
        return max(int(340 * self.sf), 320)

    def _update_responsive_constraints(self):
        try:
            if not hasattr(self, "right_panel"):
                return
            preferred_width = self.preferred_right_panel_width()
            self.right_panel.setMinimumWidth(preferred_width)
        except RuntimeError:
            return

    def _is_compact_layout(self) -> bool:
        current_width, current_height = self._current_root_dimensions()
        return current_width <= 1460 or current_height <= 1048

    def _is_tight_layout(self) -> bool:
        current_width, current_height = self._current_root_dimensions()
        return current_width <= 1320 or current_height <= 980

    def _is_short_layout(self) -> bool:
        _, current_height = self._current_root_dimensions()
        return current_height <= 1048

    def _is_very_short_layout(self) -> bool:
        _, current_height = self._current_root_dimensions()
        return current_height <= 960

    def _apply_responsive_layout(self) -> None:
        try:
            compact_mode = self._is_compact_layout()
            tight_mode = self._is_tight_layout()
            short_mode = self._is_short_layout()
            very_short_mode = self._is_very_short_layout()

            self.lbl_workspace_subtitle.setVisible(not tight_mode and not very_short_mode)
            self.lbl_workspace_helper.setVisible(not compact_mode and not short_mode)
            if hasattr(self, "lbl_summary_hint"):
                self.lbl_summary_hint.setVisible(not (tight_mode and short_mode))

            filter_margin = max(int((8 if short_mode else 10) * self.sf), 6)
            filter_spacing = max(int((4 if short_mode else 6) * self.sf), 4)
            self.filters_host_layout.setContentsMargins(filter_margin, filter_margin, filter_margin, filter_margin)
            self.filters_host_layout.setSpacing(filter_spacing)
            self.filters_row.setSpacing(max(int((8 if short_mode else 12) * self.sf), 6))
            self.filters_buttons_layout.setContentsMargins(0, int((8 if short_mode else 12) * self.sf), 0, 0)

            self.btn_clear_filters.setText("Limpar" if compact_mode else "Limpar filtros")
            self.btn_reset_sort.setText("Ordem" if compact_mode else "Restaurar ordem")
            self.btn_columns.setText("Colunas" if compact_mode else "Exibir colunas")
            self.btn_table_full.setText("Expandir tabela")
            self.btn_manage_plantios.setText("Plantios" if compact_mode else "Plantios...")

            self.filter_micro.setMinimumWidth(int((160 if compact_mode else 220) * self.sf))
            self.filter_eletronico.setMinimumWidth(int((110 if compact_mode else 140) * self.sf))
            self.filter_status.setMinimumWidth(int((108 if compact_mode else 130) * self.sf))
            self.filter_year.setMinimumWidth(int((82 if compact_mode else 90) * self.sf))

            compact_filter_button_height = 26 if short_mode else 28
            for button in [self.btn_clear_filters, self.btn_reset_sort, self.btn_columns, self.btn_table_full]:
                button.setMinimumHeight(max(int(compact_filter_button_height * self.sf), 24))

            totals_height = max(
                int(
                    (
                        166
                        if very_short_mode
                        else 174
                        if short_mode
                        else 190
                        if compact_mode
                        else 230
                    )
                    * self.sf
                ),
                148 if very_short_mode else 156 if compact_mode or short_mode else 200,
            )
            self.group_totals.setFixedHeight(totals_height)
            metrics_min_height = max(
                int(((72 if very_short_mode else 80 if short_mode else 92 if compact_mode else 120) * self.sf)),
                68 if very_short_mode else 76,
            )
            self.kpi_table.setMinimumHeight(metrics_min_height)
            self.micro_table.setMinimumHeight(metrics_min_height)

            export_height = max(int(((30 if short_mode else 36 if compact_mode else 42) * self.sf)), 28)
            self.bar_export.setFixedHeight(export_height)
            export_button_height = max(min(export_height - 4, int(28 * self.sf)), 24)
            export_vertical_margin = max((export_height - export_button_height) // 2, 2)
            if hasattr(self, "export_bar_layout"):
                self.export_bar_layout.setContentsMargins(
                    int(8 * self.sf),
                    export_vertical_margin,
                    int(8 * self.sf),
                    export_vertical_margin,
                )
            for button in [self.btn_export_csv, self.btn_export_spreadsheet, self.btn_export_pdf]:
                button.setFixedHeight(export_button_height)
            if hasattr(self, "export_label"):
                self.export_label.setVisible(not tight_mode and not short_mode)

            self.combo_heatmap_type.setMinimumWidth(max(int((120 if compact_mode else 150) * self.sf), 110))
            placeholder_label = getattr(self, "map_placeholder_label", None)
            if placeholder_label is not None:
                placeholder_label.setVisible(not tight_mode)

            input_height = max(int(((25 if very_short_mode else 27 if short_mode else 30) * self.sf)), 24)
            for widget in [
                self.in_oficio,
                self.in_avtec,
                self.in_comp,
                self.in_end,
                self.in_end_plantio,
                self.in_micro,
                self.in_caixa,
                self.btn_manage_plantios,
                self.eletronico_cont,
            ]:
                widget.setFixedHeight(input_height)

            self.chk_sn.setFixedWidth(max(int(((96 if short_mode else 108) * self.sf)), 84))
            form_layout = self.form_group.layout()
            if form_layout is not None:
                side_margin = max(int(((12 if short_mode else 15) * self.sf)), 10)
                top_margin = max(int(((10 if very_short_mode else 12 if short_mode else 14) * self.sf)), 8)
                bottom_margin = max(int(((8 if short_mode else 10) * self.sf)), 8)
                form_layout.setContentsMargins(side_margin, top_margin, side_margin, bottom_margin)
                form_layout.setHorizontalSpacing(max(int(((8 if short_mode else 10) * self.sf)), 6))
                form_layout.setVerticalSpacing(max(int(((7 if very_short_mode else 8 if short_mode else 10) * self.sf)), 6))
                for row_index in range(4):
                    form_layout.setRowMinimumHeight(row_index, input_height)

            map_layout = self.map_group.layout()
            if map_layout is not None:
                map_layout.setContentsMargins(
                    max(int(((8 if short_mode else 10) * self.sf)), 6),
                    max(int(((8 if short_mode else 10) * self.sf)), 6),
                    max(int(((8 if short_mode else 10) * self.sf)), 6),
                    max(int(((8 if short_mode else 10) * self.sf)), 6),
                )
                map_layout.setHorizontalSpacing(max(int(((6 if short_mode else 8) * self.sf)), 4))
                map_layout.setVerticalSpacing(max(int(((4 if short_mode else 6) * self.sf)), 4))
            map_button_height = max(int(((22 if short_mode else 24) * self.sf)), 20)
            for button in [
                self.btn_maps,
                self.btn_maps_plantio,
                self.btn_batch_geo,
                self.btn_map_full,
                self.btn_street_view,
                self.btn_add_layer,
            ]:
                button.setMinimumHeight(map_button_height)
            if self.has_map_web_view():
                map_height = max(
                    int(((380 if very_short_mode else 420 if short_mode else 460) * self.sf)),
                    340 if very_short_mode else 360 if short_mode else 380,
                )
                self.web.setMinimumHeight(map_height)

            self._update_form_group_height()
        except RuntimeError:
            return

    def _finalize_responsive_layout(self) -> None:
        try:
            self._apply_responsive_layout()
            self._update_responsive_constraints()
            self._sync_left_panel_heights()
            self.align_splitter_to_table_width()
        except RuntimeError:
            return

    def _preferred_splitter_anchor_left_width(self) -> int | None:
        if not hasattr(self, "btn_table_full") or not hasattr(self, "splitter"):
            return None

        button = self.btn_table_full
        splitter_rect = self.splitter.geometry()
        if splitter_rect.width() <= 0 or button.width() <= 0:
            return None

        text = button.text() or ""
        target_char_index = resolve_splitter_anchor_character_index(text)
        if target_char_index is None:
            return None

        option = QStyleOptionButton()
        button.initStyleOption(option)
        content_rect = button.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, button)
        full_text_width = button.fontMetrics().horizontalAdvance(text)
        text_origin_x = content_rect.x() + max((content_rect.width() - full_text_width) // 2, 0)

        prefix = text[:target_char_index]
        target_char = text[target_char_index]
        return compute_splitter_anchor_left_width(
            splitter_x=splitter_rect.x(),
            button_x=button.geometry().x(),
            text_origin_x=text_origin_x,
            prefix_width=button.fontMetrics().horizontalAdvance(prefix),
            target_char_width=button.fontMetrics().horizontalAdvance(target_char),
            handle_width=self.splitter.handleWidth(),
            nudge=max(
                int(self._SPLITTER_VISUAL_ANCHOR_NUDGE * max(float(self.sf), 1.0)),
                self._SPLITTER_VISUAL_ANCHOR_NUDGE,
            ),
        )

    def align_splitter_to_table_width(self):
        try:
            if not hasattr(self, "splitter") or self.splitter.count() < 2:
                return

            splitter_rect = self.splitter.contentsRect()
            handle_total_width = self.splitter.handleWidth() * max(self.splitter.count() - 1, 0)
            total_width = splitter_rect.width() - handle_total_width
            if total_width <= 0:
                total_width = sum(self.splitter.sizes())
            if total_width <= 0:
                return

            self._update_responsive_constraints()
            right_min_width = self.right_panel.minimumWidth()
            target_left_width = min(
                max(self.preferred_left_panel_width(), 0),
                max(total_width - right_min_width, 0),
            )
            sizes = compute_splitter_sizes(
                total_width=total_width,
                right_min_width=right_min_width,
                preferred_left_width=target_left_width,
                anchor_left_width=self._preferred_splitter_anchor_left_width(),
            )
            if sizes is None:
                return

            self.splitter.setSizes(list(sizes))
        except RuntimeError:
            return

    def _column_width_bounds(self, attr: str) -> tuple[int, int]:
        bounds = resolve_column_width_bounds(
            attr,
            scale_factor=self.sf,
            rules=self._COLUMN_WIDTH_RULES,
        )
        return bounds.min_width, bounds.max_width

    def _column_texts_for_records(self, attr: str, records: List[Compensacao]) -> List[str]:
        return build_column_texts_for_records(
            attr,
            records,
            static_texts=self._COLUMN_STATIC_TEXTS,
            display_tipo_value=display_tipo_value,
        )

    def resize_table_columns_for_records(self, records: List[Compensacao]):
        effective_records = list(records or [])
        for column_index, attr in enumerate(DISPLAY_COLUMN_ATTRS):
            if self.table.isColumnHidden(column_index):
                continue
            min_width, max_width = self._column_width_bounds(attr)
            self._resize_column_to_texts(
                column_index,
                self._column_texts_for_records(attr, effective_records),
                min_width=min_width,
                max_width=max_width,
            )

    def _resize_column_to_texts(
        self,
        column_index: int,
        texts: List[str],
        *,
        min_width: int | None = None,
        max_width: int | None = None,
    ):
        header = self.table.horizontalHeader()
        if column_index < 0 or column_index >= header.count():
            return

        header_text = self.table_model.headerData(column_index, Qt.Horizontal, Qt.DisplayRole) or ""
        widths = [header.fontMetrics().horizontalAdvance(str(header_text))]
        widths.extend(self.table.fontMetrics().horizontalAdvance(str(text or "")) for text in texts)
        target_width = compute_target_column_width(
            widths,
            padding=max(int(28 * self.sf), 28),
            min_width=min_width,
            max_width=max_width,
        )
        header.resizeSection(column_index, target_width)

    def _build_map_url(self, map_html: str, *, fallback_html: str = "", engine: str = "") -> QUrl:
        url = QUrl.fromLocalFile(map_html)
        query = QUrlQuery()
        query.addQueryItem("mapEngine", str(engine or ""))
        query.addQueryItem("defaultBaseLayer", MAP_DEFAULT_BASE_LAYER)
        if fallback_html:
            query.addQueryItem("fallbackUrl", QUrl.fromLocalFile(fallback_html).toString())
        if engine == "leaflet":
            query.addQueryItem("tileScheme", "compmap")
        url.setQuery(query)
        return url

    def _load_map_engine(self, engine: str | None = None):
        resource = resolve_map_engine_resource(engine)
        map_html = resource.html_path
        if not os.path.exists(map_html):
            if getattr(self, "map_placeholder_label", None) is not None:
                self.map_placeholder_label.setText(
                    "Não foi possível localizar o componente do mapa nesta instalação. Verifique os arquivos do aplicativo antes de seguir com a validação geográfica."
                )
            return

        web = self.ensure_map_web_view()
        self._map_engine = resource.engine
        url = self._build_map_url(
            map_html,
            fallback_html=resource.fallback_html_path,
            engine=resource.engine,
        )
        web.setUrl(url)
        self._map_loaded = True

    def _handle_map_load_finished(self, ok: bool):
        if ok or self._map_fallback_loaded or self._map_engine == "leaflet":
            return
        self._map_fallback_loaded = True
        self._map_loaded = False
        self._load_map_engine("leaflet")

    def load_map(self):
        if self._map_loaded:
            return
        self._load_map_engine()

    def _create_totals_group(self):
        g = QGroupBox("Indicadores do recorte")
        l = QHBoxLayout(g)
        l.setContentsMargins(int(8 * self.sf), int(10 * self.sf), int(8 * self.sf), int(8 * self.sf))
        l.setSpacing(int(8 * self.sf))
        self.kpi_table = QTableView()
        self.kpi_model = QStandardItemModel(0, 2)
        self.kpi_model.setHorizontalHeaderLabels(["Métrica", "Valor"])
        self.kpi_table.setModel(self.kpi_model)
        self.kpi_table.horizontalHeader().setStretchLastSection(True)
        self.kpi_table.setMinimumHeight(int(120 * self.sf))
        self.micro_table = QTableView()
        self.micro_model = QStandardItemModel(0, 2)
        self.micro_model.setHorizontalHeaderLabels(["Microbacia", "Pendente"])
        self.micro_table.setModel(self.micro_model)
        self.micro_table.horizontalHeader().setStretchLastSection(True)
        self.micro_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.micro_table.setMinimumHeight(int(120 * self.sf))
        l.addWidget(self.kpi_table, 1)
        l.addWidget(self.micro_table, 1)
        g.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        g.setFixedHeight(max(int(230 * self.sf), 200))
        return g

    def update_totals_tables(self, metrics: Dict):
        self.kpi_model.removeRows(0, self.kpi_model.rowCount())
        for label, value in build_totals_rows(metrics):
            self.kpi_model.appendRow([QStandardItem(label), QStandardItem(value)])
        self.micro_model.removeRows(0, self.micro_model.rowCount())
        for micro, value in build_micro_rows(metrics):
            self.micro_model.appendRow([QStandardItem(micro), QStandardItem(value)])

    def _create_export_bar(self):
        w = QWidget()
        w.setProperty("panel", "subtle")
        w.setFixedHeight(int(42 * self.sf))
        l = QHBoxLayout(w)
        self.export_bar_layout = l
        l.setContentsMargins(int(8 * self.sf), int(2 * self.sf), int(8 * self.sf), int(2 * self.sf))
        l.setSpacing(int(6 * self.sf))
        export_label = QLabel("Exportação do recorte atual")
        self.export_label = export_label
        export_label.setProperty("role", "helper-strong")
        l.addWidget(export_label)
        self.btn_export_csv = QPushButton("CSV")
        self.btn_export_spreadsheet = QPushButton("Planilha")
        self.btn_export_pdf = QPushButton("PDF")
        for b in [self.btn_export_csv, self.btn_export_spreadsheet, self.btn_export_pdf]:
            b.setProperty("kind", "chip-quiet")
            b.setFixedHeight(max(int(24 * self.sf), 24))
            l.addWidget(b)
        l.addStretch(1)
        return w

    def _create_form_group(self):
        top_margin = max(int(14 * self.sf), 14)
        row_spacing = max(int(10 * self.sf), 10)
        column_spacing = max(int(10 * self.sf), 8)
        input_h = max(int(30 * self.sf), 30)
        label_w = max(int(112 * self.sf), 96)
        primary_field_w = max(int(190 * self.sf), 140)
        secondary_field_w = max(int(150 * self.sf), 110)
        aux_col_w = max(int(108 * self.sf), 90)

        g = QGroupBox("Cadastro do processo")
        g.setObjectName("formGroup")
        l = QGridLayout(g)
        l.setContentsMargins(int(15 * self.sf), top_margin, int(15 * self.sf), int(10 * self.sf))
        l.setHorizontalSpacing(column_spacing)
        l.setVerticalSpacing(row_spacing)

        def mk_lbl(t):
            lbl = QLabel(t)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setMinimumWidth(label_w)
            lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            return lbl

        def mk_in(min_width):
            le = QLineEdit()
            le.setFixedHeight(input_h)
            le.setMinimumWidth(min_width)
            le.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            le.setClearButtonEnabled(True)
            le.setLayoutDirection(Qt.LeftToRight)
            le.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            return le

        self.in_oficio = mk_in(primary_field_w)
        self.in_oficio.setMinimumWidth(max(int(172 * self.sf), 150))
        self.in_oficio.setPlaceholderText("Ex.: 206/2021 - SMMACTI")
        self.in_oficio.setToolTip("Número do ofício ou processo principal do cadastro.")
        self.chk_sn = QCheckBox("S/N")
        self.chk_sn.setMinimumWidth(max(int(86 * self.sf), 76))
        self.chk_sn.setToolTip("Marque quando o cadastro não possuir ofício ou processo definido.")
        self.oficio_sn_container = QWidget()
        self.oficio_sn_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.oficio_sn_layout = QHBoxLayout(self.oficio_sn_container)
        self.oficio_sn_layout.setContentsMargins(0, 0, 0, 0)
        self.oficio_sn_layout.setSpacing(int(16 * self.sf))
        self.oficio_sn_layout.addWidget(self.in_oficio, 1)
        self.oficio_sn_layout.addWidget(self.chk_sn, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self.in_avtec = mk_in(secondary_field_w)
        self.in_avtec.setPlaceholderText("Ex.: 107/2021")
        self.in_avtec.setToolTip("Número da avaliação técnica associada ao cadastro.")
        self.in_comp = mk_in(secondary_field_w)
        self.in_comp.setValidator(QDoubleValidator(0, 9999999, 2))
        self.in_comp.setPlaceholderText("Ex.: 10")
        self.in_comp.setToolTip("Quantidade de compensação prevista para o processo.")
        self.in_end = mk_in(primary_field_w)
        self.in_end.setPlaceholderText("Ex.: Rua José Luiz da Silva")
        self.in_end.setToolTip("Endereço principal utilizado no cadastro.")
        self.in_end_plantio = mk_in(primary_field_w)
        self.in_end_plantio.setReadOnly(True)
        self.in_end_plantio.setEnabled(False)
        self.in_end_plantio.setPlaceholderText("Nenhum plantio cadastrado")
        self.in_end_plantio.setToolTip("Resumo do endereço de plantio cadastrado para o registro.")
        self.in_end_plantio.setMinimumWidth(max(int(220 * self.sf), 170))
        self.btn_manage_plantios = QPushButton("Plantios...")
        self.btn_manage_plantios.setProperty("kind", "chip-quiet")
        self.btn_manage_plantios.setFixedHeight(input_h)
        self.btn_manage_plantios.setToolTip("Abre o editor de plantios vinculados ao cadastro.")
        plantio_button_w = max(int(132 * self.sf), 122)
        self.btn_manage_plantios.setMinimumWidth(plantio_button_w)
        self.btn_manage_plantios.setEnabled(False)
        self.plantio_summary_container = QWidget()
        self.plantio_summary_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.plantio_summary_layout = QHBoxLayout(self.plantio_summary_container)
        self.plantio_summary_layout.setContentsMargins(0, 0, 0, 0)
        self.plantio_summary_layout.setSpacing(0)
        self.plantio_summary_layout.addWidget(self.in_end_plantio, 1)
        self.plantio_actions_container = QWidget()
        self.plantio_actions_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.plantio_actions_layout = QHBoxLayout(self.plantio_actions_container)
        self.plantio_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.plantio_actions_layout.setSpacing(int(8 * self.sf))
        self.in_micro = QComboBox()
        self.in_micro.setEditable(True)
        self.in_micro.setFixedHeight(input_h)
        self.in_micro.setMinimumWidth(secondary_field_w)
        self.in_micro.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.in_micro.setToolTip("Microbacia relacionada ao endereço do cadastro.")
        if self.in_micro.lineEdit() is not None:
            self.in_micro.lineEdit().setClearButtonEnabled(True)
            self.in_micro.lineEdit().setPlaceholderText("Selecione ou digite uma microbacia")
            self.in_micro.lineEdit().setLayoutDirection(Qt.LeftToRight)
            self.in_micro.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.in_caixa = mk_in(secondary_field_w)
        self.in_caixa.setValidator(QIntValidator(0, 999999))
        self.in_caixa.setPlaceholderText("Ex.: 125")
        self.in_caixa.setToolTip("Número da caixa física quando o tipo exigir arquivamento físico.")
        self.chk_arquivado = QCheckBox("Arquivado")
        self.chk_arquivado.setToolTip("Preenche automaticamente a caixa como Arquivado.")
        self.chk_compensado = QCheckBox("Compensado (SIM)")
        self.chk_compensado.setMinimumWidth(max(int(156 * self.sf), 142))
        self.chk_compensado.setToolTip("Marca o cadastro como já compensado.")
        self.plantio_actions_layout.addWidget(self.btn_manage_plantios, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.plantio_actions_layout.addWidget(self.chk_compensado, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.plantio_actions_layout.addStretch(1)

        self.eletronico_cont = QWidget()
        self.eletronico_cont.setFixedHeight(input_h)
        self.eletronico_cont.setMinimumWidth(primary_field_w + aux_col_w)
        self.eletronico_layout = QHBoxLayout(self.eletronico_cont)
        self.eletronico_layout.setContentsMargins(0, 0, 0, 0)
        self.eletronico_layout.setSpacing(int(10 * self.sf))
        self.eletronico_group = QButtonGroup(self)
        self.eletronico_group.setExclusive(True)

        lbl_oficio = mk_lbl("Ofício/Processo:")
        lbl_avtec = mk_lbl("Av. Tec.:")
        lbl_eletronico = mk_lbl("Tipo:")
        lbl_compensacao = mk_lbl("Compensação:")
        lbl_endereco = mk_lbl("Endereço:")
        lbl_microbacia = mk_lbl("Microbacia:")
        lbl_endereco_plantio = mk_lbl("Endereço Plantio:")
        lbl_caixa = mk_lbl("Caixa:")

        l.addWidget(lbl_oficio, 0, 0)
        l.addWidget(self.oficio_sn_container, 0, 1, 1, 2)
        l.addWidget(lbl_avtec, 0, 3)
        l.addWidget(self.in_avtec, 0, 4)

        l.addWidget(lbl_eletronico, 1, 0)
        l.addWidget(self.eletronico_cont, 1, 1, 1, 2)
        l.addWidget(lbl_compensacao, 1, 3)
        l.addWidget(self.in_comp, 1, 4)

        l.addWidget(lbl_endereco, 2, 0)
        l.addWidget(self.in_end, 2, 1, 1, 2)
        l.addWidget(lbl_microbacia, 2, 3)
        l.addWidget(self.in_micro, 2, 4)

        l.addWidget(lbl_endereco_plantio, 3, 0)
        l.addWidget(self.plantio_summary_container, 3, 1, 1, 2)
        l.addWidget(lbl_caixa, 3, 3)
        l.addWidget(self.in_caixa, 3, 4)

        l.addWidget(self.plantio_actions_container, 4, 1, 1, 3)
        l.addWidget(self.chk_arquivado, 4, 4)

        l.setColumnMinimumWidth(0, label_w)
        l.setColumnMinimumWidth(1, primary_field_w)
        l.setColumnMinimumWidth(2, aux_col_w + int(10 * self.sf))
        l.setColumnMinimumWidth(3, label_w)
        l.setColumnMinimumWidth(4, secondary_field_w)
        l.setRowMinimumHeight(0, input_h)
        l.setRowMinimumHeight(1, input_h)
        l.setRowMinimumHeight(2, input_h)
        l.setRowMinimumHeight(3, input_h)
        l.setColumnStretch(1, 1)
        l.setColumnStretch(2, 0)
        l.setColumnStretch(4, 1)
        g.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return g

    def _update_form_group_height(self):
        if not hasattr(self, "form_group") or self.form_group is None:
            return

        target_height = self.form_group.minimumSizeHint().height()
        if target_height > 0 and self.form_group.minimumHeight() != target_height:
            self.form_group.setMinimumHeight(target_height)

    def _create_map_group(self):
        g = QGroupBox("Mapa e geocodificação")
        l = QGridLayout(g)
        l.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        l.setHorizontalSpacing(int(8 * self.sf))
        l.setVerticalSpacing(int(6 * self.sf))
        self.btn_maps = QPushButton("Buscar Endereço")
        self.btn_maps_plantio = QPushButton("Buscar Plantio")
        self.btn_batch_geo = QPushButton("GPS em Lote")
        self.btn_map_full = QPushButton("Mapa ampliado")
        self.btn_street_view = QPushButton("Street View")
        self.btn_add_layer = QPushButton("Adicionar Camada GIS")
        self.btn_add_layer.setToolTip("Adicione camadas externas ao mapa (.geojson, .json ou .kml)")
        self.chk_heatmap = QCheckBox("Mapa de Calor")
        self.chk_heatmap.setToolTip("Liga ou desliga a camada de mapa de calor.")
        self.combo_heatmap_type = QComboBox()
        self.combo_heatmap_type.addItems(["Pendentes", "Realizadas", "Tudo"])
        self.combo_heatmap_type.setMinimumWidth(max(int(150 * self.sf), 120))
        self.combo_heatmap_type.setToolTip("Escolhe qual conjunto de registros alimentar no mapa de calor.")
        self.map_notice_label = QLabel("")
        self.map_notice_label.setObjectName("MapNoticeLabel")
        self.map_notice_label.setWordWrap(True)
        self.map_notice_label.setVisible(False)
        for b in [self.btn_maps, self.btn_maps_plantio, self.btn_batch_geo, self.btn_map_full, self.btn_street_view, self.btn_add_layer]:
            b.setMinimumHeight(int(24 * self.sf))
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for b in [self.btn_map_full, self.btn_street_view, self.btn_add_layer]:
            b.setProperty("kind", "chip-quiet")
        self.btn_maps.setProperty("kind", "primary")
        self.btn_maps_plantio.setProperty("kind", "primary")
        self.btn_batch_geo.setProperty("kind", "secondary")
        self.btn_maps.setToolTip("Geocodifica o endereço principal e posiciona o mapa.")
        self.btn_maps_plantio.setToolTip("Geocodifica o endereço de plantio cadastrado.")
        self.btn_batch_geo.setToolTip("Atualiza coordenadas em lote para os registros filtrados.")
        self.btn_map_full.setToolTip("Abre o mapa em tela cheia com os overlays atuais.")
        self.btn_street_view.setToolTip("Abre o ponto atual no Google Street View.")
        l.addWidget(self.btn_maps, 0, 0)
        l.addWidget(self.btn_maps_plantio, 0, 1)
        l.addWidget(self.btn_batch_geo, 1, 0)
        l.addWidget(self.btn_map_full, 1, 1)
        l.addWidget(self.btn_street_view, 2, 0)
        l.addWidget(self.btn_add_layer, 2, 1)
        l.addWidget(self.chk_heatmap, 3, 0)
        l.addWidget(self.combo_heatmap_type, 3, 1)
        l.addWidget(self.map_notice_label, 4, 0, 1, 2)
        l.setColumnStretch(0, 1)
        l.setColumnStretch(1, 1)
        return g

    def set_map_notice(self, message: str = ""):
        text = str(message or "").strip()
        self.map_notice_label.setText(text)
        self.map_notice_label.setVisible(bool(text))


