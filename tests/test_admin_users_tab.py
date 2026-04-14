import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QBoxLayout, QLineEdit, QWidget

from app.services.access_service import AccessEnvironment, AppAccessSession
from app.services.supabase_admin_users_service import AdminUserRecord
from app.ui.tabs.admin_users_tab import AdminUsersTab, CreateUserDialog, EditUserDialog, ResetUserPasswordDialog


STRONG_PASSWORD = "SenhaSegura1!"
UPDATED_STRONG_PASSWORD = "SenhaNova123!"


def _app():
    return QApplication.instance() or QApplication([])


class _FakeAdminUsersService:
    def __init__(self):
        self.users = [
            AdminUserRecord(
                user_id="admin-1",
                email="admin@prefeitura.sp.gov.br",
                display_name="Administrador",
                role="admin",
                is_active=True,
                created_at="2026-04-06T12:00:00Z",
            ),
            AdminUserRecord(
                user_id="editor-1",
                email="editor@prefeitura.sp.gov.br",
                display_name="Editor",
                role="editor",
                is_active=False,
                created_at="2026-04-06T12:10:00Z",
            ),
        ]
        self.create_calls = []
        self.update_calls = []
        self.reset_calls = []
        self.role_calls = []

    def list_users(self, _access_session):
        return list(self.users)

    def create_user(self, _access_session, *, email, password, display_name="", role="editor", is_active=True):
        self.create_calls.append((email, password, display_name, role, is_active))
        created = AdminUserRecord(
            user_id=f"user-{len(self.users) + 1}",
            email=f"{email}@saocarlos.sp.gov.br" if "@" not in email else email,
            display_name=display_name,
            role=role,
            is_active=is_active,
            created_at="2026-04-07T12:00:00Z",
        )
        self.users.append(created)
        return created

    def update_user(self, _access_session, *, user_id, email, display_name=""):
        self.update_calls.append((user_id, email, display_name))
        for index, user in enumerate(self.users):
            if user.user_id == user_id:
                updated = AdminUserRecord(
                    user_id=user.user_id,
                    email=f"{email}@saocarlos.sp.gov.br" if "@" not in email else email,
                    display_name=display_name,
                    role=user.role,
                    is_active=user.is_active,
                    created_at=user.created_at,
                    updated_at="2026-04-08T12:00:00Z",
                )
                self.users[index] = updated
                return updated
        raise AssertionError("user not found")

    def reset_user_password(self, _access_session, *, user_id, password):
        self.reset_calls.append((user_id, password))
        return next(user for user in self.users if user.user_id == user_id)

    def set_user_role(self, _access_session, *, user_id, role):
        self.role_calls.append((user_id, role))
        for index, user in enumerate(self.users):
            if user.user_id == user_id:
                updated = AdminUserRecord(
                    user_id=user.user_id,
                    email=user.email,
                    display_name=user.display_name,
                    role=role,
                    is_active=user.is_active,
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                )
                self.users[index] = updated
                return updated
        raise AssertionError("user not found")


class _FakeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.scale_factor = 1.0
        self.access_session = AppAccessSession(
            environment=AccessEnvironment.PRODUCTION,
            label="Producao",
            auth_mode="password",
            user_id="admin-1",
            user_email="admin@prefeitura.sp.gov.br",
            app_role="admin",
            access_token="token",
            refresh_token="refresh",
        )


def test_admin_users_tab_refreshes_and_populates_table():
    _app()
    tab = AdminUsersTab(_FakeWindow(), admin_service=_FakeAdminUsersService())

    tab.refresh_users()

    assert tab.table.rowCount() == 2
    assert tab.table.item(0, 0).text() == "admin@prefeitura.sp.gov.br"


def test_admin_users_tab_disables_self_management_actions():
    _app()
    tab = AdminUsersTab(_FakeWindow(), admin_service=_FakeAdminUsersService())
    tab.refresh_users()

    tab.table.selectRow(0)
    tab._refresh_action_state()

    assert tab.btn_deactivate.isEnabled() is False
    assert tab.btn_delete.isEnabled() is False
    assert "própria conta" in tab.selection_hint.text().lower()
    assert tab.btn_apply_role.isEnabled() is False


def test_create_user_dialog_strips_default_domain_from_email_field():
    _app()
    dialog = CreateUserDialog()

    dialog.email_input.setText("novo.usuario@saocarlos.sp.gov.br")
    dialog._normalize_email_field()

    assert dialog.email_input.text() == "novo.usuario"


def test_admin_users_tab_enables_password_reset_for_selected_self():
    _app()
    tab = AdminUsersTab(_FakeWindow(), admin_service=_FakeAdminUsersService())
    tab.refresh_users()

    tab.table.selectRow(0)
    tab._refresh_action_state()

    assert tab.btn_reset_password.isEnabled() is True


def test_admin_users_tab_marks_last_active_admin_as_protected():
    _app()
    tab = AdminUsersTab(_FakeWindow(), admin_service=_FakeAdminUsersService())
    tab.refresh_users()

    tab.table.selectRow(0)
    tab._refresh_action_state()

    assert tab.btn_deactivate.isEnabled() is False
    assert tab.btn_delete.isEnabled() is False
    assert "último administrador ativo" in tab.selection_hint.text().lower()


def test_admin_users_tab_resets_password(monkeypatch):
    _app()
    fake_service = _FakeAdminUsersService()

    class _FakeResetDialog:
        def __init__(self, email, parent=None):
            self.email = email

        def exec(self):
            return 1

        def password(self):
            return UPDATED_STRONG_PASSWORD

    monkeypatch.setattr("app.ui.tabs.admin_users_tab.ResetUserPasswordDialog", _FakeResetDialog)

    tab = AdminUsersTab(_FakeWindow(), admin_service=fake_service)
    tab.refresh_users()
    tab.table.selectRow(1)

    tab._handle_reset_password()

    assert fake_service.reset_calls == [("editor-1", UPDATED_STRONG_PASSWORD)]


def test_admin_users_tab_applies_selected_role(monkeypatch):
    _app()
    fake_service = _FakeAdminUsersService()
    monkeypatch.setattr("app.ui.tabs.admin_users_tab.msg_confirm", lambda *args, **kwargs: True)
    tab = AdminUsersTab(_FakeWindow(), admin_service=fake_service)
    tab.refresh_users()
    tab.table.selectRow(1)
    tab._refresh_action_state()

    tab.manage_role_combo.setCurrentIndex(2)
    tab._handle_set_role()

    assert fake_service.role_calls == [("editor-1", "viewer")]


def test_create_user_dialog_inputs_enable_clear_buttons():
    _app()
    dialog = CreateUserDialog()
    tab = AdminUsersTab(_FakeWindow(), admin_service=_FakeAdminUsersService())

    assert dialog.email_input.isClearButtonEnabled() is True
    assert dialog.display_name_input.isClearButtonEnabled() is True
    assert dialog.password_input.isClearButtonEnabled() is True
    assert tab.btn_new_user.toolTip() != ""
    assert tab.btn_reset_password.toolTip() != ""


def test_create_user_dialog_password_toggle_changes_echo_mode():
    _app()
    dialog = CreateUserDialog()

    assert dialog.password_input.echoMode() == QLineEdit.Password

    dialog.password_toggle_button.click()

    assert dialog.password_input.echoMode() == QLineEdit.Normal
    assert dialog.password_toggle_button.text() == "Ocultar"


def test_reset_user_password_dialog_allows_password_visibility_toggle():
    _app()
    dialog = ResetUserPasswordDialog("usuario@prefeitura.sp.gov.br")

    assert dialog.password_input.echoMode() == QLineEdit.Password
    assert dialog.confirm_password_input.echoMode() == QLineEdit.Password

    dialog.password_toggle_button.click()
    dialog.confirm_password_toggle_button.click()

    assert dialog.password_input.echoMode() == QLineEdit.Normal
    assert dialog.confirm_password_input.echoMode() == QLineEdit.Normal


def test_create_user_dialog_updates_role_preview():
    _app()
    dialog = CreateUserDialog()

    dialog.role_combo.setCurrentIndex(2)
    dialog._refresh_role_preview()

    assert "gerenciar usuários" in dialog.role_preview_label.text().lower()


def test_edit_user_dialog_prefills_and_normalizes_email():
    _app()
    dialog = EditUserDialog(email="analista@saocarlos.sp.gov.br", display_name="Analista")

    assert dialog.email_input.text() == "analista"
    assert dialog.display_name_input.text() == "Analista"

    dialog.email_input.setText("analista@saocarlos.sp.gov.br")
    dialog._normalize_email_field()

    assert dialog.email_input.text() == "analista"


def test_admin_users_tab_creates_user_from_dialog(monkeypatch):
    _app()
    fake_service = _FakeAdminUsersService()

    class _FakeCreateDialog:
        def __init__(self, parent=None):
            self.parent = parent

        def exec(self):
            return 1

        def values(self):
            return {
                "email": "novo.usuario",
                "display_name": "Novo usuário",
                "password": UPDATED_STRONG_PASSWORD,
                "role": "viewer",
                "is_active": False,
            }

    monkeypatch.setattr("app.ui.tabs.admin_users_tab.CreateUserDialog", _FakeCreateDialog)

    tab = AdminUsersTab(_FakeWindow(), admin_service=fake_service)
    tab.refresh_users()

    tab._open_create_user_dialog()

    assert fake_service.create_calls == [
        ("novo.usuario", UPDATED_STRONG_PASSWORD, "Novo usuário", "viewer", False)
    ]
    assert len(fake_service.users) == 3
    assert tab.table.rowCount() == 3


def test_reset_user_password_dialog_rejects_weak_password():
    _app()
    dialog = ResetUserPasswordDialog("usuario@prefeitura.sp.gov.br")
    dialog.password_input.setText("fraca123456!")
    dialog.confirm_password_input.setText("fraca123456!")

    dialog._submit()

    assert dialog.status_label.text() == "A senha precisa ter uma letra maiuscula."


def test_admin_users_tab_updates_selected_user_from_dialog(monkeypatch):
    _app()
    fake_service = _FakeAdminUsersService()

    class _FakeEditDialog:
        def __init__(self, *, email, display_name, parent=None):
            self.email = email
            self.display_name = display_name
            self.parent = parent

        def exec(self):
            return 1

        def values(self):
            return {
                "email": "editor.corrigido",
                "display_name": "Editor Corrigido",
            }

    monkeypatch.setattr("app.ui.tabs.admin_users_tab.EditUserDialog", _FakeEditDialog)

    tab = AdminUsersTab(_FakeWindow(), admin_service=fake_service)
    tab.refresh_users()
    tab.table.selectRow(1)
    tab._refresh_action_state()

    tab._handle_edit_user()

    assert fake_service.update_calls == [("editor-1", "editor.corrigido", "Editor Corrigido")]
    assert tab.table.rowCount() == 2
    assert tab.table.item(1, 0).text() == "editor.corrigido@saocarlos.sp.gov.br"
    assert tab.table.item(1, 1).text() == "Editor Corrigido"
    assert tab.table.selectedItems() or tab.table.currentRow() == 1


def test_admin_users_tab_uses_stacked_layout_when_window_is_compact():
    _app()
    window = _FakeWindow()
    window.resize(1180, 780)
    tab = AdminUsersTab(window, admin_service=_FakeAdminUsersService())

    tab._apply_responsive_layout()

    assert tab.content_layout.direction() == QBoxLayout.TopToBottom
    assert tab.role_editor_row.direction() == QBoxLayout.TopToBottom
    assert tab.action_row_primary.direction() == QBoxLayout.TopToBottom
    assert tab.action_row_secondary.direction() == QBoxLayout.TopToBottom
    assert tab.sidebar.minimumWidth() == 0
    assert tab.btn_new_user.text() == "Novo"


def test_admin_users_tab_keeps_side_by_side_layout_when_window_is_wide():
    _app()
    window = _FakeWindow()
    window.resize(1800, 1000)
    tab = AdminUsersTab(window, admin_service=_FakeAdminUsersService())

    tab._apply_responsive_layout()

    assert tab.content_layout.direction() == QBoxLayout.LeftToRight
    assert tab.role_editor_row.direction() == QBoxLayout.LeftToRight
    assert tab.action_row_primary.direction() == QBoxLayout.LeftToRight
    assert tab.action_row_secondary.direction() == QBoxLayout.LeftToRight
    assert tab.sidebar.minimumWidth() >= 220
    assert tab.btn_new_user.text() == "Novo usuário"

