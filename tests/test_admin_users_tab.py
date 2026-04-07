import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from app.services.access_service import AccessEnvironment, AppAccessSession
from app.services.supabase_admin_users_service import AdminUserRecord
from app.ui.tabs.admin_users_tab import AdminUsersTab


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
        self.reset_calls = []

    def list_users(self, _access_session):
        return list(self.users)

    def reset_user_password(self, _access_session, *, user_id, password):
        self.reset_calls.append((user_id, password))
        return next(user for user in self.users if user.user_id == user_id)


class _FakeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.scale_factor = 1.0
        self.access_session = AppAccessSession(
            environment=AccessEnvironment.PRODUCTION,
            label="Produção",
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
    assert "próprio usuário" in tab.selection_hint.text().lower()


def test_admin_users_tab_strips_default_domain_from_email_field():
    _app()
    tab = AdminUsersTab(_FakeWindow(), admin_service=_FakeAdminUsersService())

    tab.email_input.setText("novo.usuario@saocarlos.sp.gov.br")
    tab._normalize_email_field()

    assert tab.email_input.text() == "novo.usuario"


def test_admin_users_tab_enables_password_reset_for_selected_self():
    _app()
    tab = AdminUsersTab(_FakeWindow(), admin_service=_FakeAdminUsersService())
    tab.refresh_users()

    tab.table.selectRow(0)
    tab._refresh_action_state()

    assert tab.btn_reset_password.isEnabled() is True


def test_admin_users_tab_resets_password(monkeypatch):
    _app()
    fake_service = _FakeAdminUsersService()

    class _FakeResetDialog:
        def __init__(self, email, parent=None):
            self.email = email

        def exec(self):
            return 1

        def password(self):
            return "senha-nova-segura"

    monkeypatch.setattr("app.ui.tabs.admin_users_tab.ResetUserPasswordDialog", _FakeResetDialog)

    tab = AdminUsersTab(_FakeWindow(), admin_service=fake_service)
    tab.refresh_users()
    tab.table.selectRow(1)

    tab._handle_reset_password()

    assert fake_service.reset_calls == [("editor-1", "senha-nova-segura")]
