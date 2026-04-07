from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from app.services.access_service import (
    AccessAuthError,
    AccessEnvironment,
    SupabaseAccessProfile,
    SupabaseAccessService,
    resolve_production_access_profile,
)
from app.services.demo_dataset_service import reset_demo_database
from app.services.sqlite_mirror_service import DEFAULT_SINGLETON_SESSION_PATH, SqliteMirrorService
from app.services.supabase_workspace_sync_service import SupabaseWorkspaceSyncResult
from app.services.tcra_sqlite_service import TcraSqliteService


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

    def table(self, name):
        assert name == "profiles"
        return _FakeProfileQuery(self._profile_data)


class _FakeRecoveryAuth:
    def __init__(self):
        self.otp_payload = None
        self.verify_payload = None
        self.update_payload = None
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

    def sign_out(self):
        self.signed_out = True


class _FakeRecoveryClient:
    def __init__(self, *, profile_data):
        self.auth = _FakeRecoveryAuth()
        self._profile_data = profile_data

    def table(self, name):
        assert name == "profiles"
        return _FakeProfileQuery(self._profile_data)


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
        sys,
        "path",
        [str(Path(__file__).resolve().parents[1]), str(fake_site_packages)] + sys.path,
    )
    sys.modules.pop("supabase", None)

    create_client = SupabaseAccessService._import_supabase_create_client()
    created = create_client("https://example.supabase.co", "sb_publishable_test")

    assert created == {
        "url": "https://example.supabase.co",
        "key": "sb_publishable_test",
    }


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
    fake_auth = _FakeRecoveryAuth()

    service._create_client = lambda profile: SimpleNamespace(auth=fake_auth)  # type: ignore[method-assign]

    message = service.request_password_reset(email="analista")

    assert "cole esse link ou código no app" in message.lower()
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
    fake_client = _FakeRecoveryClient(
        profile_data={
            "id": "user-123",
            "email": "analista@saocarlos.sp.gov.br",
            "display_name": "Analista",
            "role": "editor",
            "is_active": True,
        }
    )
    service._create_client = lambda profile: fake_client  # type: ignore[method-assign]

    message = service.complete_password_reset(
        email="analista",
        recovery_value="123456",
        new_password="senha-nova",
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
    assert fake_client.auth.update_payload == {"password": "senha-nova"}
    assert fake_client.auth.signed_out is True


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

    with pytest.raises(AccessAuthError, match="não foi liberado"):
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
