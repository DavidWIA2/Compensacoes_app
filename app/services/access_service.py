from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from app.config import (
    DEFAULT_SUPABASE_PRODUCTION_PUBLISHABLE_KEY,
    DEFAULT_SUPABASE_PRODUCTION_URL,
    SUPABASE_DEMO_KEY_ENV_VAR,
    SUPABASE_DEMO_URL_ENV_VAR,
    SUPABASE_PRODUCTION_KEY_ENV_VAR,
    SUPABASE_PRODUCTION_URL_ENV_VAR,
    normalize_corporate_email,
)
from app.services.supabase_workspace_sync_service import (
    PRODUCTION_CACHE_SESSION_PATH,
    SupabaseWorkspaceSyncResult,
    SupabaseWorkspaceSyncService,
)
from app.services.supabase_client_loader import load_supabase_create_client
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
    def is_production(self) -> bool:
        return self.environment == AccessEnvironment.PRODUCTION

    @property
    def is_admin(self) -> bool:
        return str(self.app_role or "").strip().lower() == "admin"

    @property
    def role_display_name(self) -> str:
        normalized = str(self.app_role or "").strip().lower()
        if normalized == "admin":
            return "Administrador"
        if normalized == "viewer":
            return "Leitura"
        if normalized == "demo":
            return "Demonstração"
        if normalized:
            return "Edição"
        if self.environment == AccessEnvironment.DEMO:
            return "Demonstração"
        return "Local"

    @property
    def environment_display_name(self) -> str:
        if self.environment == AccessEnvironment.DEMO:
            return "Demonstração isolada"
        if self.environment == AccessEnvironment.PRODUCTION:
            return "Produção oficial"
        return "Contingência local"

    @property
    def environment_chip_text(self) -> str:
        if self.environment == AccessEnvironment.DEMO:
            return "Ambiente: Demonstração isolada"
        if self.environment == AccessEnvironment.PRODUCTION:
            return "Ambiente: Produção oficial"
        return "Ambiente: Contingência local"

    @property
    def environment_tooltip_text(self) -> str:
        if self.environment == AccessEnvironment.DEMO:
            if self.supabase_url:
                return "Modo de demonstração autenticado no Supabase, usando uma base fictícia isolada e segura para treinamento."
            return "Modo de demonstração com base fictícia local reiniciada a cada abertura, sem impacto na produção."
        if self.environment == AccessEnvironment.PRODUCTION:
            identity = self.user_email or self.user_id or "usuário autenticado"
            role_suffix = f" (perfil: {self.role_display_name})" if self.app_role else ""
            return (
                f"Acesso à produção oficial autenticado via Supabase para {identity}{role_suffix}, "
                "com cache local sincronizado da base protegida."
            )
        return "Sessão local de contingência, sem autenticação remota e sem impacto direto na base oficial."

    def settings_name(self, base_name: str) -> str:
        if self.environment == AccessEnvironment.DEMO:
            return f"{base_name}Demo"
        return base_name


class AccessAuthError(RuntimeError):
    pass


def resolve_production_access_profile() -> SupabaseAccessProfile:
    return SupabaseAccessProfile(
        environment=AccessEnvironment.PRODUCTION,
        label="Produção",
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
        label="Demonstração",
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
        self._supabase_dependency_checked = False
        self._supabase_dependency_error = ""

    def can_sign_in_production(self) -> bool:
        return self.production_profile.is_configured and self.production_profile.allow_password

    def production_sign_in_available(self) -> bool:
        return (
            self.production_profile.is_configured
            and self.production_profile.allow_password
            and self._has_supabase_dependency()
        )

    def production_sign_in_unavailability_reason(self) -> str:
        if not self.production_profile.is_configured or not self.production_profile.allow_password:
            return "A autenticação da produção oficial ainda não está configurada nesta instalação."
        if not self._has_supabase_dependency():
            return self._supabase_dependency_error or (
                "A dependência 'supabase' não está disponível nesta instalação."
            )
        return ""

    def can_open_demo(self) -> bool:
        return True

    def demo_entry_label(self) -> str:
        if self.demo_profile.is_configured and self.demo_profile.allow_anonymous:
            return "Demonstração online"
        return "Demonstração local"

    def sign_in_production(self, *, email: str, password: str) -> AppAccessSession:
        normalized_email = normalize_corporate_email(email)
        normalized_password = str(password or "")
        if not normalized_email or not normalized_password:
            raise AccessAuthError("Informe email e senha para entrar em produção.")
        if not self.production_sign_in_available():
            message = self.production_sign_in_unavailability_reason()
            if message:
                raise AccessAuthError(message)
            raise AccessAuthError("A autenticação de produção ainda não está configurada.")

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
                "Seu usuário existe, mas ainda não foi liberado para o ambiente de produção. "
                "Peça para um administrador ativar seu perfil no Supabase."
            )
        try:
            sync_result = self.production_sync_service.sync_authenticated_client(client)
        except Exception as exc:
            raise AccessAuthError(
                f"Autenticação concluída, mas a base oficial não pode ser sincronizada: {exc}"
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

    def can_request_password_reset(self) -> bool:
        return self.production_sign_in_available()

    def request_password_reset(self, *, email: str) -> str:
        normalized_email = normalize_corporate_email(email)
        if not normalized_email:
            raise AccessAuthError("Informe seu email corporativo para recuperar a senha.")
        if not self.can_request_password_reset():
            message = self.production_sign_in_unavailability_reason()
            if message:
                raise AccessAuthError(message)
            raise AccessAuthError("A recuperação de senha ainda não está configurada neste app.")

        try:
            client = self._create_client(self.production_profile)
            client.auth.sign_in_with_otp(
                {
                    "email": normalized_email,
                    "options": {
                        "should_create_user": False,
                    },
                }
            )
        except Exception as exc:
            raise AccessAuthError(f"Falha ao solicitar a recuperação de senha: {exc}") from exc

        return (
            "Se existir um usuário ativo com esse email, o Supabase enviará um link ou código "
            "de acesso para a caixa corporativa. Depois, cole esse link ou código no app para definir a nova senha."
        )

    def complete_password_reset(
        self,
        *,
        email: str,
        recovery_value: str,
        new_password: str,
    ) -> str:
        normalized_email = normalize_corporate_email(email)
        normalized_recovery_value = str(recovery_value or "").strip()
        normalized_password = str(new_password or "")
        if not normalized_email:
            raise AccessAuthError("Informe seu email corporativo para concluir a recuperação.")
        if not normalized_recovery_value:
            raise AccessAuthError("Cole o link ou o código recebido no email corporativo.")
        if len(normalized_password) < 8:
            raise AccessAuthError("A nova senha precisa ter pelo menos 8 caracteres.")
        if not self._has_supabase_dependency():
            message = self.production_sign_in_unavailability_reason()
            if message:
                raise AccessAuthError(message)
            raise AccessAuthError("A dependencia 'supabase' nao esta disponivel nesta instalacao.")

        try:
            client = self._create_client(self.production_profile)
            verification_payload = self._build_password_reset_verification_payload(
                normalized_email,
                normalized_recovery_value,
            )

            access_token = verification_payload.pop("_access_token", "")
            refresh_token = verification_payload.pop("_refresh_token", "")
            if access_token and refresh_token:
                client.auth.set_session(access_token, refresh_token)
            else:
                response = client.auth.verify_otp(verification_payload)
                remote_session = self._build_remote_session(
                    self.production_profile,
                    response,
                    auth_mode="password_recovery",
                )
                client.auth.set_session(remote_session.access_token, remote_session.refresh_token)

            profile = self._fetch_production_profile_from_session(client)
            if not bool(profile.get("is_active", False)):
                raise AccessAuthError(
                    "Seu usuário existe, mas ainda não foi liberado para o ambiente de produção. "
                    "Peça a um administrador para ativar seu perfil no Supabase."
                )
            client.auth.update_user({"password": normalized_password})
            self._best_effort_sign_out(client)
        except AccessAuthError:
            raise
        except Exception as exc:
            raise AccessAuthError(f"Falha ao concluir a redefinição da senha: {exc}") from exc

        return "Senha atualizada com sucesso. Você já pode voltar ao app e entrar com a nova senha."

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
                    label="Demonstração",
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
                    "Falha ao autenticar demonstração online. Voltando para a base local fictícia: %s",
                    exc,
                    exc_info=True,
                )

        demo_db_path = self._reset_demo_database()
        return AppAccessSession(
            environment=AccessEnvironment.DEMO,
            label="Demonstração",
            auth_mode="demo_local",
            is_anonymous=True,
            local_db_path=str(demo_db_path),
            local_session_path=PRODUCTION_CACHE_SESSION_PATH,
            app_role="demo",
        )

    def _create_client(self, profile: SupabaseAccessProfile):
        try:
            create_client = self._import_supabase_create_client()
        except ImportError as exc:
            raise AccessAuthError(
                "A dependência 'supabase' não está instalada. Rode 'pip install -r requirements.txt'."
            ) from exc

        return create_client(profile.url, profile.publishable_key)

    def _has_supabase_dependency(self) -> bool:
        if self._supabase_dependency_checked:
            return not bool(self._supabase_dependency_error)
        self._supabase_dependency_checked = True
        try:
            self._import_supabase_create_client()
        except ImportError:
            self._supabase_dependency_error = (
                "Esta instalação foi gerada sem o cliente oficial do Supabase. "
                "Use a demonstração local ou reinstale a release corrigida."
            )
            return False
        self._supabase_dependency_error = ""
        return True

    @staticmethod
    def _import_supabase_create_client():
        return load_supabase_create_client()

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
            raise AccessAuthError("A autenticação retornou sem usuário válido.")

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
            raise AccessAuthError("O ambiente atual não usa autenticação remota do Supabase.")

        if not profile.is_configured:
            raise AccessAuthError("O projeto Supabase deste ambiente ainda não está configurado.")

        access_token = str(getattr(access_session, "access_token", "") or "").strip()
        refresh_token = str(getattr(access_session, "refresh_token", "") or "").strip()
        if not access_token or not refresh_token:
            raise AccessAuthError("A sessão autenticada não possui tokens reutilizáveis do Supabase.")

        try:
            client = self._create_client(profile)
            client.auth.set_session(access_token, refresh_token)
        except Exception as exc:
            raise AccessAuthError(f"Não foi possível restaurar a sessão autenticada do Supabase: {exc}") from exc
        return client

    def refresh_production_cache(
        self,
        access_session: AppAccessSession,
        *,
        local_db_path: str | Path | None = None,
        session_path: str | None = None,
    ) -> SupabaseWorkspaceSyncResult:
        if access_session.environment != AccessEnvironment.PRODUCTION:
            raise AccessAuthError("A sincronização remota só está disponível no ambiente de produção.")

        client = self.create_authenticated_client(access_session)
        resolved_local_db_path = (
            Path(local_db_path)
            if local_db_path is not None
            else (Path(access_session.local_db_path) if str(access_session.local_db_path or "").strip() else None)
        )
        resolved_session_path = str(session_path or access_session.local_session_path or "").strip()
        if not resolved_session_path:
            resolved_session_path = PRODUCTION_CACHE_SESSION_PATH

        try:
            return self.production_sync_service.sync_authenticated_client(
                client,
                local_db_path=resolved_local_db_path,
                session_path=resolved_session_path,
            )
        except Exception as exc:
            raise AccessAuthError(f"Não foi possível sincronizar o cache local de produção: {exc}") from exc

    def sign_out_session(self, access_session: AppAccessSession | None) -> None:
        if not isinstance(access_session, AppAccessSession):
            return
        if access_session.environment not in {AccessEnvironment.PRODUCTION, AccessEnvironment.DEMO}:
            return

        access_token = str(getattr(access_session, "access_token", "") or "").strip()
        refresh_token = str(getattr(access_session, "refresh_token", "") or "").strip()
        if not access_token or not refresh_token:
            return

        try:
            client = self.create_authenticated_client(access_session)
        except Exception:
            logger.warning("Falha ao recriar a sessão Supabase durante o logout.", exc_info=True)
            return
        self._best_effort_sign_out(client)

    def _reset_demo_database(self) -> Path:
        factory = self._demo_dataset_factory
        if factory is None:
            from app.services.demo_dataset_service import reset_demo_database

            factory = reset_demo_database
        return Path(factory(self.demo_db_path))

    def _fetch_production_profile(self, client: Any, *, user_id: str) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise AccessAuthError("Sessão autenticada sem identificador de usuário válido.")
        try:
            response = (
                client.table("profiles")
                .select("id, email, display_name, role, is_active")
                .eq("id", normalized_user_id)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            raise AccessAuthError(f"Não foi possível consultar o perfil liberado do usuário: {exc}") from exc

        payload = getattr(response, "data", None)
        if not isinstance(payload, dict) or not payload:
            raise AccessAuthError(
                "Seu usuário ainda não possui um perfil configurado no ambiente de produção."
            )
        return dict(payload)

    def _fetch_production_profile_from_session(self, client: Any) -> dict[str, Any]:
        try:
            response = client.auth.get_user()
        except Exception as exc:
            raise AccessAuthError(f"Não foi possível validar a sessão de recuperação: {exc}") from exc

        user = getattr(response, "user", None)
        if user is None:
            data = getattr(response, "data", None)
            user = getattr(data, "user", None) if data is not None else None
        user_id = str(getattr(user, "id", "") or "")
        if not user_id:
            raise AccessAuthError("A sessão de recuperação não retornou um usuário válido.")
        return self._fetch_production_profile(client, user_id=user_id)

    @staticmethod
    def _build_password_reset_verification_payload(email: str, recovery_value: str) -> dict[str, str]:
        parsed = urlparse(recovery_value)
        query = parse_qs(parsed.query)
        fragment = parse_qs(parsed.fragment)

        access_token = str((fragment.get("access_token") or [""])[0] or "").strip()
        refresh_token = str((fragment.get("refresh_token") or [""])[0] or "").strip()
        if access_token and refresh_token:
            return {
                "_access_token": access_token,
                "_refresh_token": refresh_token,
            }

        token_hash = str((query.get("token_hash") or query.get("token") or [""])[0] or "").strip()
        if token_hash:
            recovery_type = str((query.get("type") or ["email"])[0] or "email").strip().lower()
            return {
                "token_hash": token_hash,
                "type": recovery_type or "email",
            }

        return {
            "email": email,
            "token": recovery_value,
            "type": "email",
        }

    @staticmethod
    def _best_effort_sign_out(client: Any) -> None:
        auth = getattr(client, "auth", None)
        sign_out = getattr(auth, "sign_out", None)
        if callable(sign_out):
            try:
                sign_out()
            except Exception:
                logger.warning("Falha ao encerrar sessão Supabase após login bloqueado.", exc_info=True)
