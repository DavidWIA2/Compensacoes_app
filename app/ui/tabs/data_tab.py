import os
from typing import List, Dict, Optional

from PySide6.QtCore import Qt, QUrl, QUrlQuery
from PySide6.QtGui import QIntValidator, QDoubleValidator, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTableView, QHeaderView,
    QGroupBox, QGridLayout, QLabel, QLineEdit, QCheckBox, QComboBox,
    QPushButton, QSizePolicy, QButtonGroup, QStyle, QStyleOptionButton, QFrame,
    QMenu, QToolButton,
)
from app.models.compensacao import Compensacao
from app.models.display_columns import DISPLAY_COLUMN_ATTRS, display_column_index
from app.config import MAP_DEFAULT_BASE_LAYER
from app.services.map_engine import resolve_map_engine_resource
from app.services.mapbox_config import read_mapbox_usage, resolve_mapbox_access_token
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
    compute_preferred_right_panel_width,
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
        self.lbl_workspace_subtitle = QLabel(
            "Consulta operacional da base, filtros do recorte e edição do cadastro em andamento."
        )
        self.lbl_workspace_subtitle.setProperty("role", "page-subtitle")
        self.lbl_workspace_helper = QLabel(
            "Use a grade para localizar processos e o painel lateral para revisar cadastro, plantios e mapa."
        )
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
        quick_filters_layout.addWidget(QLabel("Filtros rápidos:"))
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

        self.quality_filter_buttons: Dict[str, QPushButton] = {}
        quality_filters_layout = quick_filters_layout
        self.quality_filters_layout = quality_filters_layout
        quality_filters_layout.addSpacing(int(8 * self.sf))
        quality_filters_layout.addWidget(QLabel("Qualidade:"))
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

        actions_row = quick_filters_layout
        self.actions_row = actions_row
        actions_row.addStretch(1)
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
        r_lay.setSpacing(int(6 * self.sf))
        self.lbl_form_context = QLabel(
            "O painel lateral concentra o cadastro do processo, plantios vinculados e ações de geocodificação."
        )
        self.lbl_form_context.setProperty("role", "helper")
        self.lbl_form_context.setWordWrap(True)
        r_lay.addWidget(self.lbl_form_context, 0)
        self.form_group = self._create_form_group()
        self._update_form_group_height()
        r_lay.addWidget(self.form_group, 0)

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
        r_lay.addWidget(crud_frame, 0)

        self.map_group = self._create_map_group()
        r_lay.addWidget(self.map_group)

        self.map_host = QWidget()
        self.map_host.setMinimumHeight(0)
        self.map_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.map_host_layout = QVBoxLayout(self.map_host)
        self.map_host_layout.setContentsMargins(0, 0, 0, 0)
        self.map_host_layout.setSpacing(0)
        self._build_map_placeholder()
        r_lay.addWidget(self.map_host, 1)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self._update_responsive_constraints()
        self._apply_responsive_layout()
        self.splitter.setSizes([max(int(980 * self.sf), 720), self.right_panel.minimumWidth()])
        schedule_owned_single_shot(self, 0, self._sync_left_panel_heights)
        schedule_owned_single_shot(self, 0, self._update_responsive_constraints)
        schedule_owned_single_shot(self, 0, self.align_splitter_to_table_width)

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

        self.map_placeholder_label = QLabel(
            "O mapa embutido é carregado sob demanda para manter a abertura do app estável. Use-o quando precisar validar endereço, microbacia ou plantio no contexto do cadastro."
        )
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
        web.setMinimumHeight(int(350 * self.sf))
        web.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        web.setPage(DebugPage(web))
        settings = web.page().settings()
        settings.setAttribute(webengine_settings_cls.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(webengine_settings_cls.LocalContentCanAccessRemoteUrls, True)

        self.channel = webchannel_cls(web.page())
        self.bridge = MapBridge(
            getattr(self.main_window, "_on_map_click", None) if self.main_window else None,
            getattr(self.main_window, "save_map_layer_preference", None) if self.main_window else None,
            getattr(self.main_window, "_on_mapbox_tiles_requested", None) if self.main_window else None,
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
        return compute_preferred_right_panel_width(
            scale_factor=self.sf,
            map_group_width=self.map_group.minimumSizeHint().width() if hasattr(self, "map_group") else None,
            crud_buttons_width=self._crud_buttons_minimum_width() if hasattr(self, "btn_ficha_pdf") else None,
            form_group_width=(
                self.form_group.minimumSizeHint().width() + max(int(12 * self.sf), 12)
                if hasattr(self, "form_group")
                else None
            ),
        )

    def _update_responsive_constraints(self):
        try:
            if not hasattr(self, "right_panel"):
                return
            preferred_width = self.preferred_right_panel_width()
            self.right_panel.setMinimumWidth(max(preferred_width, 520))
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
            self.lbl_form_context.setVisible(not compact_mode and not short_mode)

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
                    int(((200 if very_short_mode else 230 if short_mode else 350) * self.sf)),
                    170 if very_short_mode else 205 if short_mode else 280,
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
            mapbox_token = resolve_mapbox_access_token()
            if mapbox_token:
                mapbox_usage = read_mapbox_usage()
                query.addQueryItem("mapboxToken", mapbox_token)
                query.addQueryItem("mapboxUsageMonth", mapbox_usage.month)
                query.addQueryItem("mapboxTileUsed", str(mapbox_usage.tiles_used))
                query.addQueryItem("mapboxTileLimit", str(mapbox_usage.monthly_limit))
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
        self.in_oficio.setPlaceholderText("Ex.: 206/2021 - SMMACTI")
        self.in_oficio.setToolTip("Número do ofício ou processo principal do cadastro.")
        self.chk_sn = QCheckBox("S/N")
        self.chk_sn.setFixedWidth(aux_col_w)
        self.chk_sn.setToolTip("Marque quando o cadastro não possuir ofício ou processo definido.")

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
        l.addWidget(self.in_oficio, 0, 1)
        l.addWidget(self.chk_sn, 0, 2, Qt.AlignLeft | Qt.AlignVCenter)
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

        l.addWidget(self.plantio_actions_container, 4, 1, 1, 2)
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
        for b in [self.btn_maps, self.btn_maps_plantio, self.btn_map_full, self.btn_street_view, self.btn_add_layer]:
            b.setProperty("kind", "chip-quiet")
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


