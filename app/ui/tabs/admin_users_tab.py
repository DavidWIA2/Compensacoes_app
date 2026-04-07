from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
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
from app.ui.components.ui_utils import msg_confirm


def _format_role(role: str) -> str:
    normalized = str(role or "").strip().lower()
    if normalized == "admin":
        return "Administrador"
    if normalized == "viewer":
        return "Leitor"
    return "Editor"


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
        self.password_input.setPlaceholderText("Senha provisória com 8+ caracteres")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.confirm_password_input = QLineEdit(self)
        self.confirm_password_input.setPlaceholderText("Repita a senha")
        self.confirm_password_input.setEchoMode(QLineEdit.Password)
        self.confirm_password_input.returnPressed.connect(self._submit)

        form.addRow("Senha:", self.password_input)
        form.addRow("Confirmar:", self.confirm_password_input)
        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("FormStateLabel")
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_button = QPushButton("Cancelar")
        cancel_button.clicked.connect(self.reject)
        submit_button = QPushButton("Aplicar senha")
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
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        layout.setSpacing(int(10 * self.sf))

        title = QLabel("Administração de usuários")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        subtitle = QLabel(
            "Tela restrita a administradores ativos. Aqui você cadastra novos acessos e controla usuários existentes."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("FormStateLabel")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        top_actions = QHBoxLayout()
        self.status_label = QLabel("Abra esta aba ou use Atualizar para carregar os usuários.")
        self.status_label.setObjectName("FormStateLabel")
        self.btn_refresh = QPushButton("Atualizar")
        self.btn_refresh.setProperty("kind", "secondary")
        top_actions.addWidget(self.status_label, 1)
        top_actions.addWidget(self.btn_refresh)
        layout.addLayout(top_actions)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(["Email", "Nome", "Perfil", "Situação", "Criado"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        action_row = QHBoxLayout()
        self.btn_activate = QPushButton("Reativar")
        self.btn_activate.setProperty("kind", "secondary")
        self.btn_deactivate = QPushButton("Desativar")
        self.btn_deactivate.setProperty("kind", "secondary")
        self.btn_reset_password = QPushButton("Redefinir senha")
        self.btn_reset_password.setProperty("kind", "secondary")
        self.btn_delete = QPushButton("Excluir")
        self.btn_delete.setProperty("kind", "danger")
        self.selection_hint = QLabel("Selecione um usuário para gerenciar.")
        self.selection_hint.setObjectName("FormStateLabel")
        action_row.addWidget(self.btn_activate)
        action_row.addWidget(self.btn_deactivate)
        action_row.addWidget(self.btn_reset_password)
        action_row.addWidget(self.btn_delete)
        action_row.addWidget(self.selection_hint, 1)
        layout.addLayout(action_row)

        create_group = QGroupBox("Novo usuário")
        create_layout = QFormLayout(create_group)
        create_layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        create_layout.setHorizontalSpacing(int(12 * self.sf))
        create_layout.setVerticalSpacing(int(10 * self.sf))

        self.email_input = QLineEdit(self)
        self.email_input.setPlaceholderText("nome.sobrenome")
        self.email_input.editingFinished.connect(self._normalize_email_field)
        self.display_name_input = QLineEdit(self)
        self.display_name_input.setPlaceholderText("Nome para exibição")
        self.password_input = QLineEdit(self)
        self.password_input.setPlaceholderText("Senha provisória")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.role_combo = QComboBox(self)
        self.role_combo.addItem("Editor", "editor")
        self.role_combo.addItem("Leitor", "viewer")
        self.role_combo.addItem("Administrador", "admin")
        self.is_active_combo = QComboBox(self)
        self.is_active_combo.addItem("Ativo", True)
        self.is_active_combo.addItem("Inativo", False)
        self.btn_create = QPushButton("Cadastrar usuário")

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
        create_layout.addRow("Senha:", self.password_input)
        create_layout.addRow("Perfil:", self.role_combo)
        create_layout.addRow("Liberação:", self.is_active_combo)
        create_layout.addRow("", self.btn_create)
        layout.addWidget(create_group)

        self.btn_refresh.clicked.connect(self.refresh_users)
        self.btn_create.clicked.connect(self._handle_create_user)
        self.btn_activate.clicked.connect(lambda: self._handle_set_active(True))
        self.btn_deactivate.clicked.connect(lambda: self._handle_set_active(False))
        self.btn_reset_password.clicked.connect(self._handle_reset_password)
        self.btn_delete.clicked.connect(self._handle_delete_user)
        self.table.itemSelectionChanged.connect(self._refresh_action_state)
        self._refresh_action_state()

    def handle_tab_activated(self) -> None:
        self.refresh_users()

    def refresh_users(self) -> None:
        if self._busy:
            return
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
        self.table.setRowCount(len(self.users))
        for row_index, user in enumerate(self.users):
            email_item = QTableWidgetItem(user.email)
            email_item.setData(Qt.UserRole, user.user_id)
            name_item = QTableWidgetItem(user.display_name or "--")
            role_item = QTableWidgetItem(_format_role(user.role))
            status_item = QTableWidgetItem(user.status_label)
            created_item = QTableWidgetItem((user.created_at or "")[:10] or "--")
            for column, item in enumerate((email_item, name_item, role_item, status_item, created_item)):
                if column == 3:
                    if user.is_active:
                        item.setBackground(Qt.GlobalColor.green)
                        item.setForeground(Qt.GlobalColor.white)
                    else:
                        item.setBackground(Qt.GlobalColor.darkYellow)
                        item.setForeground(Qt.GlobalColor.black)
                self.table.setItem(row_index, column, item)
        self.table.resizeRowsToContents()
        self._refresh_action_state()

    def _selected_user(self) -> AdminUserRecord | None:
        items = self.table.selectedItems()
        if not items:
            return None
        selected_id = str(items[0].data(Qt.UserRole) or "").strip()
        for user in self.users:
            if user.user_id == selected_id:
                return user
        return None

    def _refresh_action_state(self) -> None:
        user = self._selected_user()
        access_session = self._access_session()
        can_manage = user is not None and not self._busy
        can_manage_self = user is not None and user.user_id == access_session.user_id
        self.btn_activate.setEnabled(can_manage and not bool(user.is_active) and not can_manage_self)
        self.btn_deactivate.setEnabled(can_manage and bool(user.is_active) and not can_manage_self)
        self.btn_reset_password.setEnabled(can_manage)
        self.btn_delete.setEnabled(can_manage and not can_manage_self)
        if user is None:
            self.selection_hint.setText("Selecione um usuário para gerenciar.")
        elif can_manage_self:
            self.selection_hint.setText(
                "Seu próprio usuário não pode ser desativado ou excluído por esta tela, "
                "mas a senha ainda pode ser redefinida."
            )
        else:
            self.selection_hint.setText(
                f"Selecionado: {user.email} | {_format_role(user.role)} | {user.status_label}"
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
        if not msg_confirm(
            self,
            "Excluir usuário",
            f"Deseja excluir o usuário {user.email}?",
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

    def _set_busy(self, busy: bool, message: str) -> None:
        self._busy = busy
        self.status_label.setText(message)
        self.btn_refresh.setEnabled(not busy)
        self.btn_create.setEnabled(not busy)
        self.btn_reset_password.setEnabled(not busy and self._selected_user() is not None)
        for widget in (
            self.email_input,
            self.display_name_input,
            self.password_input,
            self.role_combo,
            self.is_active_combo,
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
