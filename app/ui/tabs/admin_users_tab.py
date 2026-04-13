from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QHeaderView,
)

from app.config import (
    DEFAULT_CORPORATE_EMAIL_SUFFIX,
    display_corporate_email_local_part,
)
from app.services.access_service import AccessEnvironment, AppAccessSession
from app.services.supabase_admin_users_service import (
    AdminUserRecord,
    AdminUsersError,
    SupabaseAdminUsersService,
)
from app.ui.components.widgets import ClickableComboBox
from app.ui.components.ui_utils import msg_confirm


def _format_role(role: str) -> str:
    normalized = str(role or "").strip().lower()
    if normalized == "admin":
        return "Administrador"
    if normalized == "viewer":
        return "Leitor"
    return "Editor"


def _role_capabilities_text(role: str) -> str:
    normalized = str(role or "").strip().lower()
    if normalized == "admin":
        return "Pode gerenciar usuários, redefinir senhas, controlar acessos e operar os módulos do sistema."
    if normalized == "viewer":
        return "Pode consultar as telas e relatórios, sem alterar dados operacionais."
    return "Pode operar os módulos, cadastrar e atualizar dados, sem administrar usuários."


def _is_admin_role(role: str) -> bool:
    return str(role or "").strip().lower() == "admin"


def _configure_text_input(
    input_field: QLineEdit,
    *,
    placeholder: str = "",
    tooltip: str = "",
    password: bool = False,
) -> None:
    if placeholder:
        input_field.setPlaceholderText(placeholder)
    if tooltip:
        input_field.setToolTip(tooltip)
    input_field.setClearButtonEnabled(True)
    if password:
        input_field.setEchoMode(QLineEdit.Password)


def _build_password_row(
    input_field: QLineEdit,
    *,
    parent: QWidget | None = None,
    show_label: str = "Mostrar",
    hide_label: str = "Ocultar",
) -> tuple[QWidget, QPushButton]:
    container = QWidget(parent)
    container_layout = QHBoxLayout(container)
    container_layout.setContentsMargins(0, 0, 0, 0)
    container_layout.setSpacing(8)

    toggle_button = QPushButton(show_label, container)
    toggle_button.setCheckable(True)
    toggle_button.setAutoDefault(False)
    toggle_button.setDefault(False)
    toggle_button.setProperty("kind", "ghost")
    toggle_button.setMinimumWidth(88)
    toggle_button.setToolTip("Alterna a visibilidade da senha digitada.")

    def _sync_visibility(checked: bool) -> None:
        input_field.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        toggle_button.setText(hide_label if checked else show_label)

    toggle_button.toggled.connect(_sync_visibility)
    _sync_visibility(False)

    container_layout.addWidget(input_field, 1)
    container_layout.addWidget(toggle_button, 0)
    return container, toggle_button


class ResetUserPasswordDialog(QDialog):
    def __init__(self, email: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._email = email
        self.setWindowTitle("Redefinir senha")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(
            f"Defina uma senha provisória para {self._email}."
        )
        title.setWordWrap(True)
        title.setObjectName("FormStateLabel")
        layout.addWidget(title)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.password_input = QLineEdit(self)
        _configure_text_input(
            self.password_input,
            placeholder="Senha provisória com 8+ caracteres",
            tooltip="Informe uma senha provisória segura para o usuário selecionado.",
            password=True,
        )
        self.confirm_password_input = QLineEdit(self)
        _configure_text_input(
            self.confirm_password_input,
            placeholder="Repita a senha",
            tooltip="Repita a senha provisória para confirmar a alteração.",
            password=True,
        )
        password_row, self.password_toggle_button = _build_password_row(self.password_input, parent=self)
        confirm_password_row, self.confirm_password_toggle_button = _build_password_row(
            self.confirm_password_input,
            parent=self,
        )
        self.confirm_password_input.returnPressed.connect(self._submit)

        form.addRow("Senha:", password_row)
        form.addRow("Confirmar:", confirm_password_row)
        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("FormStateLabel")
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = QPushButton("Cancelar")
        cancel_button.setProperty("kind", "ghost")
        cancel_button.clicked.connect(self.reject)
        submit_button = QPushButton("Aplicar senha")
        submit_button.setProperty("kind", "primary")
        submit_button.clicked.connect(self._submit)
        actions.addWidget(cancel_button)
        actions.addWidget(submit_button)
        layout.addLayout(actions)

    def password(self) -> str:
        return self.password_input.text()

    def _submit(self) -> None:
        password = self.password_input.text()
        confirm_password = self.confirm_password_input.text()
        if len(password) < 8:
            self.status_label.setText("A senha precisa ter pelo menos 8 caracteres.")
            self.password_input.setFocus()
            return
        if password != confirm_password:
            self.status_label.setText("A confirmação da senha não confere.")
            self.confirm_password_input.setFocus()
            return
        self.accept()


class AdminUsersTab(QWidget):
    def __init__(
        self,
        parent=None,
        *,
        admin_service: SupabaseAdminUsersService | None = None,
    ) -> None:
        super().__init__(parent)
        self.main_window = parent
        self.sf = getattr(parent, "scale_factor", 1.0)
        access_service = getattr(parent, "access_service", None)
        production_profile = getattr(access_service, "production_profile", None)
        self.admin_service = admin_service or SupabaseAdminUsersService(
            production_profile=production_profile,
        )
        self.users: list[AdminUserRecord] = []
        self._busy = False
        self._last_role_sync_user_id = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        layout.setSpacing(int(8 * self.sf))

        header_frame = QFrame(self)
        header_frame.setProperty("panel", "section")
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(int(10 * self.sf), int(9 * self.sf), int(10 * self.sf), int(9 * self.sf))
        header_layout.setSpacing(int(5 * self.sf))

        title_row = QHBoxLayout()
        title_row.setSpacing(int(10 * self.sf))
        title_text_layout = QVBoxLayout()
        title_text_layout.setSpacing(int(2 * self.sf))
        kicker = QLabel("GESTÃO DE ACESSO")
        kicker.setProperty("role", "eyebrow")
        title = QLabel("Administração de usuários")
        title.setProperty("role", "page-title")
        self.header_subtitle = QLabel(
            "Ambiente restrito a administradores ativos para cadastro, liberação e manutenção de acessos."
        )
        self.header_subtitle.setWordWrap(True)
        self.header_subtitle.setProperty("role", "page-subtitle")
        header_badges = QHBoxLayout()
        header_badges.setContentsMargins(0, 0, 0, 0)
        header_badges.setSpacing(int(6 * self.sf))
        for badge_text in ("Produção oficial", "Acesso corporativo", "Perfis e permissões"):
            badge = QLabel(badge_text)
            badge.setProperty("role", "context-chip")
            header_badges.addWidget(badge, 0)
        header_badges.addStretch(1)
        title_text_layout.addWidget(kicker)
        title_text_layout.addWidget(title)
        title_text_layout.addWidget(self.header_subtitle)
        title_text_layout.addLayout(header_badges)
        title_row.addLayout(title_text_layout, 1)
        self.btn_refresh = QPushButton("Atualizar")
        self.btn_refresh.setProperty("kind", "ghost")
        self.btn_refresh.setToolTip("Recarrega a lista de usuários e o estado de cada perfil.")
        self.btn_refresh.setMinimumHeight(int(28 * self.sf))
        title_row.addWidget(self.btn_refresh, 0, Qt.AlignTop)
        header_layout.addLayout(title_row)

        self.status_label = QLabel("Abra esta aba ou use Atualizar para carregar os usuários.")
        self.status_label.setObjectName("FormStateLabel")
        header_layout.addWidget(self.status_label)

        self.operator_context_label = QLabel(
            "Gestor atual: conta administrativa autenticada no ambiente oficial."
        )
        self.operator_context_label.setProperty("role", "helper")
        self.operator_context_label.setWordWrap(True)
        header_layout.addWidget(self.operator_context_label)

        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(int(6 * self.sf))
        self.summary_total_label = QLabel("Usuários: 0")
        self.summary_total_label.setObjectName("StatusChip")
        self.summary_active_label = QLabel("Ativos: 0")
        self.summary_active_label.setObjectName("StatusChip")
        self.summary_admin_label = QLabel("Admins: 0")
        self.summary_admin_label.setObjectName("StatusChip")
        self.summary_visible_label = QLabel("Visíveis: 0")
        self.summary_visible_label.setObjectName("StatusChip")
        summary_row.addWidget(self.summary_total_label)
        summary_row.addWidget(self.summary_active_label)
        summary_row.addWidget(self.summary_admin_label)
        summary_row.addWidget(self.summary_visible_label)
        summary_row.addStretch(1)
        header_layout.addLayout(summary_row)
        layout.addWidget(header_frame)

        filters_frame = QFrame(self)
        filters_frame.setProperty("panel", "toolbar")
        filters_container = QVBoxLayout(filters_frame)
        filters_container.setContentsMargins(int(10 * self.sf), int(8 * self.sf), int(10 * self.sf), int(8 * self.sf))
        filters_container.setSpacing(int(5 * self.sf))
        self.filters_hint = QLabel("Localize contas por nome, email, perfil ou situação antes de aplicar ações administrativas.")
        self.filters_hint.setProperty("role", "helper")
        self.filters_hint.setWordWrap(True)
        filters_layout = QHBoxLayout()
        filters_layout.setContentsMargins(0, 0, 0, 0)
        filters_layout.setSpacing(int(5 * self.sf))
        self.table_search_input = QLineEdit(self)
        _configure_text_input(
            self.table_search_input,
            placeholder="Buscar por email, nome ou perfil",
            tooltip="Filtra os usuários já carregados nesta tela.",
        )
        self.status_filter_combo = ClickableComboBox(self)
        self.status_filter_combo.addItem("Todos os status", "all")
        self.status_filter_combo.addItem("Somente ativos", "active")
        self.status_filter_combo.addItem("Somente inativos", "inactive")
        self.role_filter_combo = ClickableComboBox(self)
        self.role_filter_combo.addItem("Todos os perfis", "all")
        self.role_filter_combo.addItem("Administradores", "admin")
        self.role_filter_combo.addItem("Editores", "editor")
        self.role_filter_combo.addItem("Leitores", "viewer")
        filters_layout.addWidget(QLabel("Busca:"))
        filters_layout.addWidget(self.table_search_input, 1)
        filters_layout.addWidget(QLabel("Status:"))
        filters_layout.addWidget(self.status_filter_combo)
        filters_layout.addWidget(QLabel("Perfil:"))
        filters_layout.addWidget(self.role_filter_combo)
        filters_container.addWidget(self.filters_hint)
        filters_container.addLayout(filters_layout)
        layout.addWidget(filters_frame)

        content_layout = QHBoxLayout()
        self.content_layout = content_layout
        content_layout.setSpacing(int(8 * self.sf))

        table_panel = QFrame(self)
        table_panel.setProperty("panel", "section")
        table_panel_layout = QVBoxLayout(table_panel)
        table_panel_layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        table_panel_layout.setSpacing(int(5 * self.sf))
        table_title = QLabel("Usuários cadastrados")
        table_title.setProperty("role", "section-title")
        table_panel_layout.addWidget(table_title)
        self.table_hint = QLabel("Use busca e filtros para localizar rapidamente a conta que você precisa revisar.")
        self.table_hint.setProperty("role", "helper")
        self.table_hint.setWordWrap(True)
        table_panel_layout.addWidget(self.table_hint)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(["Email", "Nome", "Perfil", "Situação", "Criado"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(int(28 * self.sf))
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table_panel_layout.addWidget(self.table, 1)

        sidebar = QWidget(self)
        self.sidebar = sidebar
        sidebar.setMinimumWidth(int(320 * self.sf))
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(int(6 * self.sf))

        manage_group = QGroupBox("Conta selecionada")
        manage_layout = QVBoxLayout(manage_group)
        manage_layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        manage_layout.setSpacing(int(6 * self.sf))
        self.manage_hint = QLabel("Selecione uma conta para revisar o perfil, o status e as ações disponíveis.")
        self.manage_hint.setProperty("role", "helper")
        self.manage_hint.setWordWrap(True)
        manage_layout.addWidget(self.manage_hint)
        selected_caption = QLabel("Contexto da conta")
        selected_caption.setProperty("role", "panel-caption")
        manage_layout.addWidget(selected_caption)
        self.selection_summary_label = QLabel("Nenhuma conta selecionada")
        self.selection_summary_label.setObjectName("StatusChip")
        manage_layout.addWidget(self.selection_summary_label)
        self.selection_profile_label = QLabel("Perfil: --")
        self.selection_profile_label.setObjectName("FormStateLabel")
        self.selection_status_label = QLabel("Situação: --")
        self.selection_status_label.setObjectName("FormStateLabel")
        self.selection_created_label = QLabel("Criado: --")
        self.selection_created_label.setObjectName("FormStateLabel")
        self.selection_permissions_label = QLabel("Permissões: --")
        self.selection_permissions_label.setProperty("role", "helper")
        self.selection_permissions_label.setWordWrap(True)
        manage_layout.addWidget(self.selection_profile_label)
        manage_layout.addWidget(self.selection_status_label)
        manage_layout.addWidget(self.selection_created_label)
        manage_layout.addWidget(self.selection_permissions_label)

        profile_editor_caption = QLabel("Perfil operacional")
        profile_editor_caption.setProperty("role", "panel-caption")
        manage_layout.addWidget(profile_editor_caption)
        role_editor_row = QHBoxLayout()
        role_editor_row.setSpacing(int(6 * self.sf))
        self.manage_role_combo = QComboBox(self)
        self.manage_role_combo.addItem("Administrador", "admin")
        self.manage_role_combo.addItem("Editor", "editor")
        self.manage_role_combo.addItem("Leitor", "viewer")
        self.manage_role_combo.setToolTip("Define o perfil operacional da conta selecionada.")
        self.btn_apply_role = QPushButton("Aplicar perfil")
        self.btn_apply_role.setProperty("kind", "ghost")
        self.btn_apply_role.setMinimumHeight(int(28 * self.sf))
        self.btn_apply_role.setToolTip("Atualiza o perfil da conta selecionada no ambiente oficial.")
        role_editor_row.addWidget(self.manage_role_combo, 1)
        role_editor_row.addWidget(self.btn_apply_role, 0)
        manage_layout.addLayout(role_editor_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(int(6 * self.sf))
        self.btn_activate = QPushButton("Reativar acesso")
        self.btn_activate.setProperty("kind", "success")
        self.btn_activate.setToolTip("Reativa o acesso do usuário selecionado.")
        self.btn_deactivate = QPushButton("Desativar acesso")
        self.btn_deactivate.setProperty("kind", "chip-quiet")
        self.btn_deactivate.setToolTip("Bloqueia temporariamente o acesso do usuário selecionado.")
        self.btn_reset_password = QPushButton("Redefinir senha")
        self.btn_reset_password.setProperty("kind", "chip-quiet")
        self.btn_reset_password.setToolTip("Define uma senha provisória para o usuário selecionado.")
        self.btn_delete = QPushButton("Excluir conta")
        self.btn_delete.setProperty("kind", "danger")
        self.btn_delete.setToolTip("Remove definitivamente o usuário selecionado.")
        for button in [self.btn_activate, self.btn_deactivate, self.btn_reset_password, self.btn_delete]:
            button.setMinimumHeight(int(28 * self.sf))
        self.selection_hint = QLabel("Selecione uma conta para liberar, bloquear, redefinir senha ou excluir.")
        self.selection_hint.setObjectName("FormStateLabel")
        actions_caption = QLabel("Ações disponíveis")
        actions_caption.setProperty("role", "panel-caption")
        action_row.addWidget(self.btn_activate)
        action_row.addWidget(self.btn_deactivate)
        manage_layout.addWidget(actions_caption)
        manage_layout.addLayout(action_row)
        action_row_secondary = QHBoxLayout()
        action_row_secondary.setSpacing(int(6 * self.sf))
        action_row_secondary.addWidget(self.btn_reset_password)
        action_row_secondary.addWidget(self.btn_delete)
        action_row_secondary.addStretch(1)
        manage_layout.addLayout(action_row_secondary)
        manage_layout.addWidget(self.selection_hint)
        sidebar_layout.addWidget(manage_group)

        create_group = QGroupBox("Cadastrar nova conta")
        create_layout = QFormLayout(create_group)
        create_layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        create_layout.setHorizontalSpacing(int(12 * self.sf))
        create_layout.setVerticalSpacing(int(8 * self.sf))
        self.create_hint = QLabel("Preencha os dados essenciais para liberar o primeiro acesso da conta corporativa.")
        self.create_hint.setProperty("role", "helper")
        self.create_hint.setWordWrap(True)
        create_layout.addRow(self.create_hint)
        self.create_role_hint = QLabel(
            "Administradores podem cadastrar, redefinir senhas e controlar o status de acesso dos demais usuários."
        )
        self.create_role_hint.setProperty("role", "helper")
        self.create_role_hint.setWordWrap(True)
        create_layout.addRow(self.create_role_hint)
        self.create_permissions_label = QLabel(_role_capabilities_text("editor"))
        self.create_permissions_label.setProperty("role", "helper")
        self.create_permissions_label.setWordWrap(True)
        create_layout.addRow(self.create_permissions_label)
        self.create_domain_hint = QLabel(
            "O domínio corporativo é acrescentado automaticamente. Informe apenas a parte antes de @saocarlos.sp.gov.br.",
            create_group,
        )
        self.create_domain_hint.setProperty("role", "helper")
        self.create_domain_hint.setWordWrap(True)
        create_layout.addRow(self.create_domain_hint)

        self.email_input = QLineEdit(self)
        _configure_text_input(
            self.email_input,
            placeholder="nome.sobrenome",
            tooltip="Informe apenas o identificador do email corporativo; o domínio é preenchido ao lado.",
        )
        self.email_input.editingFinished.connect(self._normalize_email_field)
        self.display_name_input = QLineEdit(self)
        _configure_text_input(
            self.display_name_input,
            placeholder="Nome para exibição",
            tooltip="Nome exibido no app para o usuário cadastrado.",
        )
        self.password_input = QLineEdit(self)
        _configure_text_input(
            self.password_input,
            placeholder="Senha provisória",
            tooltip="Senha inicial entregue ao usuário para o primeiro acesso.",
            password=True,
        )
        self.password_row, self.password_toggle_button = _build_password_row(self.password_input, parent=create_group)
        self.role_combo = QComboBox(self)
        self.role_combo.addItem("Editor", "editor")
        self.role_combo.addItem("Leitor", "viewer")
        self.role_combo.addItem("Administrador", "admin")
        self.role_combo.setToolTip("Define o nível de permissão do usuário.")
        self.is_active_combo = QComboBox(self)
        self.is_active_combo.addItem("Ativo", True)
        self.is_active_combo.addItem("Inativo", False)
        self.is_active_combo.setToolTip("Escolhe se o usuário já entra liberado ou bloqueado.")
        self.btn_create = QPushButton("Cadastrar usuário")
        self.btn_create.setProperty("kind", "primary")
        self.btn_create.setToolTip("Cria um novo usuário de produção com o perfil informado.")
        self.btn_create.setMinimumHeight(int(30 * self.sf))

        email_row = QWidget(self)
        email_layout = QHBoxLayout(email_row)
        email_layout.setContentsMargins(0, 0, 0, 0)
        email_layout.setSpacing(int(8 * self.sf))
        email_suffix = QLabel(DEFAULT_CORPORATE_EMAIL_SUFFIX, email_row)
        email_suffix.setObjectName("FormStateLabel")
        email_layout.addWidget(self.email_input, 1)
        email_layout.addWidget(email_suffix, 0, Qt.AlignVCenter)

        create_layout.addRow("Email:", email_row)
        create_layout.addRow("Nome:", self.display_name_input)
        create_layout.addRow("Senha:", self.password_row)
        create_layout.addRow("Perfil:", self.role_combo)
        create_layout.addRow("Liberação:", self.is_active_combo)
        create_layout.addRow("", self.btn_create)
        sidebar_layout.addWidget(create_group)
        sidebar_layout.addStretch(1)

        content_layout.addWidget(table_panel, 3)
        content_layout.addWidget(sidebar, 1)
        layout.addLayout(content_layout, 1)

        self.btn_refresh.clicked.connect(self.refresh_users)
        self.btn_create.clicked.connect(self._handle_create_user)
        self.btn_activate.clicked.connect(lambda: self._handle_set_active(True))
        self.btn_deactivate.clicked.connect(lambda: self._handle_set_active(False))
        self.btn_reset_password.clicked.connect(self._handle_reset_password)
        self.btn_delete.clicked.connect(self._handle_delete_user)
        self.btn_apply_role.clicked.connect(self._handle_set_role)
        self.table.itemSelectionChanged.connect(self._refresh_action_state)
        self.table_search_input.textChanged.connect(self._populate_table)
        self.status_filter_combo.currentIndexChanged.connect(self._populate_table)
        self.role_filter_combo.currentIndexChanged.connect(self._populate_table)
        self.manage_role_combo.currentIndexChanged.connect(self._refresh_action_state)
        self.role_combo.currentIndexChanged.connect(self._refresh_create_role_preview)
        self._refresh_summary_chips(0)
        self._refresh_operator_context()
        self._refresh_create_role_preview()
        self._refresh_action_state()
        self._apply_responsive_layout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_responsive_layout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _is_compact_layout(self) -> bool:
        root = self.window()
        current_width = root.width() if root is not None and root.width() > 0 else self.width()
        current_height = root.height() if root is not None and root.height() > 0 else self.height()
        if current_width < 900 and not self.isVisible():
            current_width = 1920
        if current_height < 640 and not self.isVisible():
            current_height = 1080
        return current_width <= 1460 or current_height <= 860

    def _apply_responsive_layout(self) -> None:
        compact_mode = self._is_compact_layout()
        self.header_subtitle.setVisible(not compact_mode)
        self.filters_hint.setVisible(not compact_mode)
        self.table_hint.setVisible(not compact_mode)
        self.manage_hint.setVisible(not compact_mode)
        self.create_hint.setVisible(not compact_mode)
        self.create_role_hint.setVisible(not compact_mode)
        self.operator_context_label.setVisible(not compact_mode)
        self.create_domain_hint.setVisible(not compact_mode)
        self.create_permissions_label.setVisible(True)
        self.selection_permissions_label.setVisible(True)

        self.sidebar.setMinimumWidth(max(int((260 if compact_mode else 320) * self.sf), 220))
        self.btn_activate.setText("Reativar" if compact_mode else "Reativar acesso")
        self.btn_deactivate.setText("Desativar" if compact_mode else "Desativar acesso")
        self.btn_reset_password.setText("Senha" if compact_mode else "Redefinir senha")
        self.btn_delete.setText("Excluir" if compact_mode else "Excluir conta")
        self.btn_apply_role.setText("Aplicar" if compact_mode else "Aplicar perfil")

    def handle_tab_activated(self) -> None:
        self.refresh_users()

    def refresh_users(self) -> None:
        if self._busy:
            return
        self._refresh_operator_context()
        self._set_busy(True, "Atualizando usuários...")
        try:
            self.users = self.admin_service.list_users(self._access_session())
        except AdminUsersError as exc:
            self._set_busy(False, str(exc))
            QMessageBox.warning(self, "Administração", str(exc))
            return
        except Exception as exc:
            self._set_busy(False, f"Falha inesperada: {exc}")
            QMessageBox.critical(self, "Administração", f"Falha inesperada ao atualizar usuários: {exc}")
            return

        self._populate_table()
        self._set_busy(False, f"{len(self.users)} usuário(s) carregado(s).")

    def _populate_table(self) -> None:
        visible_users = self._filtered_users()
        self._refresh_summary_chips(len(visible_users))
        self.table.setRowCount(len(visible_users))
        for row_index, user in enumerate(visible_users):
            email_item = QTableWidgetItem(user.email)
            email_item.setData(Qt.UserRole, user.user_id)
            name_item = QTableWidgetItem(user.display_name or "--")
            role_item = QTableWidgetItem(_format_role(user.role))
            status_item = QTableWidgetItem(user.status_label)
            created_item = QTableWidgetItem((user.created_at or "")[:10] or "--")
            for column, item in enumerate((email_item, name_item, role_item, status_item, created_item)):
                if column == 2:
                    self._apply_role_item_style(item, user.role)
                if column == 3:
                    self._apply_status_item_style(item, user.is_active)
                self.table.setItem(row_index, column, item)
        self.table.resizeRowsToContents()
        self._refresh_action_state()

    def _apply_status_item_style(self, item: QTableWidgetItem, is_active: bool) -> None:
        base = self.palette().base().color()
        light_theme = base.lightness() >= 150
        if is_active:
            background = QColor("#d8f0df") if light_theme else QColor("#214a31")
            foreground = QColor("#1e5631") if light_theme else QColor("#f3fbf5")
        else:
            background = QColor("#f6e2b8") if light_theme else QColor("#5a4515")
            foreground = QColor("#7a5100") if light_theme else QColor("#fff4d6")
        item.setBackground(background)
        item.setForeground(foreground)

    def _apply_role_item_style(self, item: QTableWidgetItem, role: str) -> None:
        normalized_role = str(role or "").strip().lower()
        base = self.palette().base().color()
        light_theme = base.lightness() >= 150
        if normalized_role == "admin":
            background = QColor("#dfe7ff") if light_theme else QColor("#26345f")
            foreground = QColor("#1d3897") if light_theme else QColor("#eef3ff")
        elif normalized_role == "viewer":
            background = QColor("#eceff3") if light_theme else QColor("#39414a")
            foreground = QColor("#4d5968") if light_theme else QColor("#edf2f7")
        else:
            background = QColor("#e4f4ec") if light_theme else QColor("#214c39")
            foreground = QColor("#1b6b45") if light_theme else QColor("#edfff5")
        item.setBackground(background)
        item.setForeground(foreground)

    def _filtered_users(self) -> list[AdminUserRecord]:
        search_text = self.table_search_input.text().strip().lower()
        status_filter = str(self.status_filter_combo.currentData() or "all").strip()
        role_filter = str(self.role_filter_combo.currentData() or "all").strip()

        visible_users: list[AdminUserRecord] = []
        for user in self.users:
            if status_filter == "active" and not bool(user.is_active):
                continue
            if status_filter == "inactive" and bool(user.is_active):
                continue
            if role_filter != "all" and str(user.role or "").strip().lower() != role_filter:
                continue
            if search_text:
                haystack = " ".join(
                    [
                        str(user.email or ""),
                        str(user.display_name or ""),
                        str(user.role or ""),
                        str(user.status_label or ""),
                    ]
                ).lower()
                if search_text not in haystack:
                    continue
            visible_users.append(user)
        return visible_users

    def _refresh_summary_chips(self, visible_count: int | None = None) -> None:
        active_count = sum(1 for user in self.users if bool(user.is_active))
        admin_count = sum(1 for user in self.users if str(user.role or "").strip().lower() == "admin")
        visible_value = len(self.users) if visible_count is None else int(visible_count)
        self.summary_total_label.setText(f"Usuários: {len(self.users)}")
        self.summary_active_label.setText(f"Ativos: {active_count}")
        self.summary_admin_label.setText(f"Admins: {admin_count}")
        self.summary_visible_label.setText(f"Visíveis: {visible_value}")

    def _refresh_operator_context(self) -> None:
        try:
            access_session = self._access_session()
        except AdminUsersError:
            self.operator_context_label.setText(
                "Gestor atual: sessão administrativa indisponível para este ambiente."
            )
            return

        identity = str(access_session.user_email or access_session.user_id or "administrador").strip()
        self.operator_context_label.setText(
            f"Gestor atual: {identity} • {access_session.environment_display_name} • perfil {access_session.role_display_name}."
        )

    def _refresh_create_role_preview(self) -> None:
        role = str(self.role_combo.currentData() or "editor").strip().lower()
        self.create_permissions_label.setText(_role_capabilities_text(role))

    def _active_admin_count(self) -> int:
        return sum(1 for user in self.users if bool(user.is_active) and _is_admin_role(user.role))

    def _is_last_active_admin(self, user: AdminUserRecord | None) -> bool:
        return bool(
            user is not None
            and bool(user.is_active)
            and _is_admin_role(user.role)
            and self._active_admin_count() <= 1
        )

    def _confirm_admin_action(self, *, title: str, message: str) -> bool:
        return msg_confirm(
            self,
            title,
            f"{message}\n\nAmbiente: Produção oficial.",
        )

    def _selected_user(self) -> AdminUserRecord | None:
        items = self.table.selectedItems()
        if not items:
            return None
        selected_id = str(items[0].data(Qt.UserRole) or "").strip()
        for user in self.users:
            if user.user_id == selected_id:
                return user
        return None

    def _set_manage_role_value(self, role: str) -> None:
        target_role = str(role or "editor").strip().lower()
        for index in range(self.manage_role_combo.count()):
            if str(self.manage_role_combo.itemData(index) or "").strip().lower() == target_role:
                previous = self.manage_role_combo.blockSignals(True)
                self.manage_role_combo.setCurrentIndex(index)
                self.manage_role_combo.blockSignals(previous)
                return

    def _refresh_action_state(self) -> None:
        user = self._selected_user()
        access_session = self._access_session()
        can_manage = user is not None and not self._busy
        can_manage_self = user is not None and user.user_id == access_session.user_id
        is_last_active_admin = self._is_last_active_admin(user)
        if user is None:
            self._last_role_sync_user_id = ""
        elif user.user_id != self._last_role_sync_user_id:
            self._set_manage_role_value(user.role)
            self._last_role_sync_user_id = user.user_id
        self.btn_activate.setEnabled(can_manage and not bool(user.is_active) and not can_manage_self)
        self.btn_deactivate.setEnabled(
            can_manage and bool(user.is_active) and not can_manage_self and not is_last_active_admin
        )
        self.btn_reset_password.setEnabled(can_manage)
        self.btn_delete.setEnabled(can_manage and not can_manage_self and not is_last_active_admin)
        self.manage_role_combo.setEnabled(can_manage and not can_manage_self)
        self.btn_apply_role.setEnabled(
            can_manage
            and not can_manage_self
            and user is not None
            and str(self.manage_role_combo.currentData() or "").strip().lower() != str(user.role or "").strip().lower()
            and not (is_last_active_admin and str(self.manage_role_combo.currentData() or "").strip().lower() != "admin")
        )
        if user is None:
            self.selection_summary_label.setText("Nenhuma conta selecionada")
            self.selection_profile_label.setText("Perfil: --")
            self.selection_status_label.setText("Situação: --")
            self.selection_created_label.setText("Criado: --")
            self.selection_permissions_label.setText("Permissões: selecione uma conta para ver o escopo do perfil.")
            self.manage_role_combo.setCurrentIndex(1)
            self.selection_hint.setText("Selecione uma conta para revisar perfil, situação e ações administrativas disponíveis.")
        elif can_manage_self:
            self.selection_summary_label.setText(f"{user.email} | sua conta")
            self.selection_profile_label.setText(f"Perfil: {_format_role(user.role)}")
            self.selection_status_label.setText(f"Situação: {user.status_label}")
            self.selection_created_label.setText(f"Criado: {(user.created_at or '')[:10] or '--'}")
            self.selection_permissions_label.setText(_role_capabilities_text(user.role))
            if is_last_active_admin:
                self.selection_hint.setText(
                    "Sua própria conta também é o último administrador ativo. Ela não pode ser desativada, excluída nem rebaixada por esta tela."
                )
            else:
                self.selection_hint.setText(
                    "Sua própria conta não pode ser desativada, excluída nem ter o perfil alterado por esta tela, mas a senha ainda pode ser redefinida."
                )
        elif is_last_active_admin:
            self.selection_summary_label.setText(f"{user.email} | administrador protegido")
            self.selection_profile_label.setText(f"Perfil: {_format_role(user.role)}")
            self.selection_status_label.setText(f"Situação: {user.status_label}")
            self.selection_created_label.setText(f"Criado: {(user.created_at or '')[:10] or '--'}")
            self.selection_permissions_label.setText(_role_capabilities_text(user.role))
            self.selection_hint.setText(
                "Proteção ativa: este é o último administrador ativo. A conta não pode ser desativada, excluída nem rebaixada."
            )
        else:
            self.selection_summary_label.setText(f"{user.email} | {_format_role(user.role)}")
            self.selection_profile_label.setText(f"Perfil: {_format_role(user.role)}")
            self.selection_status_label.setText(f"Situação: {user.status_label}")
            self.selection_created_label.setText(f"Criado: {(user.created_at or '')[:10] or '--'}")
            self.selection_permissions_label.setText(_role_capabilities_text(user.role))
            self.selection_hint.setText(
                f"Conta pronta para gestão: {user.email} • {_format_role(user.role)} • {user.status_label}"
            )

    def _normalize_email_field(self) -> None:
        local_part = display_corporate_email_local_part(self.email_input.text())
        if local_part != self.email_input.text():
            self.email_input.setText(local_part)

    def _handle_create_user(self) -> None:
        self._set_busy(True, "Cadastrando usuário...")
        try:
            created = self.admin_service.create_user(
                self._access_session(),
                email=self.email_input.text(),
                password=self.password_input.text(),
                display_name=self.display_name_input.text(),
                role=str(self.role_combo.currentData() or "editor"),
                is_active=bool(self.is_active_combo.currentData()),
            )
        except AdminUsersError as exc:
            self._set_busy(False, str(exc))
            QMessageBox.warning(self, "Administração", str(exc))
            return
        except Exception as exc:
            self._set_busy(False, f"Falha inesperada: {exc}")
            QMessageBox.critical(self, "Administração", f"Falha inesperada ao cadastrar usuário: {exc}")
            return

        self.email_input.clear()
        self.display_name_input.clear()
        self.password_input.clear()
        self.role_combo.setCurrentIndex(0)
        self.is_active_combo.setCurrentIndex(0)
        self.status_label.setText(f"Usuário {created.email} cadastrado com sucesso.")
        self.refresh_users()

    def _handle_set_active(self, is_active: bool) -> None:
        user = self._selected_user()
        if user is None:
            return
        if not is_active and self._is_last_active_admin(user):
            QMessageBox.warning(
                self,
                "Administração",
                "Não é possível desativar o último administrador ativo do ambiente oficial.",
            )
            return
        if not self._confirm_admin_action(
            title="Atualizar acesso",
            message=(
                f"Deseja {'reativar' if is_active else 'desativar'} a conta {user.email} "
                f"com perfil {_format_role(user.role)}?"
            ),
        ):
            return
        self._set_busy(True, "Atualizando status do usuário...")
        try:
            updated = self.admin_service.set_user_active(
                self._access_session(),
                user_id=user.user_id,
                is_active=is_active,
            )
        except AdminUsersError as exc:
            self._set_busy(False, str(exc))
            QMessageBox.warning(self, "Administração", str(exc))
            return
        except Exception as exc:
            self._set_busy(False, f"Falha inesperada: {exc}")
            QMessageBox.critical(self, "Administração", f"Falha inesperada ao atualizar usuário: {exc}")
            return

        self.status_label.setText(
            f"Usuário {updated.email} agora está {'ativo' if updated.is_active else 'inativo'}."
        )
        self.refresh_users()

    def _handle_delete_user(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        if self._is_last_active_admin(user):
            QMessageBox.warning(
                self,
                "Administração",
                "Não é possível excluir o último administrador ativo do ambiente oficial.",
            )
            return
        if not self._confirm_admin_action(
            title="Excluir usuário",
            message=(
                f"Deseja excluir definitivamente a conta {user.email}? "
                "Essa ação remove o acesso do usuário à base oficial."
            ),
        ):
            return

        self._set_busy(True, "Excluindo usuário...")
        try:
            self.admin_service.delete_user(self._access_session(), user_id=user.user_id)
        except AdminUsersError as exc:
            self._set_busy(False, str(exc))
            QMessageBox.warning(self, "Administração", str(exc))
            return
        except Exception as exc:
            self._set_busy(False, f"Falha inesperada: {exc}")
            QMessageBox.critical(self, "Administração", f"Falha inesperada ao excluir usuário: {exc}")
            return

        self.status_label.setText(f"Usuário {user.email} excluído com sucesso.")
        self.refresh_users()

    def _handle_reset_password(self) -> None:
        user = self._selected_user()
        if user is None:
            return

        dialog = ResetUserPasswordDialog(user.email, self)
        if not dialog.exec():
            return

        self._set_busy(True, "Redefinindo senha do usuário...")
        try:
            updated = self.admin_service.reset_user_password(
                self._access_session(),
                user_id=user.user_id,
                password=dialog.password(),
            )
        except AdminUsersError as exc:
            self._set_busy(False, str(exc))
            QMessageBox.warning(self, "Administração", str(exc))
            return
        except Exception as exc:
            self._set_busy(False, f"Falha inesperada: {exc}")
            QMessageBox.critical(self, "Administração", f"Falha inesperada ao redefinir senha: {exc}")
            return

        self.status_label.setText(f"Senha redefinida com sucesso para {updated.email}.")
        self._set_busy(False, self.status_label.text())

    def _handle_set_role(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        next_role = str(self.manage_role_combo.currentData() or "editor").strip().lower()
        current_role = str(user.role or "").strip().lower()
        if next_role == current_role:
            return
        if self._is_last_active_admin(user) and next_role != "admin":
            QMessageBox.warning(
                self,
                "Administração",
                "Não é possível rebaixar o último administrador ativo do ambiente oficial.",
            )
            return
        if not self._confirm_admin_action(
            title="Alterar perfil",
            message=(
                f"Deseja alterar o perfil de {user.email} de {_format_role(current_role)} "
                f"para {_format_role(next_role)}?"
            ),
        ):
            self._set_manage_role_value(current_role)
            self._refresh_action_state()
            return

        self._set_busy(True, "Atualizando perfil do usuário...")
        try:
            updated = self.admin_service.set_user_role(
                self._access_session(),
                user_id=user.user_id,
                role=next_role,
            )
        except AdminUsersError as exc:
            self._set_manage_role_value(current_role)
            self._set_busy(False, str(exc))
            QMessageBox.warning(self, "Administração", str(exc))
            return
        except Exception as exc:
            self._set_manage_role_value(current_role)
            self._set_busy(False, f"Falha inesperada: {exc}")
            QMessageBox.critical(self, "Administração", f"Falha inesperada ao atualizar perfil: {exc}")
            return

        self.status_label.setText(
            f"Perfil atualizado: {updated.email} agora é {_format_role(updated.role)}."
        )
        self.refresh_users()

    def _set_busy(self, busy: bool, message: str) -> None:
        self._busy = busy
        self.status_label.setText(message)
        self.btn_refresh.setEnabled(not busy)
        self.btn_create.setEnabled(not busy)
        self.btn_reset_password.setEnabled(not busy and self._selected_user() is not None)
        for widget in (
            self.table_search_input,
            self.status_filter_combo,
            self.role_filter_combo,
            self.email_input,
            self.display_name_input,
            self.password_input,
            self.role_combo,
            self.is_active_combo,
            self.manage_role_combo,
            self.table,
        ):
            widget.setEnabled(not busy)
        self._refresh_action_state()

    def _access_session(self) -> AppAccessSession:
        access_session = getattr(self.main_window, "access_session", None)
        if not isinstance(access_session, AppAccessSession):
            raise AdminUsersError("Sessão autenticada ausente para administração.")
        if access_session.environment != AccessEnvironment.PRODUCTION:
            raise AdminUsersError("Administração de usuários disponível apenas em Produção.")
        if str(access_session.app_role or "").strip().lower() != "admin":
            raise AdminUsersError("Apenas administradores podem abrir esta tela.")
        return access_session



