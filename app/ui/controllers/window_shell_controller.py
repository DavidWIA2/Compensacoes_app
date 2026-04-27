from __future__ import annotations

import os
from typing import List, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIntValidator, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.application.use_cases.authoritative_persistence import AuthoritativePersistenceUseCases
from app.application.use_cases.local_record_queries import (
    LocalFilterFacetsResult,
    LocalRecordQueriesUseCases,
)
from app.application.use_cases.persistence_monitoring import (
    PersistenceRecordOverviewReport,
    PersistenceStatusReport,
)
from app.config import APP_WINDOW_TITLE
from app.services.access_service import AccessAuthError
from app.models.display_columns import DISPLAY_COLUMN_ATTRS, DISPLAY_COLUMN_LABELS
from app.services.records_service import (
    STANDARD_TIPO_OPTIONS,
    TIPO_OFICIO,
    TIPO_NULO,
    compute_metrics,
    display_tipo_value,
    normalize_microbacia_key,
    remove_accents,
    tipo_is_eletronico,
    unique_non_empty,
)
from app.ui.components.access_dialog import ChangePasswordDialog
from app.ui.components.themes import THEME_DARK, THEME_LIGHT, get_app_qss
from app.ui.components.widgets import ColumnsDialog
from app.ui.controllers.window_shell_support import (
    COMPENSACOES_SEARCH_PLACEHOLDER as SUPPORT_COMPENSACOES_SEARCH_PLACEHOLDER,
    TCRA_SEARCH_PLACEHOLDER as SUPPORT_TCRA_SEARCH_PLACEHOLDER,
    build_user_identity_label_text,
    build_user_identity_tooltip_text,
    build_window_chrome_snapshot,
)
from app.ui.controllers.window_layout_support import (
    apply_window_responsive_layout,
    fit_window_to_available_geometry,
)
from app.utils.logger import get_logger


logger = get_logger("UI.WindowShell")


class WindowShellController:
    TCRA_SEARCH_PLACEHOLDER = SUPPORT_TCRA_SEARCH_PLACEHOLDER
    COMPENSACOES_SEARCH_PLACEHOLDER = SUPPORT_COMPENSACOES_SEARCH_PLACEHOLDER

    def __init__(self, window):
        self.window = window
        self.persistence = getattr(window, "authoritative_persistence", None)
        self.persistence_use_cases = getattr(window, "persistence_monitoring_use_cases", None)
        self.local_record_queries = (
            self.persistence.local_record_queries
            if isinstance(self.persistence, AuthoritativePersistenceUseCases)
            else LocalRecordQueriesUseCases(getattr(window, "persistence_service", None))
        )
        self._search_context = "compensacoes"
        self._compensacoes_search_text = ""
        self._syncing_global_search = False
        self._last_selected_tipo = ""
        self._secondary_status_widgets: list[QWidget] = []
        self._tertiary_status_widgets: list[QWidget] = []

    def _bind_runtime_persistence_service(self) -> None:
        if isinstance(self.persistence, AuthoritativePersistenceUseCases):
            self.persistence.bind_runtime_window(self.window)
            return
        self.local_record_queries.snapshot_reader = getattr(self.window, "persistence_service", None)

    def setup_ui(self):
        central = QWidget()
        self.window.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(5, 5, 5, 0)
        layout.setSpacing(4)

        toolbar_frame = QFrame(central)
        toolbar_frame.setObjectName("ShellToolbar")
        toolbar_frame.setProperty("panel", "toolbar")
        top = QHBoxLayout(toolbar_frame)
        self.toolbar_layout = top
        top.setContentsMargins(
            int(10 * self.window.scale_factor),
            int(8 * self.window.scale_factor),
            int(10 * self.window.scale_factor),
            int(8 * self.window.scale_factor),
        )
        top.setSpacing(int(8 * self.window.scale_factor))

        self.window.search = QLineEdit()
        self.window.search.setPlaceholderText(self.COMPENSACOES_SEARCH_PLACEHOLDER)
        self.window.search.setClearButtonEnabled(True)
        self.window.search.setMinimumHeight(int(30 * self.window.scale_factor))
        self.window.search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.window.search.setToolTip("Busca global do módulo atualmente aberto.")

        search_panel = QFrame(toolbar_frame)
        self.window.search_panel = search_panel
        search_panel.setProperty("panel", "glass")
        search_panel_layout = QVBoxLayout(search_panel)
        self.search_panel_layout = search_panel_layout
        search_panel_layout.setContentsMargins(
            int(10 * self.window.scale_factor),
            int(6 * self.window.scale_factor),
            int(10 * self.window.scale_factor),
            int(6 * self.window.scale_factor),
        )
        search_panel_layout.setSpacing(int(3 * self.window.scale_factor))
        search_header = QHBoxLayout()
        search_header.setContentsMargins(0, 0, 0, 0)
        search_header.setSpacing(int(6 * self.window.scale_factor))
        search_caption = QLabel("Busca global")
        search_caption.setProperty("role", "panel-caption")
        self.window.search_context_label = QLabel("Compensações • recorte ativo")
        self.window.search_context_label.setProperty("role", "context-chip")
        self.window.search_context_label.setToolTip(
            "O campo de busca acompanha automaticamente o módulo atualmente aberto."
        )
        search_header.addWidget(search_caption, 0)
        search_header.addWidget(self.window.search_context_label, 0)
        search_header.addStretch(1)
        self.window.search_helper_label = QLabel(
            "Use a busca superior para localizar rapidamente itens no módulo em foco."
        )
        self.window.search_helper_label.setProperty("role", "helper")
        self.window.search_helper_label.setWordWrap(True)
        search_panel_layout.addLayout(search_header)
        search_panel_layout.addWidget(self.window.search_helper_label, 0)
        search_panel_layout.addWidget(self.window.search, 0)

        self.window.btn_theme = QPushButton("Tema")
        self.window.btn_theme.setProperty("kind", "ghost")
        self.window.btn_theme.setMinimumWidth(int(56 * self.window.scale_factor))
        self.window.btn_theme.setMaximumWidth(int(72 * self.window.scale_factor))
        self.window.btn_theme.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.window.btn_theme.setToolTip("Alterna entre tema claro e escuro.")

        self.window.btn_change_password = QPushButton("Alterar senha")
        self.window.btn_change_password.setProperty("kind", "ghost")
        self.window.btn_change_password.setMinimumWidth(int(108 * self.window.scale_factor))
        self.window.btn_change_password.setMaximumWidth(int(132 * self.window.scale_factor))
        self.window.btn_change_password.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.window.btn_change_password.setAutoDefault(False)
        self.window.btn_change_password.setDefault(False)
        self.window.btn_change_password.setFocusPolicy(Qt.ClickFocus)
        self.window.btn_change_password.setEnabled(False)
        self.window.btn_change_password.setToolTip(
            "Abre a troca de senha da conta institucional autenticada."
        )
        self.window.btn_change_password.setVisible(self.can_change_password())

        self.window.session_user_label = QLabel(
            build_user_identity_label_text(getattr(self.window, "access_session", None))
        )
        self.window.session_user_label.setProperty("role", "account-name")
        self.window.session_user_label.setToolTip(
            build_user_identity_tooltip_text(getattr(self.window, "access_session", None))
        )
        self.window.session_user_label.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
        self.window.session_user_label.setMinimumWidth(0)
        self.window.session_user_label.setMaximumWidth(int(220 * self.window.scale_factor))

        self.window.session_role_label = QLabel(self._build_account_role_text())
        self.window.session_role_label.setProperty("role", "context-chip")
        self.window.session_role_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.window.session_role_label.setMinimumWidth(0)
        self.window.session_role_label.setMaximumWidth(int(150 * self.window.scale_factor))

        self.window.session_context_label = QLabel(self._build_account_context_text())
        self.window.session_context_label.setProperty("role", "account-meta")
        self.window.session_context_label.setWordWrap(True)
        self.window.session_context_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self.window.btn_sign_out = QPushButton("Sair")
        self.window.btn_sign_out.setProperty("kind", "secondary")
        self.window.btn_sign_out.setMinimumWidth(int(60 * self.window.scale_factor))
        self.window.btn_sign_out.setMaximumWidth(int(82 * self.window.scale_factor))
        self.window.btn_sign_out.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.window.btn_sign_out.setAutoDefault(False)
        self.window.btn_sign_out.setDefault(False)
        self.window.btn_sign_out.setFocusPolicy(Qt.ClickFocus)
        self.window.btn_sign_out.setEnabled(False)
        self.window.btn_sign_out.setToolTip("Encerra a sessão atual e volta para a tela de acesso.")

        account_panel = QFrame(toolbar_frame)
        self.window.account_panel = account_panel
        account_panel.setProperty("panel", "glass")
        account_layout = QVBoxLayout(account_panel)
        self.account_layout = account_layout
        account_layout.setContentsMargins(
            int(8 * self.window.scale_factor),
            int(6 * self.window.scale_factor),
            int(8 * self.window.scale_factor),
            int(6 * self.window.scale_factor),
        )
        account_layout.setSpacing(int(4 * self.window.scale_factor))
        account_caption_row = QHBoxLayout()
        account_caption_row.setContentsMargins(0, 0, 0, 0)
        account_caption_row.setSpacing(int(6 * self.window.scale_factor))
        account_caption = QLabel("Conta ativa")
        account_caption.setProperty("role", "panel-caption")
        self.window.account_environment_chip = QLabel(
            getattr(
                getattr(self.window, "access_session", None),
                "environment_chip_text",
                "Ambiente: Contingência local",
            )
        )
        self.window.account_environment_chip.setProperty("role", "context-chip")
        self.window.account_environment_chip.setToolTip(
            getattr(
                getattr(self.window, "access_session", None),
                "environment_tooltip_text",
                "Inicialização local sem gateway de autenticação.",
            )
        )
        account_caption_row.addWidget(account_caption, 0)
        account_caption_row.addWidget(self.window.account_environment_chip, 0)
        account_caption_row.addStretch(1)
        account_layout.addLayout(account_caption_row)
        account_actions_row = QHBoxLayout()
        self.account_actions_row = account_actions_row
        account_actions_row.setContentsMargins(0, 0, 0, 0)
        account_actions_row.setSpacing(int(5 * self.window.scale_factor))
        account_actions_row.addWidget(self.window.session_user_label)
        account_actions_row.addWidget(self.window.session_role_label)
        account_actions_row.addStretch(1)
        account_actions_row.addWidget(self.window.btn_theme)
        account_actions_row.addWidget(self.window.btn_change_password)
        account_actions_row.addWidget(self.window.btn_sign_out)
        account_layout.addLayout(account_actions_row)
        account_layout.addWidget(self.window.session_context_label)

        top.addWidget(search_panel, 1)
        top.addWidget(account_panel, 0)
        layout.addWidget(toolbar_frame)

        self.window.tabs = QTabWidget()
        self.window.data_tab = self.window._data_tab_cls(self.window)
        self.window.dash_tab = self.window._dashboard_tab_cls(self.window)
        self.window.operations_tab = self.window._operations_tab_cls(self.window)
        self.window.tcra_tab = self.window._tcra_tab_cls(self.window)
        self.window.admin_users_tab = None
        admin_tab_cls = getattr(self.window, "_admin_users_tab_cls", None)
        if self._can_show_admin_users_tab() and admin_tab_cls is not None:
            self.window.admin_users_tab = admin_tab_cls(
                self.window,
                admin_service=getattr(self.window, "admin_users_service", None),
            )
        self.window.data_tab.search = self.window.search
        self.window.search.textChanged.connect(self._on_global_search_changed)
        if hasattr(self.window.tcra_tab, "search_input"):
            self.window.tcra_tab.search_input.textChanged.connect(self._on_tcra_search_changed)
        self.window.tabs.addTab(self.window.data_tab, "Compensações")
        self.window.tabs.addTab(self.window.tcra_tab, "TCRAs")
        self.window.tabs.addTab(self.window.dash_tab, "Painel")
        self.window.tabs.addTab(self.window.operations_tab, "Opera\u00e7\u00f5es")
        if self.window.admin_users_tab is not None:
            self.window.tabs.addTab(self.window.admin_users_tab, "Administração")
        layout.addWidget(self.window.tabs)
        self.window.tabs.setTabText(0, "Compensações")
        self.window.tabs.setTabText(self.window.tabs.indexOf(self.window.tcra_tab), "TCRAs")
        self.window.tabs.setTabText(self.window.tabs.indexOf(self.window.dash_tab), "Painel")
        self.window.tabs.setTabText(self.window.tabs.indexOf(self.window.operations_tab), "Operações")
        if self.window.admin_users_tab is not None:
            self.window.tabs.setTabText(self.window.tabs.indexOf(self.window.admin_users_tab), "Administração")

        self.window.progress_bar = QProgressBar()
        self.window.progress_bar.setMaximumWidth(200)
        self.window.progress_bar.setVisible(False)

        self.window.progress_cancel_button = QPushButton("Cancelar")
        self.window.progress_cancel_button.setProperty("kind", "secondary")
        self.window.progress_cancel_button.setVisible(False)
        self.window.progress_cancel_button.clicked.connect(self.window.cancel_active_operation)

        self.window.form_state_label = QLabel("Sem altera\u00e7\u00f5es")
        self.window.form_state_label.setObjectName("FormStateLabel")

        self.window.statusBar().addPermanentWidget(self.window.progress_bar)
        self.window.statusBar().addPermanentWidget(self.window.progress_cancel_button)
        self.window.statusBar().addPermanentWidget(self.window.form_state_label)

        self.window.session_file_label = QLabel("Base: aguardando")
        self.window.session_file_label.setObjectName("StatusChip")
        self.window.session_file_label.setMinimumWidth(0)
        self.window.session_file_label.setMaximumWidth(int(280 * self.window.scale_factor))
        self.window.session_file_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.window.session_file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        environment_chip_text = getattr(
            getattr(self.window, "access_session", None),
            "environment_chip_text",
            "Ambiente: Contingência local",
        )
        environment_chip_tooltip = getattr(
            getattr(self.window, "access_session", None),
            "environment_tooltip_text",
            "Inicialização local sem gateway de autenticação.",
        )
        self.window.session_environment_label = QLabel(environment_chip_text)
        self.window.session_environment_label.setObjectName("StatusChip")
        self.window.session_environment_label.setToolTip(environment_chip_tooltip)

        self.window.session_records_label = QLabel("Registros: 0")
        self.window.session_records_label.setObjectName("StatusChip")

        self.window.session_sync_label = QLabel("Sincronia: aguardando")
        self.window.session_sync_label.setObjectName("StatusChip")

        self.window.session_write_label = QLabel("Escrita: aguardando")
        self.window.session_write_label.setObjectName("StatusChip")

        self.window.session_selection_label = QLabel("Seleção: nova")
        self.window.session_selection_label.setObjectName("StatusChip")

        self._secondary_status_widgets = [
            self.window.session_environment_label,
            self.window.session_write_label,
            self.window.session_selection_label,
        ]
        self._tertiary_status_widgets = [
            self.window.form_state_label,
            self.window.session_file_label,
        ]

        self.window.statusBar().addPermanentWidget(self.window.session_environment_label)
        self.window.statusBar().addPermanentWidget(self.window.session_file_label)
        self.window.statusBar().addPermanentWidget(self.window.session_records_label)
        self.window.statusBar().addPermanentWidget(self.window.session_sync_label)
        self.window.statusBar().addPermanentWidget(self.window.session_write_label)
        self.window.statusBar().addPermanentWidget(self.window.session_selection_label)
        self.window.statusBar().setSizeGripEnabled(False)
        self.window.statusBar().setStyleSheet("QStatusBar::item { border: none; }")
        self.update_filters_from_records()
        self.setup_dynamic_form_options_from_records()
        self.sync_global_search_context()
        self.refresh_window_chrome()
        apply_window_responsive_layout(self.window)

    def _can_show_admin_users_tab(self) -> bool:
        access_session = getattr(self.window, "access_session", None)
        environment = str(getattr(access_session, "environment", "") or "").strip().lower()
        role = str(getattr(access_session, "app_role", "") or "").strip().lower()
        return environment == "production" and role == "admin"

    def can_change_password(self) -> bool:
        access_session = getattr(self.window, "access_session", None)
        environment = str(getattr(access_session, "environment", "") or "").strip().lower()
        user_email = str(getattr(access_session, "user_email", "") or "").strip()
        is_anonymous = bool(getattr(access_session, "is_anonymous", False))
        return environment == "production" and bool(user_email) and not is_anonymous

    def _build_account_role_text(self) -> str:
        access_session = getattr(self.window, "access_session", None)
        role = str(getattr(access_session, "app_role", "") or "").strip().lower()
        if role == "admin":
            return "Perfil: administrador do sistema"
        if role == "viewer":
            return "Perfil: leitura"
        if role:
            return "Perfil: edição"
        environment = str(getattr(access_session, "environment", "") or "").strip().lower()
        if environment == "demo":
            return "Perfil: demonstração"
        return "Perfil: local"

    def _build_account_context_text(self) -> str:
        access_session = getattr(self.window, "access_session", None)
        environment = str(getattr(access_session, "environment", "") or "").strip().lower()
        if environment == "production":
            return "Sessão corporativa autenticada na produção oficial, com base protegida e sincronização ativa."
        if environment == "demo":
            return "Sessão isolada para treinamento e validação visual, sem escrita na base oficial."
        return "Sessão local de contingência para uso offline e suporte operacional."

    def _update_top_shell_context(self) -> None:
        if hasattr(self.window, "search_context_label"):
            if self._search_context == "tcra":
                self.window.search_context_label.setText("TCRAs • busca operacional")
                self.window.search_helper_label.setText(
                    "Busque processos, termos, eventos, responsáveis ou pendências do módulo TCRA."
                )
            elif self._search_context == "admin":
                self.window.search_context_label.setText("Administração • ambiente oficial")
                self.window.search_helper_label.setText(
                    "A gestão de usuários usa filtros próprios e só fica disponível para administradores ativos na produção oficial."
                )
            else:
                self.window.search_context_label.setText("Compensações • recorte ativo")
                self.window.search_helper_label.setText(
                    "Busque ofícios, av. tec., endereços ou microbacias diretamente pelo topo."
                )

        access_session = getattr(self.window, "access_session", None)
        if hasattr(self.window, "session_role_label"):
            self.window.session_role_label.setText(self._build_account_role_text())
        if hasattr(self.window, "session_context_label"):
            self.window.session_context_label.setText(self._build_account_context_text())
        if hasattr(self.window, "account_environment_chip"):
            self.window.account_environment_chip.setText(
                getattr(access_session, "environment_chip_text", "Ambiente: Contingência local")
            )
        can_change_password = self.can_change_password()
        if hasattr(self.window, "btn_change_password"):
            self.window.btn_change_password.setVisible(can_change_password)
        if hasattr(self.window, "action_change_password"):
            self.window.action_change_password.setVisible(can_change_password)

    def _is_compact_layout(self) -> bool:
        try:
            current_width = self.window.width()
            current_height = self.window.height()
            is_visible = self.window.isVisible()
            screen = self.window.screen() or QApplication.instance().primaryScreen()
        except RuntimeError:
            return False
        if screen is not None:
            available = screen.availableGeometry() if hasattr(screen, "availableGeometry") else screen.geometry()
            if current_width > 0:
                current_width = min(current_width, available.width())
            if current_height > 0:
                current_height = min(current_height, available.height())
        if current_width < 900 and not is_visible:
            current_width = available.width() if screen is not None else 1920
        if current_height < 640 and not is_visible:
            current_height = available.height() if screen is not None else 1080
        return current_width <= 1460 or current_height <= 980

    def _is_tight_layout(self) -> bool:
        try:
            current_width = self.window.width()
            current_height = self.window.height()
            is_visible = self.window.isVisible()
            screen = self.window.screen() or QApplication.instance().primaryScreen()
        except RuntimeError:
            return False
        if screen is not None:
            available = screen.availableGeometry() if hasattr(screen, "availableGeometry") else screen.geometry()
            if current_width > 0:
                current_width = min(current_width, available.width())
            if current_height > 0:
                current_height = min(current_height, available.height())
        if current_width < 900 and not is_visible:
            current_width = available.width() if screen is not None else 1920
        if current_height < 640 and not is_visible:
            current_height = available.height() if screen is not None else 1080
        return current_width <= 1320 or current_height <= 900

    def _is_stacked_toolbar_layout(self) -> bool:
        try:
            current_width = self.window.width()
            current_height = self.window.height()
            is_visible = self.window.isVisible()
            screen = self.window.screen() or QApplication.instance().primaryScreen()
        except RuntimeError:
            return False
        if screen is not None:
            available = screen.availableGeometry() if hasattr(screen, "availableGeometry") else screen.geometry()
            if current_width > 0:
                current_width = min(current_width, available.width())
            if current_height > 0:
                current_height = min(current_height, available.height())
        if current_width < 900 and not is_visible:
            current_width = available.width() if screen is not None else 1920
        if current_height < 640 and not is_visible:
            current_height = available.height() if screen is not None else 1080
        return current_width <= 1460 or current_height <= 900

    def apply_responsive_layout(self) -> None:
        try:
            scale_factor = self.window.scale_factor
        except RuntimeError:
            return
        try:
            compact_mode = self._is_compact_layout()
            tight_mode = self._is_tight_layout()
            stacked_toolbar_mode = self._is_stacked_toolbar_layout()
            if hasattr(self, "toolbar_layout"):
                target_direction = (
                    QBoxLayout.Direction.TopToBottom
                    if stacked_toolbar_mode
                    else QBoxLayout.Direction.LeftToRight
                )
                if self.toolbar_layout.direction() != target_direction:
                    self.toolbar_layout.setDirection(target_direction)
                self.toolbar_layout.setSpacing(
                    int((6 if compact_mode else 8) * scale_factor)
                )
            if hasattr(self.window, "search_panel"):
                self.window.search_panel.setSizePolicy(
                    QSizePolicy.Expanding,
                    QSizePolicy.Fixed,
                )
            if hasattr(self.window, "account_panel"):
                self.window.account_panel.setSizePolicy(
                    QSizePolicy.Expanding if stacked_toolbar_mode else QSizePolicy.Preferred,
                    QSizePolicy.Fixed,
                )
            if hasattr(self.window, "search"):
                self.window.search.setMinimumHeight(
                    max(int((28 if compact_mode else 30) * scale_factor), 26)
                )
            if hasattr(self.window, "search_helper_label"):
                self.window.search_helper_label.setVisible(not compact_mode)
            if hasattr(self.window, "search_context_label"):
                self.window.search_context_label.setVisible(not tight_mode)
            if hasattr(self.window, "session_context_label"):
                self.window.session_context_label.setVisible(not compact_mode)
            if hasattr(self.window, "account_environment_chip"):
                self.window.account_environment_chip.setVisible(not tight_mode)
            if hasattr(self.window, "session_role_label"):
                self.window.session_role_label.setVisible(not tight_mode)
                self.window.session_role_label.setMaximumWidth(
                    max(int((118 if compact_mode else 150) * scale_factor), 90)
                )
            if hasattr(self.window, "session_user_label"):
                self.window.session_user_label.setMaximumWidth(
                    max(
                        int(
                            (
                                180
                                if stacked_toolbar_mode
                                else 150 if tight_mode else 220 if compact_mode else 260
                            )
                            * scale_factor
                        ),
                        110,
                    )
                )
            if hasattr(self.window, "session_file_label"):
                self.window.session_file_label.setMaximumWidth(
                    max(int((180 if compact_mode else 280) * scale_factor), 132)
                )
            if hasattr(self.window, "btn_theme"):
                self.window.btn_theme.setMaximumWidth(
                    max(int((52 if tight_mode else 56 if compact_mode else 72) * scale_factor), 48)
                )
            if hasattr(self.window, "btn_change_password"):
                self.window.btn_change_password.setMaximumWidth(
                    max(int((92 if tight_mode else 108 if compact_mode else 132) * scale_factor), 78)
                )
            if hasattr(self.window, "btn_sign_out"):
                self.window.btn_sign_out.setMaximumWidth(
                    max(int((58 if tight_mode else 62 if compact_mode else 82) * scale_factor), 52)
                )
            if hasattr(self.window, "progress_bar"):
                self.window.progress_bar.setMaximumWidth(max(int((120 if tight_mode else 180) * scale_factor), 92))

            for widget in getattr(self, "_secondary_status_widgets", []):
                widget.setVisible(not compact_mode)
            for widget in getattr(self, "_tertiary_status_widgets", []):
                widget.setVisible(not tight_mode)
        except RuntimeError:
            return

    def _resolve_session_availability(self, path: str | None = None):
        target_path = str(path if path is not None else self.current_session_path() or "").strip()
        persistence = getattr(self.window, "authoritative_persistence", None)
        if isinstance(persistence, AuthoritativePersistenceUseCases):
            return persistence.resolve_session_availability(target_path)

        class _FallbackAvailability:
            def __init__(self, current_path: str):
                self.path = current_path
                self.display_name = os.path.basename(current_path) or current_path
                self.has_workbook_file = bool(current_path and os.path.exists(current_path))
                self.has_local_snapshot = False
                self.source_kind = "workbook_only" if self.has_workbook_file else "missing"

            @property
            def display_label(self) -> str:
                return self.display_name or "nenhuma"

            @property
            def detail_message(self) -> str:
                if not self.path:
                    return "Banco local ainda não inicializado."
                return f"Banco local vinculado a {self.path}."

        return _FallbackAvailability(target_path)

    def current_session_availability(self):
        return self._resolve_session_availability(self.current_session_path())

    def current_file_label_text(self) -> str:
        return self._build_window_chrome_snapshot().file_label

    def current_file_tooltip_text(self) -> str:
        return self._build_window_chrome_snapshot().file_tooltip

    def current_session_path(self) -> str:
        session_runtime = getattr(self.window, "session_runtime", None)
        if session_runtime is not None:
            return str(
                getattr(session_runtime, "session_path", getattr(session_runtime, "path", "")) or ""
            ).strip()
        return ""

    def current_workbook_path(self) -> str:
        return self.current_session_path()

    def has_active_workbook(self) -> bool:
        return bool(self.current_session_path())

    def _set_global_search_text(self, text: str) -> None:
        normalized = str(text or "")
        if self.window.search.text() == normalized:
            return
        self._syncing_global_search = True
        try:
            self.window.search.setText(normalized)
        finally:
            self._syncing_global_search = False

    def _on_global_search_changed(self, text: str) -> None:
        if self._syncing_global_search:
            return
        if self.window.tabs.currentWidget() is getattr(self.window, "admin_users_tab", None):
            return
        if self.window.tabs.currentWidget() is getattr(self.window, "tcra_tab", None):
            tcra_search = getattr(getattr(self.window, "tcra_tab", None), "search_input", None)
            if tcra_search is not None and tcra_search.text() != text:
                tcra_search.setText(text)
            return
        self._compensacoes_search_text = str(text or "")

    def _on_tcra_search_changed(self, text: str) -> None:
        if self._syncing_global_search:
            return
        if self.window.tabs.currentWidget() is getattr(self.window, "tcra_tab", None):
            self._set_global_search_text(text)

    def resolved_filter_facets(self, *, refresh: bool = False) -> LocalFilterFacetsResult:
        cached_facets = getattr(self.window, "_local_filter_facets_result", None)
        if cached_facets is not None and not refresh:
            return cached_facets

        self._bind_runtime_persistence_service()
        if isinstance(self.persistence, AuthoritativePersistenceUseCases):
            facets = self.persistence.resolve_filter_facets(
                self.current_session_path(),
                fallback_records=self.window.records,
            )
            self.window._local_filter_facets_status = self.persistence.build_filter_facets_status(facets)
        else:
            facets = self.local_record_queries.resolve_filter_facets(
                self.current_session_path(),
                fallback_records=self.window.records,
            )
            self.window._local_filter_facets_status = self.local_record_queries.build_filter_facets_status(facets)
        self.window._local_filter_facets_result = facets
        return facets

    def resolved_filtered_metrics(self) -> dict[str, object]:
        cached_metrics = getattr(self.window, "_filtered_metrics", None)
        if cached_metrics is not None:
            return dict(cached_metrics)
        return compute_metrics(self.window.filtered_records)

    def resolved_dashboard_record_overview(
        self,
        *,
        refresh: bool = False,
        top_microbacias_limit: int = 3,
        sample_limit: int = 0,
    ) -> PersistenceRecordOverviewReport | None:
        cached_report = getattr(self.window, "_dashboard_record_overview", None)
        if cached_report is not None and not refresh:
            return cached_report

        self._bind_runtime_persistence_service()
        workbook_path = self.current_session_path()
        if not workbook_path:
            self.window._dashboard_record_overview = None
            return None

        if isinstance(self.persistence, AuthoritativePersistenceUseCases):
            report = self.persistence.resolve_dashboard_record_overview(
                workbook_path,
                cached_report=cached_report,
                refresh=refresh,
                top_microbacias_limit=int(top_microbacias_limit),
                sample_limit=int(sample_limit),
            )
        elif self.persistence_use_cases is not None:
            try:
                report = self.persistence_use_cases.build_record_overview_report(
                    workbook_path,
                    top_microbacias_limit=int(top_microbacias_limit),
                    sample_limit=int(sample_limit),
                )
            except Exception as exc:
                logger.warning("Falha ao montar resumo local do dashboard: %s", exc, exc_info=True)
                self.window._dashboard_record_overview = None
                return None
        else:
            self.window._dashboard_record_overview = None
            return None

        self.window._dashboard_record_overview = report
        return report

    def resolved_persistence_status_report(
        self,
        *,
        refresh: bool = False,
        expected_audit_events: int = 0,
    ) -> PersistenceStatusReport | None:
        cached_report = getattr(self.window, "_persistence_status_report", None)
        expected_records = self.resolved_total_records()
        if (
            cached_report is not None
            and not refresh
            and int(getattr(cached_report, "expected_records", 0) or 0) == int(expected_records)
            and int(getattr(cached_report, "expected_audit_events", 0) or 0) == int(expected_audit_events)
        ):
            return cached_report

        self._bind_runtime_persistence_service()
        workbook_path = self.current_session_path()
        if not workbook_path:
            self.window._persistence_status_report = None
            return None

        if isinstance(self.persistence, AuthoritativePersistenceUseCases):
            report = self.persistence.build_persistence_status_report(
                workbook_path,
                expected_records=expected_records,
                expected_audit_events=int(expected_audit_events),
            )
        elif self.persistence_use_cases is not None:
            try:
                report = self.persistence_use_cases.build_status_report(
                    workbook_path,
                    expected_records=expected_records,
                    expected_audit_events=int(expected_audit_events),
                )
            except Exception as exc:
                logger.warning("Falha ao montar status operacional do espelho local: %s", exc, exc_info=True)
                self.window._persistence_status_report = None
                return None
        else:
            self.window._persistence_status_report = None
            return None

        self.window._persistence_status_report = report
        return report

    def resolved_total_records(self) -> int:
        session_status = getattr(self.window, "_local_session_source_status", None)
        total = int(getattr(session_status, "filtered_records", 0) or 0) if session_status is not None else 0
        if total > 0:
            return total

        read_status = getattr(self.window, "_local_record_read_status", None)
        total = int(getattr(read_status, "session_records", 0) or 0) if read_status is not None else 0
        if total > 0:
            return total

        return len(self.window.records)

    def resolved_filtered_records(self) -> int:
        read_status = getattr(self.window, "_local_record_read_status", None)
        filtered = int(getattr(read_status, "filtered_records", 0) or 0) if read_status is not None else 0
        if filtered > 0:
            return filtered
        if self.window.filtered_records:
            return len(self.window.filtered_records)

        total = self.resolved_total_records()
        if total > 0 and not self.has_active_record_filters():
            return total
        return 0

    def current_records_label_text(self) -> str:
        return self._build_window_chrome_snapshot().records_label

    def current_results_label_text(self) -> str:
        return f"{self.resolved_filtered_records()} registros"

    def current_filter_status_message_text(self) -> str:
        return f"Filtro aplicado: {self.resolved_filtered_records()} registros"

    def oficio_resize_candidates(self) -> list[str]:
        return [str(getattr(record, "oficio_processo", "") or "") for record in self.window.records]

    def tipo_resize_candidates(self) -> list[str]:
        return ["Eletrônico", "Ofício", "Físico", "Nulo"] + [
            display_tipo_value(getattr(record, "eletronico", ""))
            for record in self.window.records
        ]

    def visible_records(self) -> list:
        return list(self.window.filtered_records)

    def has_active_record_filters(self) -> bool:
        if self.window.search.text().strip():
            return True
        if self.window.data_tab.filter_status.currentText().strip() not in {"", "Todos"}:
            return True
        if self.window.data_tab.filter_year.currentText().strip() not in {"", "Todos"}:
            return True
        if not self.window.data_tab.filter_micro.is_all_selected():
            return True
        if not self.window.data_tab.filter_eletronico.is_all_selected():
            return True
        if not self.window.data_tab.filter_caixa.is_all_selected():
            return True
        return False

    def current_selection_label_text(self) -> str:
        return self._build_window_chrome_snapshot().selection_label

    def current_write_label_text(self) -> str:
        return self._build_window_chrome_snapshot().write_label

    def current_write_tooltip_text(self) -> str:
        return self._build_window_chrome_snapshot().write_tooltip

    def current_sync_label_text(self) -> str:
        return self._build_window_chrome_snapshot().sync_label

    def current_sync_tooltip_text(self) -> str:
        return self._build_window_chrome_snapshot().sync_tooltip

    def _build_window_chrome_snapshot(self):
        return build_window_chrome_snapshot(
            APP_WINDOW_TITLE,
            session_path=self.current_session_path(),
            availability=self.current_session_availability(),
            access_session=getattr(self.window, "access_session", None),
            remote_sync_status=getattr(self.window, "_remote_snapshot_refresh_status", None),
            persistence_report=getattr(self.window, "_persistence_status_report", None),
            record_integrity_report=getattr(self.window, "_record_integrity_report", None),
            total_records=self.resolved_total_records(),
            filtered_records=self.resolved_filtered_records(),
            search_text=self.window.search.text(),
            selected=self.window.selected,
            write_status=getattr(self.window, "_authoritative_write_status", None),
        )

    def refresh_window_chrome(self):
        snapshot = self._build_window_chrome_snapshot()
        window_title = snapshot.window_title
        access_session = getattr(self.window, "access_session", None)
        self.window.setWindowTitle(window_title)
        if hasattr(self.window, "session_environment_label"):
            self.window.session_environment_label.setText(
                getattr(access_session, "environment_chip_text", "Ambiente: Contingência local")
            )
            self.window.session_environment_label.setToolTip(
                getattr(
                    access_session,
                    "environment_tooltip_text",
                    "Inicialização local sem gateway de autenticação.",
                )
            )
        if hasattr(self.window, "session_user_label"):
            self.window.session_user_label.setText(build_user_identity_label_text(access_session))
            self.window.session_user_label.setToolTip(build_user_identity_tooltip_text(access_session))
        self._update_top_shell_context()
        self.window.session_file_label.setText(snapshot.file_label)
        self.window.session_file_label.setToolTip(snapshot.file_tooltip)
        self.window.session_records_label.setText(snapshot.records_label)
        self.window.session_records_label.setToolTip(snapshot.records_tooltip)
        self.window.session_sync_label.setText(snapshot.sync_label)
        self.window.session_sync_label.setToolTip(snapshot.sync_tooltip)
        self.window.session_write_label.setText(snapshot.write_label)
        self.window.session_write_label.setToolTip(snapshot.write_tooltip)
        self.window.session_selection_label.setText(snapshot.selection_label)
        self.window.session_selection_label.setToolTip(snapshot.selection_tooltip)

    def sign_out(self):
        return self.window.request_sign_out()

    def _apply_updated_access_session(self, access_session) -> None:
        self.window.access_session = access_session
        self._bind_runtime_persistence_service()
        if hasattr(self.window, "_remote_snapshot_refresh_status"):
            self.window._remote_snapshot_refresh_status = None
        data_controller = getattr(self.window, "data_controller", None)
        if data_controller is not None and hasattr(data_controller, "_last_remote_operational_refresh_monotonic"):
            data_controller._last_remote_operational_refresh_monotonic = 0.0
        self.refresh_window_chrome()

    def change_password(self) -> bool:
        if not self.can_change_password():
            QMessageBox.information(
                self.window,
                "Alterar senha",
                "A troca de senha só está disponível para contas autenticadas na produção oficial.",
            )
            return False

        access_session = getattr(self.window, "access_session", None)
        dialog = ChangePasswordDialog(
            title_text="Alterar senha",
            subtitle_text=(
                "Confirme sua senha atual e defina uma nova senha pessoal para manter o acesso protegido."
            ),
            account_email=str(getattr(access_session, "user_email", "") or "").strip(),
            require_current_password=True,
            parent=self.window,
        )
        if not dialog.exec():
            return False

        payload = dialog.payload()
        try:
            updated_session = self.window.access_service.change_password(
                access_session=access_session,
                current_password=payload["current_password"],
                new_password=payload["new_password"],
            )
        except AccessAuthError as exc:
            QMessageBox.warning(self.window, "Alterar senha", str(exc))
            return False

        self._apply_updated_access_session(updated_session)
        QMessageBox.information(
            self.window,
            "Alterar senha",
            "Senha atualizada com sucesso.",
        )
        return True

    def setup_menus(self):
        build_command = self.window.command_controller.build_handler
        menubar = self.window.menuBar()
        file_menu = menubar.addMenu("Arquivo")

        self.window.action_reload = QAction("Recarregar", self.window)
        self.window.action_reload.triggered.connect(build_command("reload"))
        file_menu.addAction(self.window.action_reload)

        self.window.action_rollback = QAction("M\u00e1quina do Tempo (Restaurar Backup)", self.window)
        self.window.action_rollback.triggered.connect(build_command("show_rollback_dialog"))
        file_menu.addAction(self.window.action_rollback)

        self.window.action_operation_history = QAction("Hist\u00f3rico de Opera\u00e7\u00f5es", self.window)
        self.window.action_operation_history.triggered.connect(build_command("show_operation_history"))
        file_menu.addAction(self.window.action_operation_history)

        file_menu.addSeparator()

        self.window.action_change_password = QAction("Alterar senha", self.window)
        self.window.action_change_password.triggered.connect(build_command("change_password"))
        self.window.action_change_password.setEnabled(False)
        self.window.action_change_password.setVisible(self.can_change_password())
        file_menu.addAction(self.window.action_change_password)

        file_menu.addSeparator()

        self.window.action_sign_out = QAction("Sair da conta", self.window)
        self.window.action_sign_out.triggered.connect(build_command("sign_out"))
        self.window.action_sign_out.setEnabled(False)
        file_menu.addAction(self.window.action_sign_out)

        file_menu.addSeparator()

        help_menu = menubar.addMenu("Ajuda")
        self.window.action_check_updates = QAction("Verificar Atualizacoes", self.window)
        self.window.action_check_updates.triggered.connect(build_command("check_for_updates"))
        help_menu.addAction(self.window.action_check_updates)
        help_menu.addSeparator()

        self.window.action_export_diagnostics = QAction("Exportar Diagn\u00f3stico", self.window)
        self.window.action_export_diagnostics.triggered.connect(build_command("export_diagnostics"))
        help_menu.addAction(self.window.action_export_diagnostics)

        self.window.action_open_logs = QAction("Abrir Pasta de Logs", self.window)
        self.window.action_open_logs.triggered.connect(build_command("open_logs_folder"))
        help_menu.addAction(self.window.action_open_logs)

        help_menu.addSeparator()

        self.window.action_about = QAction("Sobre", self.window)
        self.window.action_about.triggered.connect(build_command("show_about_dialog"))
        help_menu.addAction(self.window.action_about)

    def connect_signals(self):
        build_command = self.window.command_controller.build_handler

        self.window.btn_theme.clicked.connect(build_command("toggle_theme"))
        self.window.btn_change_password.clicked.connect(build_command("change_password"))
        self.window.btn_sign_out.clicked.connect(build_command("sign_out"))

        self.window.search.textChanged.connect(self.window.schedule_apply_filter)
        self.window.tabs.currentChanged.connect(self.window._on_tab_changed)

        self.window.data_tab.filter_micro.selectionChanged.connect(self.window.schedule_apply_filter)
        self.window.data_tab.filter_eletronico.selectionChanged.connect(self.window.schedule_apply_filter)
        self.window.data_tab.filter_caixa.selectionChanged.connect(self.window.schedule_apply_filter)
        self.window.data_tab.filter_status.currentTextChanged.connect(self.window.schedule_apply_filter)
        self.window.data_tab.filter_year.currentTextChanged.connect(self.window.schedule_apply_filter)
        self.window.data_tab.btn_clear_filters.clicked.connect(build_command("clear_filters"))
        self.window.data_tab.btn_reset_sort.clicked.connect(build_command("reset_sorting"))
        self.window.data_tab.btn_columns.clicked.connect(build_command("open_columns_dialog"))
        self.window.data_tab.btn_table_full.clicked.connect(build_command("open_table_fullscreen"))
        self.window.data_tab.table.clicked.connect(self.window._on_table_clicked)

        self.window.data_tab.btn_clear.clicked.connect(build_command("clear_form"))
        self.window.data_tab.btn_add.clicked.connect(build_command("add_new"))
        self.window.data_tab.btn_save_edit.clicked.connect(build_command("save_edit"))
        self.window.data_tab.btn_delete.clicked.connect(build_command("delete_selected"))
        self.window.data_tab.btn_ficha_pdf.clicked.connect(build_command("export_ficha_pdf"))
        self.window.data_tab.btn_manage_plantios.clicked.connect(build_command("edit_plantios"))

        self.window.data_tab.btn_maps.clicked.connect(build_command("search_on_map"))
        self.window.data_tab.btn_maps_plantio.clicked.connect(build_command("search_on_map_plantio"))
        self.window.data_tab.btn_batch_geo.clicked.connect(build_command("run_batch_geocode"))
        self.window.data_tab.btn_map_full.clicked.connect(build_command("open_map_fullscreen"))
        self.window.data_tab.btn_street_view.clicked.connect(build_command("open_street_view"))
        self.window.data_tab.btn_add_layer.clicked.connect(build_command("load_custom_layer"))
        self.window.data_tab.chk_heatmap.stateChanged.connect(build_command("toggle_heatmap"))
        self.window.data_tab.combo_heatmap_type.currentTextChanged.connect(build_command("toggle_heatmap"))

        self.window.data_tab.in_oficio.textChanged.connect(self.window._validate_as_you_type)
        self.window.data_tab.in_oficio.textChanged.connect(self.window._on_form_field_changed)
        self.window.data_tab.in_caixa.textChanged.connect(self.window._on_form_field_changed)
        self.window.data_tab.in_avtec.textChanged.connect(self.window._validate_as_you_type)
        self.window.data_tab.in_avtec.textChanged.connect(self.window._on_form_field_changed)
        self.window.data_tab.in_comp.textChanged.connect(self.window._on_form_field_changed)
        self.window.data_tab.in_end.textChanged.connect(self.window._on_form_field_changed)
        self.window.data_tab.in_end_plantio.textChanged.connect(self.window._on_form_field_changed)
        self.window.data_tab.in_micro.currentTextChanged.connect(self.window._on_form_field_changed)

        self.window.data_tab.chk_compensado.toggled.connect(self.window.form_controller.on_compensado_toggled)
        self.window.data_tab.chk_sn.toggled.connect(self.window._on_chk_sn_toggled)
        self.window.data_tab.chk_arquivado.toggled.connect(self.window._on_chk_arquivado_toggled)
        self.window.data_tab.chk_arquivado.toggled.connect(self.window._on_form_field_changed)

        self.window.data_tab.btn_export_csv.clicked.connect(build_command("export_csv_clicked"))
        self.window.data_tab.btn_export_spreadsheet.clicked.connect(build_command("export_spreadsheet_clicked"))
        self.window.data_tab.btn_export_pdf.clicked.connect(build_command("export_pdf_clicked"))
        self.window.dash_tab.btn_export_diagnostics.clicked.connect(build_command("export_diagnostics"))
        self.window.dash_tab.btn_export_pdf.clicked.connect(build_command("export_dashboard_pdf_clicked"))

        self.window.operations_tab.btn_refresh.clicked.connect(build_command("refresh_operations_overview"))
        self.window.operations_tab.btn_export_diagnostics.clicked.connect(build_command("export_diagnostics"))
        self.window.operations_tab.btn_sync_production.clicked.connect(build_command("refresh_production_snapshot"))
        self.window.operations_tab.btn_history.clicked.connect(build_command("show_operation_history"))
        self.window.operations_tab.btn_rollback.clicked.connect(build_command("show_rollback_dialog"))
        self.window.operations_tab.btn_open_backup.clicked.connect(build_command("open_selected_operation_backup"))

    def sync_global_search_context(self):
        is_admin_tab_active = getattr(self.window, "tabs", None) is not None and (
            self.window.tabs.currentWidget() is getattr(self.window, "admin_users_tab", None)
        )
        is_tcra_tab_active = getattr(self.window, "tabs", None) is not None and (
            self.window.tabs.currentWidget() is getattr(self.window, "tcra_tab", None)
        )
        tcra_tab = getattr(self.window, "tcra_tab", None)
        self.window.search.setEnabled(True)
        if is_admin_tab_active:
            if self._search_context != "admin":
                self._compensacoes_search_text = self.window.search.text()
            self._search_context = "admin"
            if tcra_tab is not None and hasattr(tcra_tab, "set_global_search_mode"):
                tcra_tab.set_global_search_mode(False)
            self.window.search.clear()
            self.window.search.setPlaceholderText("Busca indisponível na administração")
            self.window.search.setEnabled(False)
            self._update_top_shell_context()
            return
        if is_tcra_tab_active:
            if self._search_context != "tcra":
                self._compensacoes_search_text = self.window.search.text()
            self._search_context = "tcra"
            self.window.search.setPlaceholderText(self.TCRA_SEARCH_PLACEHOLDER)
            if tcra_tab is not None and hasattr(tcra_tab, "set_global_search_mode"):
                tcra_tab.set_global_search_mode(True)
                self._set_global_search_text(tcra_tab.search_input.text())
            self._update_top_shell_context()
            return

        self._search_context = "compensacoes"
        self.window.search.setPlaceholderText(self.COMPENSACOES_SEARCH_PLACEHOLDER)
        if tcra_tab is not None and hasattr(tcra_tab, "set_global_search_mode"):
            tcra_tab.set_global_search_mode(False)
        self._set_global_search_text(self._compensacoes_search_text)
        self._update_top_shell_context()

    def setup_shortcuts(self):
        build_command = self.window.command_controller.build_handler

        act_save = QAction(self.window)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(build_command("save_edit"))
        self.window.addAction(act_save)

        act_undo = QAction(self.window)
        act_undo.setShortcut(QKeySequence.Undo)
        act_undo.triggered.connect(build_command("undo"))
        self.window.addAction(act_undo)

        act_redo = QAction(self.window)
        act_redo.setShortcut(QKeySequence.Redo)
        act_redo.triggered.connect(build_command("redo"))
        self.window.addAction(act_redo)

        act_new = QAction(self.window)
        act_new.setShortcut("Ctrl+N")
        act_new.triggered.connect(build_command("clear_form"))
        self.window.addAction(act_new)

        act_delete = QAction(self.window.data_tab.table)
        act_delete.setShortcut(QKeySequence(Qt.Key_Delete))
        act_delete.setShortcutContext(Qt.WidgetShortcut)
        act_delete.triggered.connect(build_command("delete_selected_from_table_shortcut"))
        self.window.data_tab.table.addAction(act_delete)

    def on_form_field_changed(self):
        self.refresh_tipo_controls()
        self.window.form_controller.remember_current_state()
        self.window.form_controller.validate_as_you_type()
        self.window._update_form_action_buttons()
        self.window._update_address_search_enabled()

    def validate_as_you_type(self):
        self.window.form_controller.validate_as_you_type()

    def is_form_dirty(self) -> bool:
        return self.window.form_controller.has_pending_changes()

    def update_address_search_enabled(self):
        self.window.map_controller.update_address_search_enabled()

    def on_chk_sn_toggled(self, checked):
        self.window.data_tab.in_oficio.blockSignals(True)
        try:
            if checked:
                self.window.data_tab.in_oficio.setText("S/N")
                self.window.data_tab.in_oficio.setEnabled(False)
            else:
                if self.window.data_tab.in_oficio.text().upper() == "S/N":
                    self.window.data_tab.in_oficio.clear()
                self.window.data_tab.in_oficio.setEnabled(True)
                self.window.data_tab.in_oficio.setFocus()
        finally:
            self.window.data_tab.in_oficio.blockSignals(False)
        self.window.form_controller.remember_current_state()
        self.window.form_controller.validate_as_you_type()
        self.window._update_form_action_buttons()

    def on_chk_arquivado_toggled(self, checked):
        self.window.data_tab.in_caixa.blockSignals(True)
        try:
            if checked:
                self.window.data_tab.in_caixa.setText("Arquivado")
            else:
                if self.window.data_tab.in_caixa.text().upper() == "ARQUIVADO":
                    self.window.data_tab.in_caixa.clear()
            self.refresh_tipo_controls(
                focus_if_enabled=not checked,
                clear_archived_text=not checked,
            )
        finally:
            self.window.data_tab.in_caixa.blockSignals(False)
        self.window.form_controller.remember_current_state()
        self.window.form_controller.validate_as_you_type()
        self.window._update_form_action_buttons()

    def finalize_startup_layout(self):
        try:
            self.window._startup_layout_pending = False
            data_tab = self.window.data_tab
            data_tab.align_splitter_to_table_width()
            data_tab._sync_left_panel_heights()
            data_tab._update_form_group_height()
            data_tab._update_responsive_constraints()
            if hasattr(data_tab, "_finalize_responsive_layout"):
                data_tab._finalize_responsive_layout()
            fit_window_to_available_geometry(self.window)
        except RuntimeError:
            return

    def apply_theme(self):
        theme = THEME_DARK if self.window.is_dark_mode else THEME_LIGHT
        qss = get_app_qss(theme, self.window.scale_factor)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)
        self.window.setStyleSheet(qss)
        self.window.data_tab.table_model.set_dark_mode(self.window.is_dark_mode)
        self.window.dash_tab.apply_theme(theme)
        self.window.operations_tab.apply_theme(theme)
        self.window.tcra_tab.apply_theme(theme)
        self.apply_theme_to_map()

    def apply_theme_to_map(self):
        mode = "dark" if self.window.is_dark_mode else "light"
        self.window._run_map_js(f"if(window.setTheme) window.setTheme('{mode}');", "theme")

    def resolve_microbacia_display_name(self, value: object) -> str:
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""
        gis = getattr(self.window, "gis", None)
        if gis is not None and hasattr(gis, "normalize_microbacia_name"):
            normalized = str(gis.normalize_microbacia_name(raw_value) or "").strip()
            if normalized:
                return normalized
        return raw_value

    def select_form_microbacia(self, value: object) -> None:
        combo = self.window.data_tab.in_micro
        target_value = self.resolve_microbacia_display_name(value)
        target_key = normalize_microbacia_key(target_value)
        if target_key:
            for index in range(combo.count()):
                if normalize_microbacia_key(combo.itemText(index)) == target_key:
                    combo.setCurrentIndex(index)
                    return
        combo.setCurrentText(target_value)

    def _resolved_microbacia_options(self, facet_microbacias: Sequence[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()

        def append_option(option: object) -> None:
            display_name = self.resolve_microbacia_display_name(option)
            key = normalize_microbacia_key(display_name)
            if not key or key in seen:
                return
            seen.add(key)
            merged.append(display_name)

        gis = getattr(self.window, "gis", None)
        if gis is not None and hasattr(gis, "list_microbacias"):
            for microbacia in gis.list_microbacias():
                append_option(microbacia)

        for microbacia in facet_microbacias:
            append_option(microbacia)

        return merged

    def update_filters_from_records(self):
        facets = self.resolved_filter_facets(refresh=True)
        current_micros = self.window.data_tab.filter_micro.checked_items()
        current_micro_all = self.window.data_tab.filter_micro.is_all_selected()
        current_caixas = self.window.data_tab.filter_caixa.checked_items()
        current_caixa_all = self.window.data_tab.filter_caixa.is_all_selected()
        micro_options = self._resolved_microbacia_options(facets.microbacias)
        caixa_options = unique_non_empty(record.caixa for record in self.window.records)
        self.window.data_tab.filter_micro.set_items(micro_options)
        self.window.data_tab.filter_micro.set_checked_items(
            current_micros,
            all_selected=current_micro_all,
            emit_selection_changed=False,
        )
        self.window.data_tab.filter_eletronico.set_items(list(STANDARD_TIPO_OPTIONS))
        self.window.data_tab.filter_caixa.set_items(caixa_options)
        self.window.data_tab.filter_caixa.set_checked_items(
            current_caixas,
            all_selected=current_caixa_all,
            emit_selection_changed=False,
        )
        self.window.data_tab.filter_year.blockSignals(True)
        self.window.data_tab.filter_year.clear()
        self.window.data_tab.filter_year.addItems(["Todos"] + list(facets.years))
        self.window.data_tab.filter_year.blockSignals(False)

    def setup_dynamic_form_options_from_records(self):
        facets = self.resolved_filter_facets()
        current_micro = self.window.data_tab.in_micro.currentText()
        self.window.data_tab.in_micro.blockSignals(True)
        self.window.data_tab.in_micro.clear()
        self.window.data_tab.in_micro.addItem("")
        for micro in self._resolved_microbacia_options(facets.microbacias):
            self.window.data_tab.in_micro.addItem(micro)
        if current_micro:
            self.select_form_microbacia(current_micro)
        self.window.data_tab.in_micro.blockSignals(False)

        checked_button = self.window.data_tab.eletronico_group.checkedButton()
        current_eletronico = display_tipo_value(checked_button.text() if checked_button else "")

        while self.window.data_tab.eletronico_layout.count():
            item = self.window.data_tab.eletronico_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                self.window.data_tab.eletronico_group.removeButton(widget)
                widget.deleteLater()

        selected_button = None
        for option in STANDARD_TIPO_OPTIONS:
            button = QRadioButton(option)
            button.setMinimumHeight(24)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            button.clicked.connect(self.window._on_form_field_changed)
            self.window.data_tab.eletronico_group.addButton(button)
            self.window.data_tab.eletronico_layout.addWidget(button)
            if option == current_eletronico:
                button.setChecked(True)
                selected_button = button

        if selected_button is None:
            for button in self.window.data_tab.eletronico_group.buttons():
                if button.text() == TIPO_NULO:
                    button.setChecked(True)
                    break

        self.window.data_tab.eletronico_layout.addStretch(1)
        self.refresh_tipo_controls()

    def refresh_tipo_controls(
        self,
        *,
        focus_if_enabled: bool = False,
        clear_archived_text: bool = False,
    ):
        checked_button = self.window.data_tab.eletronico_group.checkedButton()
        selected_tipo = display_tipo_value(checked_button.text() if checked_button else "")
        is_arquivado = self.window.data_tab.chk_arquivado.isChecked()
        caixa = self.window.data_tab.in_caixa
        previous_tipo = str(getattr(self, "_last_selected_tipo", "") or "")
        tipo_changed = selected_tipo != previous_tipo
        normalized_caixa = remove_accents(caixa.text()).strip().upper()
        caixa.setValidator(None if is_arquivado else QIntValidator(0, 999999))
        caixa.blockSignals(True)
        try:
            if is_arquivado:
                if caixa.text() != "Arquivado":
                    caixa.setText("Arquivado")
            else:
                if clear_archived_text and normalized_caixa == "ARQUIVADO":
                    caixa.clear()
                    normalized_caixa = ""

                if selected_tipo == TIPO_OFICIO:
                    if tipo_changed or not normalized_caixa:
                        if caixa.text() != "Ofícios":
                            caixa.setText("Ofícios")
                elif tipo_changed and normalized_caixa == "OFICIOS":
                    caixa.clear()
        finally:
            caixa.blockSignals(False)

        is_editable = not is_arquivado and not tipo_is_eletronico(selected_tipo)
        caixa.setEnabled(is_editable)
        if is_editable and focus_if_enabled:
            caixa.setFocus()
        self._last_selected_tipo = selected_tipo

    def open_columns_dialog(self):
        visible_map = {
            index: not self.window.data_tab.table.isColumnHidden(index)
            for index in range(self.window.data_tab.table_model.columnCount())
        }
        dialog = ColumnsDialog(self.window, list(DISPLAY_COLUMN_LABELS), visible_map)
        if not dialog.exec():
            return

        new_map = dialog.visible_map()
        if not any(new_map.values()):
            QMessageBox.warning(self.window, "Aviso", "Selecione pelo menos uma coluna para exibir.")
            return

        for index, is_visible in new_map.items():
            self.window.data_tab.table.setColumnHidden(index, not is_visible)

    def on_table_clicked(self, index):
        if self.window.selected is not None and self.window.form_controller.has_pending_changes():
            if not self.window.form_controller.confirm_discard_changes("trocar de registro"):
                return

        source_index = self.window.data_tab.proxy.mapToSource(index)
        if not source_index.isValid() or source_index.row() >= len(self.window.filtered_records):
            return

        self.window.selected = self._resolve_filtered_record_selection(source_index.row())
        self.window._fill_form(self.window.selected)
        self.window._update_form_action_buttons()
        self.window._update_address_search_enabled()

        lat = getattr(self.window.selected, "latitude", "")
        lon = getattr(self.window.selected, "longitude", "")
        if str(lat).strip() and str(lon).strip():
            self.window._set_map_marker(float(lat), float(lon))
            if self.window.selected.microbacia:
                self.window._highlight_microbacia(self.window.selected.microbacia)

    def delete_selected_from_table_shortcut(self):
        current_index = self.window.data_tab.table.currentIndex()
        if current_index.isValid():
            source_index = self.window.data_tab.proxy.mapToSource(current_index)
            if 0 <= source_index.row() < len(self.window.filtered_records):
                self.window.selected = self._resolve_filtered_record_selection(source_index.row())
        self.window.delete_selected()

    def _resolve_filtered_record_selection(self, row_index: int):
        fallback_record = self.window.filtered_records[row_index]
        self._bind_runtime_persistence_service()
        if isinstance(self.persistence, AuthoritativePersistenceUseCases):
            selected_result = self.persistence.resolve_selected_record(
                self.current_session_path(),
                fallback_records=self.window.records,
                uid=str(getattr(fallback_record, "uid", "") or ""),
                excel_row=int(getattr(fallback_record, "excel_row", 0) or 0),
            )
        else:
            selected_result = self.local_record_queries.resolve_selected_record(
                self.current_session_path(),
                fallback_records=self.window.records,
                uid=str(getattr(fallback_record, "uid", "") or ""),
                excel_row=int(getattr(fallback_record, "excel_row", 0) or 0),
            )
        return selected_result.record or fallback_record

    def get_visible_column_attrs(self) -> List[str]:
        attrs = []
        for index, attr in enumerate(DISPLAY_COLUMN_ATTRS):
            if not self.window.data_tab.table.isColumnHidden(index):
                attrs.append(attr)
        return attrs

