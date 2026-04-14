import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

from app.services.access_service import AppAccessSession, SupabaseAccessService
from app.services.app_settings import AppSettings
from app.ui.components import access_dialog as access_dialog_module
from app.ui.components.access_dialog import (
    AccessDialog,
    BootstrapFirstAdminDialog,
    ChangePasswordDialog,
    CompletePasswordResetDialog,
    RequestPasswordResetDialog,
)


STRONG_PASSWORD = "SenhaSegura1!"
UPDATED_STRONG_PASSWORD = "SenhaNova123!"
CURRENT_STRONG_PASSWORD = "SenhaAtual123!"


def _app():
    return QApplication.instance() or QApplication([])


class _MemorySettings(AppSettings):
    def __init__(self):
        self._values = {}

    def value(self, key, default=None):
        return self._values.get(key, default)

    def setValue(self, key, value):
        self._values[key] = value

    def remove(self, key):
        self._values.pop(key, None)


class _FakeAccessService:
    def __init__(self, *, must_change_password: bool = False):
        self.production_profile = SupabaseAccessService().production_profile
        self.reset_requests = []
        self.reset_completions = []
        self.password_changes = []
        self.sign_out_calls = []
        self._session = AppAccessSession(
            environment=self.production_profile.environment,
            label="Produção",
            auth_mode="password",
            user_id="admin-1",
            user_email="admin@saocarlos.sp.gov.br",
            app_role="admin",
            access_token="token",
            refresh_token="refresh",
            local_db_path="C:/tmp/producao.db",
            local_session_path="session://banco-local",
            must_change_password=must_change_password,
        )

    def can_sign_in_production(self):
        return True

    def demo_entry_label(self):
        return "Demonstração local"

    def enter_demo(self):
        raise AssertionError("Não deveria abrir demo neste teste")

    def sign_in_production(self, *, email, password):
        assert email in {"admin@saocarlos.sp.gov.br", "admin"}
        assert password == STRONG_PASSWORD
        return self._session

    def request_password_reset(self, *, email):
        self.reset_requests.append(email)
        return "email enviado"

    def complete_password_reset(self, *, email, recovery_value, new_password):
        self.reset_completions.append(
            {
                "email": email,
                "recovery_value": recovery_value,
                "new_password": new_password,
            }
        )
        return "senha atualizada"

    def change_password(self, *, access_session, current_password, new_password):
        self.password_changes.append(
            {
                "access_session": access_session,
                "current_password": current_password,
                "new_password": new_password,
            }
        )
        return AppAccessSession(
            environment=access_session.environment,
            label=access_session.label,
            auth_mode=access_session.auth_mode,
            user_id=access_session.user_id,
            user_email=access_session.user_email,
            app_role=access_session.app_role,
            access_token="token-atualizado",
            refresh_token="refresh-atualizado",
            local_db_path=access_session.local_db_path,
            local_session_path=access_session.local_session_path,
            must_change_password=False,
        )

    def sign_out_session(self, access_session):
        self.sign_out_calls.append(access_session)


class _FakeAdminUsersService:
    def bootstrap_status(self):
        return type("Status", (), {"allowed": True})()

    def bootstrap_first_admin(self, *, email, password, display_name):
        assert email == "admin@saocarlos.sp.gov.br"
        assert password == STRONG_PASSWORD
        assert display_name == "Administrador"
        return object()


class _MissingSupabaseAccessService(_FakeAccessService):
    def can_sign_in_production(self):
        return False

    def production_sign_in_unavailability_reason(self):
        return (
            "Esta instalação foi gerada sem o cliente oficial do Supabase. "
            "Use a demonstração local ou reinstale a release corrigida."
        )


def test_access_dialog_shows_bootstrap_button_when_first_admin_is_allowed():
    _app()
    dialog = AccessDialog(
        settings=_MemorySettings(),
        access_service=_FakeAccessService(),
        admin_users_service=_FakeAdminUsersService(),
    )

    assert dialog.bootstrap_button.isHidden() is False


def test_access_dialog_explains_missing_supabase_dependency_without_enabling_login():
    _app()
    dialog = AccessDialog(
        settings=_MemorySettings(),
        access_service=_MissingSupabaseAccessService(),
        admin_users_service=_FakeAdminUsersService(),
    )

    assert dialog.production_button.isEnabled() is False
    assert dialog.password_input.isEnabled() is False
    assert "cliente oficial do Supabase" in dialog.production_status.text()


def test_access_dialog_bootstrap_flow_authenticates_new_admin(monkeypatch):
    _app()

    class _FakeBootstrapDialog:
        def __init__(self, parent=None):
            self.email_input = type("Field", (), {"setText": lambda self, text: None})()

        def exec(self):
            return 1

        def payload(self):
            return {
                "display_name": "Administrador",
                "email": "admin@saocarlos.sp.gov.br",
                "password": STRONG_PASSWORD,
            }

    monkeypatch.setattr(access_dialog_module, "BootstrapFirstAdminDialog", _FakeBootstrapDialog)

    dialog = AccessDialog(
        settings=_MemorySettings(),
        access_service=_FakeAccessService(),
        admin_users_service=_FakeAdminUsersService(),
    )

    dialog._handle_bootstrap_admin()

    assert dialog.access_session is not None
    assert dialog.access_session.user_email == "admin@saocarlos.sp.gov.br"


def test_access_dialog_prefills_only_local_part_for_corporate_email():
    _app()
    settings = _MemorySettings()
    settings.set_last_access_email("david.oliveira@saocarlos.sp.gov.br")
    dialog = AccessDialog(
        settings=settings,
        access_service=_FakeAccessService(),
        admin_users_service=_FakeAdminUsersService(),
    )

    assert dialog.email_input.text() == "david.oliveira"


def test_bootstrap_dialog_payload_appends_default_corporate_domain():
    _app()
    dialog = BootstrapFirstAdminDialog()
    dialog.display_name_input.setText("Administrador")
    dialog.email_input.setText("david.oliveira")
    dialog.password_input.setText(STRONG_PASSWORD)
    dialog.confirm_password_input.setText(STRONG_PASSWORD)

    assert dialog.payload()["email"] == "david.oliveira@saocarlos.sp.gov.br"


def test_request_password_reset_dialog_payload_appends_default_corporate_domain():
    _app()
    dialog = RequestPasswordResetDialog()
    dialog.email_input.setText("david.oliveira")

    assert dialog.payload()["email"] == "david.oliveira@saocarlos.sp.gov.br"


def test_complete_password_reset_dialog_payload_appends_default_corporate_domain():
    _app()
    dialog = CompletePasswordResetDialog()
    dialog.email_input.setText("david.oliveira")
    dialog.recovery_input.setText("123456")
    dialog.password_input.setText(UPDATED_STRONG_PASSWORD)

    assert dialog.payload() == {
        "email": "david.oliveira@saocarlos.sp.gov.br",
        "recovery_value": "123456",
        "new_password": UPDATED_STRONG_PASSWORD,
    }


def test_access_dialog_inputs_expose_clear_buttons_and_environment_tooltips():
    _app()
    dialog = AccessDialog(
        settings=_MemorySettings(),
        access_service=_FakeAccessService(),
        admin_users_service=_FakeAdminUsersService(),
    )

    assert dialog.email_input.isClearButtonEnabled() is True
    assert dialog.password_input.isClearButtonEnabled() is True
    assert dialog.production_button.toolTip() != ""
    assert dialog.demo_button.toolTip() != ""

    reset_dialog = CompletePasswordResetDialog()
    assert reset_dialog.recovery_input.isClearButtonEnabled() is True
    assert reset_dialog.password_input.isClearButtonEnabled() is True


def test_access_dialog_password_toggle_changes_echo_mode():
    _app()
    dialog = AccessDialog(
        settings=_MemorySettings(),
        access_service=_FakeAccessService(),
        admin_users_service=_FakeAdminUsersService(),
    )

    assert dialog.password_input.echoMode() == QLineEdit.Password
    assert dialog.password_toggle_button.text() in {"Mostrar", "Ver"}

    dialog.password_toggle_button.click()

    assert dialog.password_input.echoMode() == QLineEdit.Normal
    assert dialog.password_toggle_button.text() == "Ocultar"


def test_password_recovery_and_bootstrap_dialogs_allow_password_visibility_toggle():
    _app()

    bootstrap_dialog = BootstrapFirstAdminDialog()
    assert bootstrap_dialog.password_input.echoMode() == QLineEdit.Password
    bootstrap_dialog.password_toggle_button.click()
    assert bootstrap_dialog.password_input.echoMode() == QLineEdit.Normal
    bootstrap_dialog.confirm_password_toggle_button.click()
    assert bootstrap_dialog.confirm_password_input.echoMode() == QLineEdit.Normal

    reset_dialog = CompletePasswordResetDialog()
    assert reset_dialog.password_input.echoMode() == QLineEdit.Password
    reset_dialog.password_toggle_button.click()
    assert reset_dialog.password_input.echoMode() == QLineEdit.Normal
    reset_dialog.confirm_password_toggle_button.click()
    assert reset_dialog.confirm_password_input.echoMode() == QLineEdit.Normal


def test_access_dialog_requests_and_completes_password_reset(monkeypatch):
    _app()

    class _FakeResetDialog:
        def __init__(self, parent=None):
            self.email_input = type("Field", (), {"setText": lambda self, text: None})()

        def exec(self):
            return 1

        def payload(self):
            return {
                "email": "admin@saocarlos.sp.gov.br",
            }

    class _FakeCompleteDialog:
        def __init__(self, parent=None):
            self.email_input = type("Field", (), {"setText": lambda self, text: None})()

        def exec(self):
            return 1

        def payload(self):
            return {
                "email": "admin@saocarlos.sp.gov.br",
                "recovery_value": "123456",
                "new_password": UPDATED_STRONG_PASSWORD,
            }

    messages = []

    def fake_information(_parent, title, message):
        messages.append((title, message))
        return 0

    monkeypatch.setattr(access_dialog_module, "RequestPasswordResetDialog", _FakeResetDialog)
    monkeypatch.setattr(access_dialog_module, "CompletePasswordResetDialog", _FakeCompleteDialog)
    monkeypatch.setattr(access_dialog_module.QMessageBox, "information", fake_information)

    access_service = _FakeAccessService()
    dialog = AccessDialog(
        settings=_MemorySettings(),
        access_service=access_service,
        admin_users_service=_FakeAdminUsersService(),
    )

    dialog._handle_password_reset_request()

    assert access_service.reset_requests == ["admin@saocarlos.sp.gov.br"]
    assert access_service.reset_completions == [
        {
            "email": "admin@saocarlos.sp.gov.br",
            "recovery_value": "123456",
            "new_password": UPDATED_STRONG_PASSWORD,
        }
    ]
    assert messages == [
        ("Recuperar senha", "email enviado"),
        ("Recuperar senha", "senha atualizada"),
    ]


def test_change_password_dialog_collects_current_and_new_passwords():
    _app()
    dialog = ChangePasswordDialog(account_email="admin@saocarlos.sp.gov.br")
    dialog.current_password_input.setText(CURRENT_STRONG_PASSWORD)
    dialog.new_password_input.setText(UPDATED_STRONG_PASSWORD)
    dialog.confirm_password_input.setText(UPDATED_STRONG_PASSWORD)

    assert dialog.payload() == {
        "current_password": CURRENT_STRONG_PASSWORD,
        "new_password": UPDATED_STRONG_PASSWORD,
    }


def test_change_password_dialog_rejects_weak_password(monkeypatch):
    _app()
    warnings = []
    monkeypatch.setattr(
        access_dialog_module.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)) or 0,
    )
    dialog = ChangePasswordDialog(account_email="admin@saocarlos.sp.gov.br")
    dialog.current_password_input.setText(CURRENT_STRONG_PASSWORD)
    dialog.new_password_input.setText("fraca123456!")
    dialog.confirm_password_input.setText("fraca123456!")

    dialog._submit()

    assert warnings == [
        ("Alterar senha", "A senha precisa ter uma letra maiuscula."),
    ]


def test_change_password_dialog_hides_current_password_controls_on_first_login():
    _app()
    dialog = ChangePasswordDialog(
        account_email="david.william@saocarlos.sp.gov.br",
        require_current_password=False,
    )

    assert dialog.current_password_input.isHidden() is True
    assert dialog.current_password_toggle_button is None


def test_access_dialog_forces_password_change_on_first_login(monkeypatch):
    _app()

    class _FakeChangePasswordDialog:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return 1

        def payload(self):
            return {"current_password": "", "new_password": UPDATED_STRONG_PASSWORD}

    messages = []
    monkeypatch.setattr(access_dialog_module, "ChangePasswordDialog", _FakeChangePasswordDialog)
    monkeypatch.setattr(
        access_dialog_module.QMessageBox,
        "information",
        lambda _parent, title, message: messages.append((title, message)) or 0,
    )

    access_service = _FakeAccessService(must_change_password=True)
    dialog = AccessDialog(
        settings=_MemorySettings(),
        access_service=access_service,
        admin_users_service=_FakeAdminUsersService(),
    )
    dialog.email_input.setText("admin")
    dialog.password_input.setText(STRONG_PASSWORD)

    dialog._handle_production_login()

    assert dialog.access_session is not None
    assert dialog.access_session.must_change_password is False
    assert access_service.password_changes == [
        {
            "access_session": access_service._session,
            "current_password": STRONG_PASSWORD,
            "new_password": UPDATED_STRONG_PASSWORD,
        }
    ]
    assert messages == [
        ("Primeiro acesso", "Senha pessoal definida com sucesso. O acesso à produção foi concluído."),
    ]


def test_access_dialog_blocks_entry_when_first_login_password_change_is_cancelled(monkeypatch):
    _app()

    class _FakeChangePasswordDialog:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def exec(self):
            return 0

    monkeypatch.setattr(access_dialog_module, "ChangePasswordDialog", _FakeChangePasswordDialog)

    access_service = _FakeAccessService(must_change_password=True)
    dialog = AccessDialog(
        settings=_MemorySettings(),
        access_service=access_service,
        admin_users_service=_FakeAdminUsersService(),
    )
    dialog.email_input.setText("admin")
    dialog.password_input.setText(STRONG_PASSWORD)

    dialog._handle_production_login()

    assert dialog.access_session is None
    assert access_service.password_changes == []
    assert access_service.sign_out_calls == [access_service._session]


def test_access_dialog_routes_login_errors_only_to_access_status_panel(monkeypatch):
    _app()

    class _RejectingAccessService(_FakeAccessService):
        def sign_in_production(self, *, email, password):
            raise access_dialog_module.AccessAuthError(
                "A senha foi atualizada, mas não foi possível concluir a liberação do primeiro acesso."
            )

    warnings = []
    monkeypatch.setattr(
        access_dialog_module.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)) or 0,
    )

    dialog = AccessDialog(
        settings=_MemorySettings(),
        access_service=_RejectingAccessService(),
        admin_users_service=_FakeAdminUsersService(),
    )
    dialog.email_input.setText("admin")
    dialog.password_input.setText(STRONG_PASSWORD)

    dialog._handle_production_login()

    assert dialog.production_status.text() == ""
    assert dialog.production_status.isVisible() is False
    assert dialog.status_title.text() == "Erro de acesso"
    assert "não foi possível concluir" in dialog.status_label.text().lower()
    assert dialog.status_panel.property("state") == "error"
    assert dialog.status_badges.isVisible() is False
    assert warnings == [
        ("Produção", "A senha foi atualizada, mas não foi possível concluir a liberação do primeiro acesso."),
    ]
