import pytest

from app.services.access_service import AccessEnvironment, AppAccessSession, SupabaseAccessProfile
from app.services.supabase_admin_users_service import (
    AdminUsersError,
    SupabaseAdminUsersService,
)


STRONG_PASSWORD = "SenhaSegura1!"
UPDATED_STRONG_PASSWORD = "SenhaNova123!"


class _FakeResponse:
    def __init__(self, *, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = b"{}"

    def json(self):
        return self._payload


@pytest.fixture
def production_profile():
    return SupabaseAccessProfile(
        environment=AccessEnvironment.PRODUCTION,
        label="Producao",
        url="https://yonvcnnkewzoqwnnmcdx.supabase.co",
        publishable_key="sb_publishable_test",
        allow_password=True,
    )


@pytest.fixture
def admin_session():
    return AppAccessSession(
        environment=AccessEnvironment.PRODUCTION,
        label="Producao",
        auth_mode="password",
        user_id="admin-1",
        user_email="admin@prefeitura.sp.gov.br",
        app_role="admin",
        access_token="access-token",
        refresh_token="refresh-token",
    )


def test_bootstrap_status_uses_public_function_without_auth(monkeypatch, production_profile):
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(payload={"allowed": True, "profile_count": 0, "message": "ok"})

    monkeypatch.setattr("app.services.supabase_admin_users_service.requests.request", fake_request)
    service = SupabaseAdminUsersService(production_profile=production_profile)

    status = service.bootstrap_status()

    assert status.allowed is True
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/functions/v1/bootstrap-first-admin")
    assert captured["headers"]["apikey"] == "sb_publishable_test"
    assert "Authorization" not in captured["headers"]


def test_list_users_requires_admin_session_and_authorization_header(monkeypatch, production_profile, admin_session):
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(
            payload={
                "users": [
                    {
                        "id": "user-1",
                        "email": "analista@prefeitura.sp.gov.br",
                        "display_name": "Analista",
                        "role": "editor",
                        "is_active": True,
                    }
                ]
            }
        )

    monkeypatch.setattr("app.services.supabase_admin_users_service.requests.request", fake_request)
    service = SupabaseAdminUsersService(production_profile=production_profile)

    users = service.list_users(admin_session)

    assert len(users) == 1
    assert users[0].email == "analista@prefeitura.sp.gov.br"
    assert captured["headers"]["Authorization"] == "Bearer access-token"
    assert captured["url"].endswith("/functions/v1/admin-users")


def test_service_blocks_non_admin_sessions_before_request(monkeypatch, production_profile):
    called = []
    monkeypatch.setattr(
        "app.services.supabase_admin_users_service.requests.request",
        lambda **kwargs: called.append(kwargs),
    )
    service = SupabaseAdminUsersService(production_profile=production_profile)

    with pytest.raises(AdminUsersError, match="Apenas administradores"):
        service.list_users(
            AppAccessSession(
                environment=AccessEnvironment.PRODUCTION,
                label="Producao",
                auth_mode="password",
                user_id="user-1",
                user_email="user@prefeitura.sp.gov.br",
                app_role="editor",
                access_token="token",
            )
        )

    assert called == []


def test_create_user_raises_backend_error_message(monkeypatch, production_profile, admin_session):
    monkeypatch.setattr(
        "app.services.supabase_admin_users_service.requests.request",
        lambda **kwargs: _FakeResponse(status_code=400, payload={"error": "email ja existe"}),
    )
    service = SupabaseAdminUsersService(production_profile=production_profile)

    with pytest.raises(AdminUsersError, match="email ja existe"):
        service.create_user(
            admin_session,
            email="dup@prefeitura.sp.gov.br",
            password=STRONG_PASSWORD,
            display_name="Duplicado",
            role="editor",
        )


def test_bootstrap_first_admin_appends_default_corporate_domain(monkeypatch, production_profile):
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(
            payload={
                "user": {
                    "id": "admin-1",
                    "email": "david.oliveira@saocarlos.sp.gov.br",
                    "display_name": "Administrador",
                    "role": "admin",
                    "is_active": True,
                }
            }
        )

    monkeypatch.setattr("app.services.supabase_admin_users_service.requests.request", fake_request)
    service = SupabaseAdminUsersService(production_profile=production_profile)

    user = service.bootstrap_first_admin(
        email="david.oliveira",
        password=STRONG_PASSWORD,
        display_name="Administrador",
    )

    assert user.email == "david.oliveira@saocarlos.sp.gov.br"
    assert captured["json"]["email"] == "david.oliveira@saocarlos.sp.gov.br"


def test_create_user_appends_default_corporate_domain(monkeypatch, production_profile, admin_session):
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(
            payload={
                "user": {
                    "id": "user-1",
                    "email": "novo.usuario@saocarlos.sp.gov.br",
                    "display_name": "Novo Usuario",
                    "role": "editor",
                    "is_active": True,
                }
            }
        )

    monkeypatch.setattr("app.services.supabase_admin_users_service.requests.request", fake_request)
    service = SupabaseAdminUsersService(production_profile=production_profile)

    user = service.create_user(
        admin_session,
        email="novo.usuario",
        password=STRONG_PASSWORD,
        display_name="Novo Usuario",
        role="editor",
    )

    assert user.email == "novo.usuario@saocarlos.sp.gov.br"
    assert captured["json"]["email"] == "novo.usuario@saocarlos.sp.gov.br"


def test_update_user_posts_update_action(monkeypatch, production_profile, admin_session):
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(
            payload={
                "user": {
                    "id": "user-1",
                    "email": "corrigido@saocarlos.sp.gov.br",
                    "display_name": "Nome Corrigido",
                    "role": "editor",
                    "is_active": True,
                }
            }
        )

    monkeypatch.setattr("app.services.supabase_admin_users_service.requests.request", fake_request)
    service = SupabaseAdminUsersService(production_profile=production_profile)

    user = service.update_user(
        admin_session,
        user_id="user-1",
        email="corrigido",
        display_name="Nome Corrigido",
    )

    assert user.email == "corrigido@saocarlos.sp.gov.br"
    assert user.display_name == "Nome Corrigido"
    assert captured["json"] == {
        "action": "update",
        "user_id": "user-1",
        "email": "corrigido@saocarlos.sp.gov.br",
        "display_name": "Nome Corrigido",
    }


def test_update_user_falls_back_to_rpc_when_edge_function_rejects_update(
    monkeypatch,
    production_profile,
    admin_session,
):
    rpc_calls = {}

    class _FakeAuth:
        def set_session(self, access_token, refresh_token):
            rpc_calls["session"] = (access_token, refresh_token)

    class _FakeRpcRequest:
        def execute(self):
            class _RpcResult:
                data = {
                    "id": "user-1",
                    "email": "corrigido@saocarlos.sp.gov.br",
                    "display_name": "Nome Corrigido",
                    "role": "editor",
                    "is_active": True,
                }

            return _RpcResult()

    class _FakeClient:
        def __init__(self):
            self.auth = _FakeAuth()

        def rpc(self, function_name, params=None):
            rpc_calls["function_name"] = function_name
            rpc_calls["params"] = params
            return _FakeRpcRequest()

    monkeypatch.setattr(
        "app.services.supabase_admin_users_service.requests.request",
        lambda **kwargs: _FakeResponse(status_code=400, payload={"error": "Acao administrativa invalida."}),
    )
    monkeypatch.setattr(
        "app.services.supabase_admin_users_service.load_supabase_create_client",
        lambda: (lambda url, key: _FakeClient()),
    )
    service = SupabaseAdminUsersService(production_profile=production_profile)

    user = service.update_user(
        admin_session,
        user_id="user-1",
        email="corrigido",
        display_name="Nome Corrigido",
    )

    assert user.email == "corrigido@saocarlos.sp.gov.br"
    assert rpc_calls["session"] == ("access-token", "refresh-token")
    assert rpc_calls["function_name"] == "rpc_admin_update_user"
    assert rpc_calls["params"] == {
        "p_user_id": "user-1",
        "p_email": "corrigido@saocarlos.sp.gov.br",
        "p_display_name": "Nome Corrigido",
    }


def test_reset_user_password_posts_reset_action(monkeypatch, production_profile, admin_session):
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(
            payload={
                "user": {
                    "id": "user-1",
                    "email": "novo.usuario@saocarlos.sp.gov.br",
                    "display_name": "Novo Usuario",
                    "role": "editor",
                    "is_active": True,
                }
            }
        )

    monkeypatch.setattr("app.services.supabase_admin_users_service.requests.request", fake_request)
    service = SupabaseAdminUsersService(production_profile=production_profile)

    user = service.reset_user_password(
        admin_session,
        user_id="user-1",
        password=UPDATED_STRONG_PASSWORD,
    )

    assert user.user_id == "user-1"
    assert captured["json"] == {
        "action": "reset_password",
        "user_id": "user-1",
        "password": UPDATED_STRONG_PASSWORD,
    }


def test_create_user_rejects_weak_password_before_request(monkeypatch, production_profile, admin_session):
    called = []
    monkeypatch.setattr(
        "app.services.supabase_admin_users_service.requests.request",
        lambda **kwargs: called.append(kwargs),
    )
    service = SupabaseAdminUsersService(production_profile=production_profile)

    with pytest.raises(AdminUsersError, match="letra maiuscula"):
        service.create_user(
            admin_session,
            email="novo.usuario",
            password="fraca123456!",
            display_name="Novo Usuario",
            role="editor",
        )

    assert called == []


def test_set_user_role_posts_role_change_action(monkeypatch, production_profile, admin_session):
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(
            payload={
                "user": {
                    "id": "user-1",
                    "email": "novo.usuario@saocarlos.sp.gov.br",
                    "display_name": "Novo Usuario",
                    "role": "viewer",
                    "is_active": True,
                }
            }
        )

    monkeypatch.setattr("app.services.supabase_admin_users_service.requests.request", fake_request)
    service = SupabaseAdminUsersService(production_profile=production_profile)

    user = service.set_user_role(
        admin_session,
        user_id="user-1",
        role="viewer",
    )

    assert user.role == "viewer"
    assert captured["json"] == {
        "action": "set_role",
        "user_id": "user-1",
        "role": "viewer",
    }
