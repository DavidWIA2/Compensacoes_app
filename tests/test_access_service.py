from pathlib import Path
from types import SimpleNamespace
import importlib
import sys

import pytest

from app.services.access_service import (
    AccessAuthError,
    AppAccessSession,
    AccessEnvironment,
    SupabaseAccessProfile,
    SupabaseAccessService,
    resolve_production_access_profile,
)
import app.services.supabase_client_loader as supabase_client_loader
from app.services.demo_dataset_service import reset_demo_database
from app.services.sqlite_mirror_service import DEFAULT_SINGLETON_SESSION_PATH, SqliteMirrorService
from app.services.supabase_workspace_sync_service import SupabaseWorkspaceSyncResult
from app.services.tcra_sqlite_service import TcraSqliteService


STRONG_PASSWORD = "SenhaSegura1!"
UPDATED_STRONG_PASSWORD = "SenhaNova123!"
CURRENT_STRONG_PASSWORD = "SenhaAtual123!"


class _FakeProfileQuery:
    def __init__(self, profile_data):
        self.profile_data = profile_data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return SimpleNamespace(data=self.profile_data)


class _FakeRpcQuery:
    def __init__(self, calls, name, params=None, response_data=True):
        self._calls = calls
        self._name = name
        self._params = params or {}
        self._response_data = response_data

    def execute(self):
        self._calls.append({"name": self._name, "params": self._params})
        return SimpleNamespace(data=self._response_data)


class _FakeAuth:
    def __init__(self, response):
        self._response = response
        self.signed_out = False
        self.last_payload = None

    def sign_in_with_password(self, payload):
        self.last_payload = payload
        return self._response

    def sign_out(self):
        self.signed_out = True


class _FakeProductionClient:
    def __init__(self, *, response, profile_data):
        self.auth = _FakeAuth(response)
        self._profile_data = profile_data
        self.rpc_calls = []

    def table(self, name):
        assert name == "profiles"
        return _FakeProfileQuery(self._profile_data)

    def rpc(self, name, params=None):
        return _FakeRpcQuery(self.rpc_calls, name, params)


class _FakeRecoveryAuth:
    def __init__(self):
        self.otp_payload = None
        self.verify_payload = None
        self.update_payload = None
        self.password_sign_in_payload = None
        self.session_calls = []
        self.signed_out = False

    def sign_in_with_otp(self, payload):
        self.otp_payload = payload
        return SimpleNamespace(user=None, session=None)

    def verify_otp(self, payload):
        self.verify_payload = payload
        return SimpleNamespace(
            user=SimpleNamespace(
                id="user-123",
                email="analista@saocarlos.sp.gov.br",
                is_anonymous=False,
            ),
            session=SimpleNamespace(
                access_token="reset-token",
                refresh_token="reset-refresh",
            ),
        )

    def set_session(self, access_token, refresh_token):
        self.session_calls.append(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
            }
        )

    def get_user(self):
        return SimpleNamespace(user=SimpleNamespace(id="user-123"))

    def update_user(self, payload):
        self.update_payload = payload
        return SimpleNamespace(user=SimpleNamespace(id="user-123"))

    def sign_in_with_password(self, payload):
        self.password_sign_in_payload = payload
        return SimpleNamespace(
            user=SimpleNamespace(
                id="user-123",
                email="analista@saocarlos.sp.gov.br",
                is_anonymous=False,
            ),
            session=SimpleNamespace(
                access_token="updated-token",
                refresh_token="updated-refresh",
            ),
        )

    def sign_out(self):
        self.signed_out = True


class _FakeRecoveryClient:
    def __init__(self, *, profile_data):
        self.auth = _FakeRecoveryAuth()
        self._profile_data = profile_data
        self.rpc_calls = []

    def table(self, name):
        assert name == "profiles"
        return _FakeProfileQuery(self._profile_data)

    def rpc(self, name, params=None):
        return _FakeRpcQuery(self.rpc_calls, name, params)


class _FakeAuthenticatedAuth:
    def __init__(self, *, response=None):
        self.update_payload = None
        self._response = response or SimpleNamespace(
            user=SimpleNamespace(id="user-123"),
            session=SimpleNamespace(
                access_token="updated-token",
                refresh_token="updated-refresh",
            ),
        )

    def update_user(self, payload):
        self.update_payload = payload
        return self._response


class _FakeAuthenticatedClient:
    def __init__(self, *, response=None):
        self.auth = _FakeAuthenticatedAuth(response=response)
        self.rpc_calls = []

    def rpc(self, name, params=None):
        return _FakeRpcQuery(self.rpc_calls, name, params)


def _mark_supabase_dependency_available(service: SupabaseAccessService) -> None:
    service._has_supabase_dependency = lambda: True  # type: ignore[method-assign]
    service._supabase_dependency_checked = True
    service._supabase_dependency_error = ""


def test_resolve_production_access_profile_uses_default_project():
    profile = resolve_production_access_profile()

    assert profile.environment == AccessEnvironment.PRODUCTION
    assert profile.url == "https://yonvcnnkewzoqwnnmcdx.supabase.co"
    assert profile.publishable_key.startswith("sb_publishable_")
    assert profile.allow_password is True


def test_import_supabase_create_client_ignores_local_repo_namespace(tmp_path, monkeypatch):
    fake_site_packages = tmp_path / "site-packages"
    fake_supabase = fake_site_packages / "supabase"
    fake_supabase.mkdir(parents=True)
    (fake_supabase / "__init__.py").write_text(
        "def create_client(url, key):\n"
        "    return {'url': url, 'key': key}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        supabase_client_loader,
        "_candidate_site_paths",
        lambda: [str(fake_site_packages)],
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: (_ for _ in ()).throw(ImportError(name)))
    sys.modules.pop("supabase", None)

    create_client = SupabaseAccessService._import_supabase_create_client()
    created = create_client("https://example.supabase.co", "sb_publishable_test")

    assert created == {
        "url": "https://example.supabase.co",
        "key": "sb_publishable_test",
    }


def test_import_supabase_create_client_supports_frozen_bundle(monkeypatch):
    fake_module = SimpleNamespace(
        create_client=lambda url, key: {
            "url": url,
            "key": key,
            "mode": "frozen",
        }
    )

    monkeypatch.setattr(supabase_client_loader.sys, "frozen", True, raising=False)
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_module if name == "supabase" else None)

    create_client = SupabaseAccessService._import_supabase_create_client()

    assert create_client("https://example.supabase.co", "sb_publishable_test") == {
        "url": "https://example.supabase.co",
        "key": "sb_publishable_test",
        "mode": "frozen",
    }


def test_production_sign_in_available_returns_false_when_supabase_dependency_is_missing(monkeypatch):
    service = SupabaseAccessService()

    monkeypatch.setattr(
        service,
        "_import_supabase_create_client",
        lambda: (_ for _ in ()).throw(ImportError("missing supabase")),
    )

    assert service.can_sign_in_production() is True
    assert service.production_sign_in_available() is False
    assert "cliente oficial do Supabase" in service.production_sign_in_unavailability_reason()


def test_sign_in_production_surfaces_dependency_message_when_supabase_is_missing(monkeypatch):
    service = SupabaseAccessService()

    monkeypatch.setattr(
        service,
        "_import_supabase_create_client",
        lambda: (_ for _ in ()).throw(ImportError("missing supabase")),
    )

    with pytest.raises(AccessAuthError, match="cliente oficial do Supabase"):
        service.sign_in_production(email="analista", password="senha-segura")


def test_request_password_reset_surfaces_dependency_message_when_supabase_is_missing(monkeypatch):
    service = SupabaseAccessService()

    monkeypatch.setattr(
        service,
        "_import_supabase_create_client",
        lambda: (_ for _ in ()).throw(ImportError("missing supabase")),
    )

    with pytest.raises(AccessAuthError, match="cliente oficial do Supabase"):
        service.request_password_reset(email="analista")


def test_sign_in_production_requires_email_and_password():
    service = SupabaseAccessService()

    with pytest.raises(AccessAuthError):
        service.sign_in_production(email="", password="")


def test_sign_in_production_builds_remote_session_from_supabase_response():
    sync_result = SupabaseWorkspaceSyncResult(
        local_db_path="C:/tmp/producao.db",
        session_path=DEFAULT_SINGLETON_SESSION_PATH,
        workbook_name="Base oficial",
        workbook_path="session://banco-local",
        synced_at="2026-04-07T12:00:00+00:00",
        record_count=329,
        plantio_count=4,
        audit_event_count=0,
        tcra_count=18,
        tcra_event_count=17,
    )
    service = SupabaseAccessService(
        production_sync_service=SimpleNamespace(
            sync_authenticated_client=lambda client: sync_result
        )
    )
    _mark_supabase_dependency_available(service)
    fake_response = SimpleNamespace(
        user=SimpleNamespace(
            id="user-123",
            email="analista@prefeitura.sp.gov.br",
            is_anonymous=False,
        ),
        session=SimpleNamespace(access_token="token"),
    )
    fake_client = _FakeProductionClient(
        response=fake_response,
        profile_data={
            "id": "user-123",
            "email": "analista@prefeitura.sp.gov.br",
            "display_name": "Analista",
            "role": "editor",
            "is_active": True,
        },
    )
    service._create_client = lambda profile: fake_client  # type: ignore[method-assign]

    session = service.sign_in_production(
        email="analista@prefeitura.sp.gov.br",
        password="senha-segura",
    )

    assert session.environment == AccessEnvironment.PRODUCTION
    assert session.user_id == "user-123"
    assert session.user_email == "analista@prefeitura.sp.gov.br"
    assert session.is_anonymous is False
    assert session.local_db_path == "C:/tmp/producao.db"
    assert session.local_session_path == DEFAULT_SINGLETON_SESSION_PATH
    assert session.app_role == "editor"
    assert session.access_token == "token"
    assert fake_client.auth.last_payload == {
        "email": "analista@prefeitura.sp.gov.br",
        "password": "senha-segura",
    }


def test_sign_in_production_marks_session_for_password_change_when_profile_requires_it():
    sync_result = SupabaseWorkspaceSyncResult(
        local_db_path="C:/tmp/producao.db",
        session_path=DEFAULT_SINGLETON_SESSION_PATH,
        workbook_name="Base oficial",
        workbook_path="session://banco-local",
        synced_at="2026-04-07T12:00:00+00:00",
        record_count=329,
        plantio_count=4,
        audit_event_count=0,
        tcra_count=18,
        tcra_event_count=17,
    )
    service = SupabaseAccessService(
        production_sync_service=SimpleNamespace(
            sync_authenticated_client=lambda client: sync_result
        )
    )
    _mark_supabase_dependency_available(service)
    fake_response = SimpleNamespace(
        user=SimpleNamespace(
            id="user-123",
            email="analista@saocarlos.sp.gov.br",
            is_anonymous=False,
        ),
        session=SimpleNamespace(access_token="token", refresh_token="refresh"),
    )
    fake_client = _FakeProductionClient(
        response=fake_response,
        profile_data={
            "id": "user-123",
            "email": "analista@saocarlos.sp.gov.br",
            "display_name": "Analista",
            "role": "editor",
            "is_active": True,
            "must_change_password": True,
        },
    )
    service._create_client = lambda profile: fake_client  # type: ignore[method-assign]

    session = service.sign_in_production(email="analista", password="senha-segura")

    assert session.must_change_password is True


def test_sign_in_production_accepts_only_corporate_local_part():
    sync_result = SupabaseWorkspaceSyncResult(
        local_db_path="C:/tmp/producao.db",
        session_path=DEFAULT_SINGLETON_SESSION_PATH,
        workbook_name="Base oficial",
        workbook_path="session://banco-local",
        synced_at="2026-04-07T12:00:00+00:00",
        record_count=329,
        plantio_count=4,
        audit_event_count=0,
        tcra_count=18,
        tcra_event_count=17,
    )
    service = SupabaseAccessService(
        production_sync_service=SimpleNamespace(
            sync_authenticated_client=lambda client: sync_result
        )
    )
    _mark_supabase_dependency_available(service)
    fake_response = SimpleNamespace(
        user=SimpleNamespace(
            id="user-123",
            email="analista@saocarlos.sp.gov.br",
            is_anonymous=False,
        ),
        session=SimpleNamespace(access_token="token"),
    )
    fake_client = _FakeProductionClient(
        response=fake_response,
        profile_data={
            "id": "user-123",
            "email": "analista@saocarlos.sp.gov.br",
            "display_name": "Analista",
            "role": "editor",
            "is_active": True,
        },
    )
    service._create_client = lambda profile: fake_client  # type: ignore[method-assign]

    session = service.sign_in_production(
        email="analista",
        password="senha-segura",
    )

    assert session.user_email == "analista@saocarlos.sp.gov.br"
    assert fake_client.auth.last_payload == {
        "email": "analista@saocarlos.sp.gov.br",
        "password": "senha-segura",
    }


def test_request_password_reset_requires_corporate_email():
    service = SupabaseAccessService()

    with pytest.raises(AccessAuthError, match="Informe seu email corporativo"):
        service.request_password_reset(email="")


def test_request_password_reset_appends_default_domain_and_requests_otp():
    service = SupabaseAccessService()
    _mark_supabase_dependency_available(service)
    fake_auth = _FakeRecoveryAuth()

    service._create_client = lambda profile: SimpleNamespace(auth=fake_auth)  # type: ignore[method-assign]

    message = service.request_password_reset(email="analista")

    lowered_message = message.lower()
    assert "cole esse link" in lowered_message
    assert "app" in lowered_message
    assert fake_auth.otp_payload == {
        "email": "analista@saocarlos.sp.gov.br",
        "options": {"should_create_user": False},
    }


def test_build_password_reset_verification_payload_accepts_magic_link_query():
    payload = SupabaseAccessService._build_password_reset_verification_payload(
        "analista@saocarlos.sp.gov.br",
        "https://example.com/reset?token=abc123&type=magiclink",
    )

    assert payload == {
        "token_hash": "abc123",
        "type": "magiclink",
    }


def test_build_password_reset_verification_payload_accepts_session_fragment():
    payload = SupabaseAccessService._build_password_reset_verification_payload(
        "analista@saocarlos.sp.gov.br",
        "myapp://reset#access_token=access-123&refresh_token=refresh-456",
    )

    assert payload == {
        "_access_token": "access-123",
        "_refresh_token": "refresh-456",
    }


def test_complete_password_reset_verifies_otp_updates_password_and_signs_out():
    service = SupabaseAccessService()
    _mark_supabase_dependency_available(service)
    fake_client = _FakeRecoveryClient(
        profile_data={
            "id": "user-123",
            "email": "analista@saocarlos.sp.gov.br",
            "display_name": "Analista",
            "role": "editor",
            "is_active": True,
            "must_change_password": True,
        }
    )
    service._create_client = lambda profile: fake_client  # type: ignore[method-assign]

    message = service.complete_password_reset(
        email="analista",
        recovery_value="123456",
        new_password=UPDATED_STRONG_PASSWORD,
    )

    assert "Senha atualizada com sucesso" in message
    assert fake_client.auth.verify_payload == {
        "email": "analista@saocarlos.sp.gov.br",
        "token": "123456",
        "type": "email",
    }
    assert fake_client.auth.session_calls == [
        {
            "access_token": "reset-token",
            "refresh_token": "reset-refresh",
        }
    ]
    assert fake_client.auth.update_payload == {"password": UPDATED_STRONG_PASSWORD}
    assert fake_client.auth.password_sign_in_payload == {
        "email": "analista@saocarlos.sp.gov.br",
        "password": UPDATED_STRONG_PASSWORD,
    }
    assert fake_client.rpc_calls == [
        {"name": "rpc_complete_password_change", "params": {}}
    ]
    assert fake_client.auth.signed_out is True


def test_change_password_verifies_current_password_updates_session_and_clears_rotation_flag():
    service = SupabaseAccessService()
    _mark_supabase_dependency_available(service)
    verification_client = _FakeProductionClient(
        response=SimpleNamespace(
            user=SimpleNamespace(
                id="user-123",
                email="analista@saocarlos.sp.gov.br",
                is_anonymous=False,
            ),
            session=SimpleNamespace(access_token="token", refresh_token="refresh"),
        ),
        profile_data={
            "id": "user-123",
            "email": "analista@saocarlos.sp.gov.br",
            "display_name": "Analista",
            "role": "editor",
            "is_active": True,
            "must_change_password": True,
        },
    )
    authenticated_client = _FakeAuthenticatedClient()
    created_clients = []

    def _create_client(profile):
        created_clients.append(profile.environment)
        return verification_client

    service._create_client = _create_client  # type: ignore[method-assign]
    service.create_authenticated_client = lambda access_session: authenticated_client  # type: ignore[method-assign]
    access_session = AppAccessSession(
        environment=AccessEnvironment.PRODUCTION,
        label="Produção",
        auth_mode="password",
        user_id="user-123",
        user_email="analista@saocarlos.sp.gov.br",
        app_role="editor",
        access_token="token",
        refresh_token="refresh",
        must_change_password=True,
    )

    updated_session = service.change_password(
        access_session=access_session,
        current_password=CURRENT_STRONG_PASSWORD,
        new_password=UPDATED_STRONG_PASSWORD,
    )

    assert created_clients == [AccessEnvironment.PRODUCTION]
    assert verification_client.auth.last_payload == {
        "email": "analista@saocarlos.sp.gov.br",
        "password": CURRENT_STRONG_PASSWORD,
    }
    assert verification_client.auth.signed_out is True
    assert authenticated_client.auth.update_payload == {
        "password": UPDATED_STRONG_PASSWORD
    }
    assert authenticated_client.rpc_calls == [
        {"name": "rpc_complete_password_change", "params": {}}
    ]
    assert updated_session.access_token == "updated-token"
    assert updated_session.refresh_token == "updated-refresh"
    assert updated_session.must_change_password is False


def test_change_password_rejects_weak_password_before_touching_supabase():
    service = SupabaseAccessService()
    access_session = AppAccessSession(
        environment=AccessEnvironment.PRODUCTION,
        label="Producao",
        auth_mode="password",
        user_id="user-123",
        user_email="analista@saocarlos.sp.gov.br",
        app_role="editor",
        access_token="token",
        refresh_token="refresh",
    )

    with pytest.raises(AccessAuthError, match="letra maiuscula"):
        service.change_password(
            access_session=access_session,
            current_password=CURRENT_STRONG_PASSWORD,
            new_password="fraca123456!",
        )


def test_sign_in_production_preserves_authorized_profile_role():
    sync_result = SupabaseWorkspaceSyncResult(
        local_db_path="C:/tmp/producao.db",
        session_path=DEFAULT_SINGLETON_SESSION_PATH,
        workbook_name="Base oficial",
        workbook_path="session://banco-local",
        synced_at="2026-04-07T12:00:00+00:00",
        record_count=329,
        plantio_count=4,
        audit_event_count=0,
        tcra_count=18,
        tcra_event_count=17,
    )
    service = SupabaseAccessService(
        production_sync_service=SimpleNamespace(
            sync_authenticated_client=lambda client: sync_result
        )
    )
    _mark_supabase_dependency_available(service)
    fake_response = SimpleNamespace(
        user=SimpleNamespace(
            id="user-123",
            email="analista@prefeitura.sp.gov.br",
            is_anonymous=False,
        ),
        session=SimpleNamespace(access_token="token", refresh_token="refresh-token"),
    )
    fake_client = _FakeProductionClient(
        response=fake_response,
        profile_data={
            "id": "user-123",
            "email": "analista@prefeitura.sp.gov.br",
            "display_name": "Analista",
            "role": "editor",
            "is_active": True,
        },
    )
    service._create_client = lambda profile: fake_client  # type: ignore[method-assign]

    session = service.sign_in_production(
        email="analista@prefeitura.sp.gov.br",
        password="senha-segura",
    )

    assert session.app_role == "editor"
    assert session.refresh_token == "refresh-token"
    assert fake_client.auth.signed_out is False


def test_sign_in_production_blocks_inactive_profile_and_signs_out():
    service = SupabaseAccessService(
        production_sync_service=SimpleNamespace(
            sync_authenticated_client=lambda client: None
        )
    )
    _mark_supabase_dependency_available(service)
    fake_response = SimpleNamespace(
        user=SimpleNamespace(
            id="user-123",
            email="analista@prefeitura.sp.gov.br",
            is_anonymous=False,
        ),
        session=SimpleNamespace(access_token="token", refresh_token="refresh-token"),
    )
    fake_client = _FakeProductionClient(
        response=fake_response,
        profile_data={
            "id": "user-123",
            "email": "analista@prefeitura.sp.gov.br",
            "display_name": "Analista",
            "role": "viewer",
            "is_active": False,
        },
    )
    service._create_client = lambda profile: fake_client  # type: ignore[method-assign]

    with pytest.raises(AccessAuthError, match="liberado"):
        service.sign_in_production(
            email="analista@prefeitura.sp.gov.br",
            password="senha-segura",
        )

    assert fake_client.auth.signed_out is True


def test_create_authenticated_client_restores_session_tokens():
    service = SupabaseAccessService(
        production_profile=SupabaseAccessProfile(
            environment=AccessEnvironment.PRODUCTION,
            label="Produção",
            url="https://yonvcnnkewzoqwnnmcdx.supabase.co",
            publishable_key="sb_publishable_key",
            allow_password=True,
        )
    )
    restored = {}
    fake_client = SimpleNamespace(
        auth=SimpleNamespace(
            set_session=lambda access_token, refresh_token: restored.update(
                {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                }
            )
        )
    )
    service._create_client = lambda profile: fake_client  # type: ignore[method-assign]

    client = service.create_authenticated_client(
        service._build_remote_session(
            service.production_profile,
            SimpleNamespace(
                user=SimpleNamespace(id="user-123", email="analista@prefeitura.sp.gov.br", is_anonymous=False),
                session=SimpleNamespace(access_token="token", refresh_token="refresh-token"),
            ),
            auth_mode="password",
        )
    )

    assert client is fake_client


def test_refresh_production_cache_reuses_authenticated_session_tokens():
    sync_result = SupabaseWorkspaceSyncResult(
        local_db_path="C:/tmp/producao.db",
        session_path=DEFAULT_SINGLETON_SESSION_PATH,
        workbook_name="Base oficial",
        workbook_path="session://banco-local",
        synced_at="2026-04-07T12:00:00+00:00",
        record_count=329,
        plantio_count=4,
        audit_event_count=0,
        tcra_count=18,
        tcra_event_count=17,
    )
    sync_calls = []
    service = SupabaseAccessService(
        production_sync_service=SimpleNamespace(
            sync_authenticated_client=lambda client, **kwargs: (
                sync_calls.append({"client": client, **kwargs}) or sync_result
            )
        )
    )
    restored = {}
    fake_client = SimpleNamespace(
        auth=SimpleNamespace(
            set_session=lambda access_token, refresh_token: restored.update(
                {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                }
            )
        )
    )
    service._create_client = lambda profile: fake_client  # type: ignore[method-assign]
    access_session = service._build_remote_session(
        service.production_profile,
        SimpleNamespace(
            user=SimpleNamespace(id="user-123", email="analista@prefeitura.sp.gov.br", is_anonymous=False),
            session=SimpleNamespace(access_token="token", refresh_token="refresh-token"),
        ),
        auth_mode="password",
    )

    result = service.refresh_production_cache(access_session)

    assert result is sync_result
    assert restored == {"access_token": "token", "refresh_token": "refresh-token"}
    assert len(sync_calls) == 1
    assert sync_calls[0]["session_path"] == DEFAULT_SINGLETON_SESSION_PATH
    assert restored == {
        "access_token": "token",
        "refresh_token": "refresh-token",
    }


def test_sign_out_session_reuses_authenticated_client_and_signs_out():
    service = SupabaseAccessService()
    signed_out = []
    fake_client = SimpleNamespace(auth=SimpleNamespace(sign_out=lambda: signed_out.append(True)))
    service.create_authenticated_client = lambda access_session: fake_client  # type: ignore[method-assign]
    access_session = AppAccessSession(
        environment=AccessEnvironment.PRODUCTION,
        label="Produção",
        auth_mode="password",
        access_token="token",
        refresh_token="refresh",
    )

    service.sign_out_session(access_session)

    assert signed_out == [True]


def test_sign_out_session_ignores_local_sessions():
    service = SupabaseAccessService()
    called = []
    service.create_authenticated_client = lambda access_session: called.append(access_session)  # type: ignore[method-assign]

    service.sign_out_session(AppAccessSession.local_default())

    assert called == []


def test_enter_demo_falls_back_to_local_seed_and_creates_fake_database(tmp_path):
    demo_db = tmp_path / "demo.db"
    service = SupabaseAccessService(
        demo_profile=SupabaseAccessProfile(
            environment=AccessEnvironment.DEMO,
            label="Demonstração",
        ),
        demo_db_path=demo_db,
    )

    session = service.enter_demo()

    sqlite_service = SqliteMirrorService(db_path=demo_db)
    tcra_service = TcraSqliteService(db_path=demo_db)
    summary = sqlite_service.get_workbook_snapshot_summary(DEFAULT_SINGLETON_SESSION_PATH)

    assert session.environment == AccessEnvironment.DEMO
    assert session.auth_mode == "demo_local"
    assert session.local_db_path == str(demo_db)
    assert session.local_session_path == DEFAULT_SINGLETON_SESSION_PATH
    assert summary.record_count == 6
    assert len(tcra_service.list_tcras()) == 3


def test_reset_demo_database_recreates_seed_from_scratch(tmp_path):
    demo_db = tmp_path / "seed-demo.db"

    first_path = reset_demo_database(demo_db)
    sqlite_service = SqliteMirrorService(db_path=first_path)
    first_records = sqlite_service.list_records_for_workbook(DEFAULT_SINGLETON_SESSION_PATH)

    assert len(first_records) == 6

    second_path = reset_demo_database(demo_db)
    sqlite_service = SqliteMirrorService(db_path=second_path)
    second_records = sqlite_service.list_records_for_workbook(DEFAULT_SINGLETON_SESSION_PATH)

    assert second_path == Path(demo_db)
    assert len(second_records) == 6
