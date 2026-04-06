from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

from app.config import (
    DEFAULT_SUPABASE_PRODUCTION_PUBLISHABLE_KEY,
    DEFAULT_SUPABASE_PRODUCTION_URL,
    SUPABASE_DEMO_KEY_ENV_VAR,
    SUPABASE_DEMO_URL_ENV_VAR,
    SUPABASE_PRODUCTION_KEY_ENV_VAR,
    SUPABASE_PRODUCTION_URL_ENV_VAR,
)
from app.services.supabase_workspace_sync_service import (
    PRODUCTION_CACHE_SESSION_PATH,
    SupabaseWorkspaceSyncService,
)
from app.utils.app_paths import resolve_data_path
from app.utils.logger import get_logger


logger = get_logger("Access")


class AccessEnvironment(StrEnum):
    LOCAL = "local"
    PRODUCTION = "production"
    DEMO = "demo"


@dataclass(frozen=True)
class SupabaseAccessProfile:
    environment: AccessEnvironment
    label: str
    url: str = ""
    publishable_key: str = ""
    allow_password: bool = False
    allow_anonymous: bool = False

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.publishable_key)


@dataclass(frozen=True)
class AppAccessSession:
    environment: AccessEnvironment
    label: str
    auth_mode: str
    user_id: str = ""
    user_email: str = ""
    is_anonymous: bool = False
    supabase_url: str = ""
    local_db_path: str = ""
    local_session_path: str = ""
    app_role: str = ""
    access_token: str = ""
    refresh_token: str = ""

    @classmethod
    def local_default(cls) -> "AppAccessSession":
        return cls(
            environment=AccessEnvironment.LOCAL,
            label="Local",
            auth_mode="local_default",
        )

    @property
    def is_demo(self) -> bool:
        return self.environment == AccessEnvironment.DEMO

    @property
    def environment_chip_text(self) -> str:
        if self.environment == AccessEnvironment.DEMO:
            return "Ambiente: Demonstracao"
        if self.environment == AccessEnvironment.PRODUCTION:
            return "Ambiente: Producao"
        return "Ambiente: Local"

    @property
    def environment_tooltip_text(self) -> str:
        if self.environment == AccessEnvironment.DEMO:
            if self.supabase_url:
                return "Modo demonstracao autenticado no Supabase e executando com base ficticia isolada."
            return "Modo demonstracao com base ficticia local reiniciada a cada abertura."
        if self.environment == AccessEnvironment.PRODUCTION:
            identity = self.user_email or self.user_id or "usuario autenticado"
            role_suffix = f" (perfil: {self.app_role})" if self.app_role else ""
            return (
                f"Acesso de producao autenticado via Supabase para {identity}{role_suffix}, "
                "com cache local sincronizado da base oficial."
            )
        return "Inicializacao local sem gateway de autenticacao."

    def settings_name(self, base_name: str) -> str:
        if self.environment == AccessEnvironment.DEMO:
            return f"{base_name}Demo"
        return base_name


class AccessAuthError(RuntimeError):
    pass


def resolve_production_access_profile() -> SupabaseAccessProfile:
    return SupabaseAccessProfile(
        environment=AccessEnvironment.PRODUCTION,
        label="Producao",
        url=str(os.getenv(SUPABASE_PRODUCTION_URL_ENV_VAR, DEFAULT_SUPABASE_PRODUCTION_URL) or "").strip(),
        publishable_key=str(
            os.getenv(
                SUPABASE_PRODUCTION_KEY_ENV_VAR,
                DEFAULT_SUPABASE_PRODUCTION_PUBLISHABLE_KEY,
            )
            or ""
        ).strip(),
        allow_password=True,
        allow_anonymous=False,
    )


def resolve_demo_access_profile() -> SupabaseAccessProfile:
    return SupabaseAccessProfile(
        environment=AccessEnvironment.DEMO,
        label="Demonstracao",
        url=str(os.getenv(SUPABASE_DEMO_URL_ENV_VAR, "") or "").strip(),
        publishable_key=str(os.getenv(SUPABASE_DEMO_KEY_ENV_VAR, "") or "").strip(),
        allow_password=False,
        allow_anonymous=True,
    )


class SupabaseAccessService:
    def __init__(
        self,
        *,
        production_profile: SupabaseAccessProfile | None = None,
        demo_profile: SupabaseAccessProfile | None = None,
        demo_db_path: str | Path | None = None,
        demo_dataset_factory: Callable[[str | Path | None], Path] | None = None,
        production_sync_service: SupabaseWorkspaceSyncService | None = None,
    ):
        self.production_profile = production_profile or resolve_production_access_profile()
        self.demo_profile = demo_profile or resolve_demo_access_profile()
        self.demo_db_path = Path(demo_db_path) if demo_db_path else resolve_data_path(
            "state",
            "demo",
            "compensacoes-demo.db",
        )
        self._demo_dataset_factory = demo_dataset_factory
        self.production_sync_service = production_sync_service or SupabaseWorkspaceSyncService()

    def can_sign_in_production(self) -> bool:
        return self.production_profile.is_configured and self.production_profile.allow_password

    def can_open_demo(self) -> bool:
        return True

    def demo_entry_label(self) -> str:
        if self.demo_profile.is_configured and self.demo_profile.allow_anonymous:
            return "Demonstracao online"
        return "Demonstracao local"

    def sign_in_production(self, *, email: str, password: str) -> AppAccessSession:
        normalized_email = str(email or "").strip()
        normalized_password = str(password or "")
        if not normalized_email or not normalized_password:
            raise AccessAuthError("Informe email e senha para entrar em producao.")
        if not self.can_sign_in_production():
            raise AccessAuthError("A autenticacao de producao ainda nao esta configurada.")

        try:
            client = self._create_client(self.production_profile)
            response = client.auth.sign_in_with_password(
                {
                    "email": normalized_email,
                    "password": normalized_password,
                }
            )
        except Exception as exc:
            raise AccessAuthError(f"Falha ao autenticar no Supabase: {exc}") from exc

        remote_session = self._build_remote_session(
            self.production_profile,
            response,
            auth_mode="password",
        )
        try:
            profile = self._fetch_production_profile(client, user_id=remote_session.user_id)
        except AccessAuthError:
            self._best_effort_sign_out(client)
            raise
        if not bool(profile.get("is_active", False)):
            self._best_effort_sign_out(client)
            raise AccessAuthError(
                "Seu usuario existe, mas ainda nao foi liberado para o ambiente de producao. "
                "Peça para um administrador ativar seu perfil no Supabase."
            )
        try:
            sync_result = self.production_sync_service.sync_authenticated_client(client)
        except Exception as exc:
            raise AccessAuthError(
                f"Autenticacao concluida, mas a base oficial nao pode ser sincronizada: {exc}"
            ) from exc
        return AppAccessSession(
            environment=remote_session.environment,
            label=remote_session.label,
            auth_mode=remote_session.auth_mode,
            user_id=remote_session.user_id,
            user_email=remote_session.user_email,
            is_anonymous=remote_session.is_anonymous,
            supabase_url=remote_session.supabase_url,
            local_db_path=sync_result.local_db_path,
            local_session_path=sync_result.session_path,
            app_role=str(profile.get("role", "") or ""),
            access_token=remote_session.access_token,
            refresh_token=remote_session.refresh_token,
        )

    def enter_demo(self) -> AppAccessSession:
        if self.demo_profile.is_configured and self.demo_profile.allow_anonymous:
            try:
                client = self._create_client(self.demo_profile)
                response = client.auth.sign_in_anonymously()
                remote_session = self._build_remote_session(
                    self.demo_profile,
                    response,
                    auth_mode="anonymous",
                )
                demo_db_path = self._reset_demo_database()
                return AppAccessSession(
                    environment=AccessEnvironment.DEMO,
                    label="Demonstracao",
                    auth_mode=remote_session.auth_mode,
                    user_id=remote_session.user_id,
                    user_email=remote_session.user_email,
                    is_anonymous=True,
                    supabase_url=remote_session.supabase_url,
                    local_db_path=str(demo_db_path),
                    local_session_path=PRODUCTION_CACHE_SESSION_PATH,
                    app_role="demo",
                    access_token=remote_session.access_token,
                    refresh_token=remote_session.refresh_token,
                )
            except Exception as exc:
                logger.warning(
                    "Falha ao autenticar demonstracao online. Voltando para a base local ficticia: %s",
                    exc,
                    exc_info=True,
                )

        demo_db_path = self._reset_demo_database()
        return AppAccessSession(
            environment=AccessEnvironment.DEMO,
            label="Demonstracao",
            auth_mode="demo_local",
            is_anonymous=True,
            local_db_path=str(demo_db_path),
            local_session_path=PRODUCTION_CACHE_SESSION_PATH,
            app_role="demo",
        )

    def _create_client(self, profile: SupabaseAccessProfile):
        try:
            from supabase import create_client
        except ImportError as exc:
            raise AccessAuthError(
                "A dependencia 'supabase' nao esta instalada. Rode 'pip install -r requirements.txt'."
            ) from exc

        return create_client(profile.url, profile.publishable_key)

    @staticmethod
    def _build_remote_session(
        profile: SupabaseAccessProfile,
        response: Any,
        *,
        auth_mode: str,
    ) -> AppAccessSession:
        session = getattr(response, "session", None)
        user = getattr(response, "user", None) or getattr(session, "user", None)
        user_id = str(getattr(user, "id", "") or "")
        user_email = str(getattr(user, "email", "") or "")
        is_anonymous = bool(getattr(user, "is_anonymous", False) or auth_mode == "anonymous")
        if not user_id:
            raise AccessAuthError("A autenticacao retornou sem usuario valido.")

        return AppAccessSession(
            environment=profile.environment,
            label=profile.label,
            auth_mode=auth_mode,
            user_id=user_id,
            user_email=user_email,
            is_anonymous=is_anonymous,
            supabase_url=profile.url,
            access_token=str(getattr(session, "access_token", "") or ""),
            refresh_token=str(getattr(session, "refresh_token", "") or ""),
        )

    def create_authenticated_client(self, access_session: AppAccessSession):
        if access_session.environment == AccessEnvironment.PRODUCTION:
            profile = self.production_profile
        elif access_session.environment == AccessEnvironment.DEMO:
            profile = self.demo_profile
        else:
            raise AccessAuthError("O ambiente atual nao usa autenticacao remota do Supabase.")

        if not profile.is_configured:
            raise AccessAuthError("O projeto Supabase deste ambiente ainda nao esta configurado.")

        access_token = str(getattr(access_session, "access_token", "") or "").strip()
        refresh_token = str(getattr(access_session, "refresh_token", "") or "").strip()
        if not access_token or not refresh_token:
            raise AccessAuthError("A sessao autenticada nao possui tokens reutilizaveis do Supabase.")

        try:
            client = self._create_client(profile)
            client.auth.set_session(access_token, refresh_token)
        except Exception as exc:
            raise AccessAuthError(f"Nao foi possivel restaurar a sessao autenticada do Supabase: {exc}") from exc
        return client

    def _reset_demo_database(self) -> Path:
        factory = self._demo_dataset_factory
        if factory is None:
            from app.services.demo_dataset_service import reset_demo_database

            factory = reset_demo_database
        return Path(factory(self.demo_db_path))

    def _fetch_production_profile(self, client: Any, *, user_id: str) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise AccessAuthError("Sessao autenticada sem identificador de usuario valido.")
        try:
            response = (
                client.table("profiles")
                .select("id, email, display_name, role, is_active")
                .eq("id", normalized_user_id)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            raise AccessAuthError(f"Nao foi possivel consultar o perfil liberado do usuario: {exc}") from exc

        payload = getattr(response, "data", None)
        if not isinstance(payload, dict) or not payload:
            raise AccessAuthError(
                "Seu usuario ainda nao possui um perfil configurado no ambiente de producao."
            )
        return dict(payload)

    @staticmethod
    def _best_effort_sign_out(client: Any) -> None:
        auth = getattr(client, "auth", None)
        sign_out = getattr(auth, "sign_out", None)
        if callable(sign_out):
            try:
                sign_out()
            except Exception:
                logger.warning("Falha ao encerrar sessao Supabase apos login bloqueado.", exc_info=True)
