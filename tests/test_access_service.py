from pathlib import Path
from types import SimpleNamespace

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

    def sign_in_with_password(self, _payload):
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


def test_resolve_production_access_profile_uses_default_project():
    profile = resolve_production_access_profile()

    assert profile.environment == AccessEnvironment.PRODUCTION
    assert profile.url == "https://yonvcnnkewzoqwnnmcdx.supabase.co"
    assert profile.publishable_key.startswith("sb_publishable_")
    assert profile.allow_password is True


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


def test_sign_in_production_preserves_authorized_profile_role():
    sync_result = SupabaseWorkspaceSyncResult(
        local_db_path="C:/tmp/producao.db",
        session_path=DEFAULT_SINGLETON_SESSION_PATH,
        workbook_name="Base oficial",
        workbook_path="session://banco-local",
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

    with pytest.raises(AccessAuthError, match="nao foi liberado"):
        service.sign_in_production(
            email="analista@prefeitura.sp.gov.br",
            password="senha-segura",
        )

    assert fake_client.auth.signed_out is True


def test_create_authenticated_client_restores_session_tokens():
    service = SupabaseAccessService(
        production_profile=SupabaseAccessProfile(
            environment=AccessEnvironment.PRODUCTION,
            label="Producao",
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
    assert restored == {
        "access_token": "token",
        "refresh_token": "refresh-token",
    }


def test_enter_demo_falls_back_to_local_seed_and_creates_fake_database(tmp_path):
    demo_db = tmp_path / "demo.db"
    service = SupabaseAccessService(
        demo_profile=SupabaseAccessProfile(
            environment=AccessEnvironment.DEMO,
            label="Demonstracao",
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
