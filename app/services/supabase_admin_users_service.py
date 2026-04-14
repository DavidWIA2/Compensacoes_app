from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from app.config import normalize_corporate_email
from app.services.password_policy import password_validation_error
from app.services.supabase_client_loader import load_supabase_create_client
from app.services.access_service import (
    AccessEnvironment,
    AppAccessSession,
    SupabaseAccessProfile,
    resolve_production_access_profile,
)


class AdminUsersError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdminBootstrapStatus:
    allowed: bool
    profile_count: int = 0
    message: str = ""


@dataclass(frozen=True)
class AdminUserRecord:
    user_id: str
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: str = ""
    updated_at: str = ""

    @property
    def status_label(self) -> str:
        return "Ativo" if self.is_active else "Inativo"


class SupabaseAdminUsersService:
    BOOTSTRAP_FUNCTION = "bootstrap-first-admin"
    ADMIN_USERS_FUNCTION = "admin-users"
    UPDATE_RPC_FUNCTION = "rpc_admin_update_user"

    def __init__(
        self,
        *,
        production_profile: SupabaseAccessProfile | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.production_profile = production_profile or resolve_production_access_profile()
        self.timeout_seconds = float(timeout_seconds)

    def bootstrap_status(self) -> AdminBootstrapStatus:
        payload = self._request_json(
            "GET",
            function_name=self.BOOTSTRAP_FUNCTION,
            payload=None,
            access_session=None,
        )
        return AdminBootstrapStatus(
            allowed=bool(payload.get("allowed", False)),
            profile_count=int(payload.get("profile_count", 0) or 0),
            message=str(payload.get("message", "") or ""),
        )

    def bootstrap_first_admin(
        self,
        *,
        email: str,
        password: str,
        display_name: str = "",
    ) -> AdminUserRecord:
        normalized_email = normalize_corporate_email(email)
        self._ensure_valid_password(password)
        payload = self._request_json(
            "POST",
            function_name=self.BOOTSTRAP_FUNCTION,
            payload={
                "email": normalized_email,
                "password": str(password or ""),
                "display_name": str(display_name or "").strip(),
            },
            access_session=None,
        )
        return self._parse_user(payload.get("user") or {})

    def list_users(self, access_session: AppAccessSession) -> list[AdminUserRecord]:
        payload = self._request_json(
            "GET",
            function_name=self.ADMIN_USERS_FUNCTION,
            payload=None,
            access_session=access_session,
        )
        return [self._parse_user(item) for item in payload.get("users") or ()]

    def create_user(
        self,
        access_session: AppAccessSession,
        *,
        email: str,
        password: str,
        display_name: str = "",
        role: str = "editor",
        is_active: bool = True,
    ) -> AdminUserRecord:
        normalized_email = normalize_corporate_email(email)
        self._ensure_valid_password(password)
        payload = self._request_json(
            "POST",
            function_name=self.ADMIN_USERS_FUNCTION,
            payload={
                "action": "create",
                "email": normalized_email,
                "password": str(password or ""),
                "display_name": str(display_name or "").strip(),
                "role": str(role or "editor").strip().lower(),
                "is_active": bool(is_active),
            },
            access_session=access_session,
        )
        return self._parse_user(payload.get("user") or {})

    def update_user(
        self,
        access_session: AppAccessSession,
        *,
        user_id: str,
        email: str,
        display_name: str = "",
    ) -> AdminUserRecord:
        normalized_email = normalize_corporate_email(email)
        payload = {
            "action": "update",
            "user_id": str(user_id or "").strip(),
            "email": normalized_email,
            "display_name": str(display_name or "").strip(),
        }
        try:
            response = self._request_json(
                "POST",
                function_name=self.ADMIN_USERS_FUNCTION,
                payload=payload,
                access_session=access_session,
            )
        except AdminUsersError as exc:
            if not self._should_fallback_to_update_rpc(exc):
                raise
            return self._update_user_via_rpc(
                access_session,
                user_id=payload["user_id"],
                email=payload["email"],
                display_name=payload["display_name"],
            )
        return self._parse_user(response.get("user") or {})

    def set_user_active(
        self,
        access_session: AppAccessSession,
        *,
        user_id: str,
        is_active: bool,
    ) -> AdminUserRecord:
        payload = self._request_json(
            "POST",
            function_name=self.ADMIN_USERS_FUNCTION,
            payload={
                "action": "set_active",
                "user_id": str(user_id or "").strip(),
                "is_active": bool(is_active),
            },
            access_session=access_session,
        )
        return self._parse_user(payload.get("user") or {})

    def set_user_role(
        self,
        access_session: AppAccessSession,
        *,
        user_id: str,
        role: str,
    ) -> AdminUserRecord:
        payload = self._request_json(
            "POST",
            function_name=self.ADMIN_USERS_FUNCTION,
            payload={
                "action": "set_role",
                "user_id": str(user_id or "").strip(),
                "role": str(role or "editor").strip().lower(),
            },
            access_session=access_session,
        )
        return self._parse_user(payload.get("user") or {})

    def delete_user(
        self,
        access_session: AppAccessSession,
        *,
        user_id: str,
    ) -> None:
        self._request_json(
            "POST",
            function_name=self.ADMIN_USERS_FUNCTION,
            payload={
                "action": "delete",
                "user_id": str(user_id or "").strip(),
            },
            access_session=access_session,
        )

    def reset_user_password(
        self,
        access_session: AppAccessSession,
        *,
        user_id: str,
        password: str,
    ) -> AdminUserRecord:
        self._ensure_valid_password(password)
        payload = self._request_json(
            "POST",
            function_name=self.ADMIN_USERS_FUNCTION,
            payload={
                "action": "reset_password",
                "user_id": str(user_id or "").strip(),
                "password": str(password or ""),
            },
            access_session=access_session,
        )
        return self._parse_user(payload.get("user") or {})

    @staticmethod
    def _ensure_valid_password(password: str) -> None:
        message = password_validation_error(str(password or ""))
        if message:
            raise AdminUsersError(message)

    def _request_json(
        self,
        method: str,
        *,
        function_name: str,
        payload: dict[str, Any] | None,
        access_session: AppAccessSession | None,
    ) -> dict[str, Any]:
        url = self._build_function_url(function_name)
        headers = self._build_headers(access_session)
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise AdminUsersError(f"Falha ao comunicar com o backend administrativo: {exc}") from exc

        try:
            decoded = response.json() if response.content else {}
        except ValueError:
            decoded = {}

        if response.status_code >= 400:
            message = str(decoded.get("error") or decoded.get("message") or "").strip()
            if not message:
                message = f"Falha administrativa no Supabase (HTTP {response.status_code})."
            raise AdminUsersError(message)
        if not isinstance(decoded, dict):
            return {}
        return dict(decoded)

    def _build_function_url(self, function_name: str) -> str:
        base_url = str(self.production_profile.url or "").strip().rstrip("/")
        if not base_url:
            raise AdminUsersError("A URL da produção oficial do Supabase não está configurada.")
        return f"{base_url}/functions/v1/{function_name}"

    def _build_headers(self, access_session: AppAccessSession | None) -> dict[str, str]:
        publishable_key = str(self.production_profile.publishable_key or "").strip()
        if not publishable_key:
            raise AdminUsersError("A chave publishable da produção oficial não está configurada.")

        headers = {
            "apikey": publishable_key,
            "Content-Type": "application/json",
        }
        if access_session is not None:
            self._validate_admin_session(access_session)
            access_token = str(access_session.access_token or "").strip()
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    def _update_user_via_rpc(
        self,
        access_session: AppAccessSession,
        *,
        user_id: str,
        email: str,
        display_name: str,
    ) -> AdminUserRecord:
        client = self._create_authenticated_client(access_session)
        try:
            response = client.rpc(
                self.UPDATE_RPC_FUNCTION,
                params={
                    "p_user_id": str(user_id or "").strip(),
                    "p_email": str(email or "").strip(),
                    "p_display_name": str(display_name or "").strip(),
                },
            ).execute()
        except Exception as exc:
            raise AdminUsersError(f"Falha ao atualizar usuario na RPC administrativa: {exc}") from exc

        payload = getattr(response, "data", None)
        if not isinstance(payload, dict):
            raise AdminUsersError("A RPC administrativa de usuarios retornou um payload invalido.")
        return self._parse_user(payload)

    def _create_authenticated_client(self, access_session: AppAccessSession):
        self._validate_admin_session(access_session)
        try:
            create_client = load_supabase_create_client()
        except ImportError as exc:
            raise AdminUsersError(
                "A dependencia 'supabase' nao esta disponivel para executar a RPC administrativa."
            ) from exc
        try:
            client = create_client(self.production_profile.url, self.production_profile.publishable_key)
            client.auth.set_session(
                str(access_session.access_token or "").strip(),
                str(access_session.refresh_token or "").strip(),
            )
        except Exception as exc:
            raise AdminUsersError(
                f"Nao foi possivel restaurar a sessao autenticada para a RPC administrativa: {exc}"
            ) from exc
        return client

    @staticmethod
    def _should_fallback_to_update_rpc(exc: AdminUsersError) -> bool:
        normalized = str(exc or "").strip().lower()
        return (
            "acao administrativa invalida" in normalized
            or ("update" in normalized and "inv" in normalized)
        )

    @staticmethod
    def _validate_admin_session(access_session: AppAccessSession) -> None:
        if access_session.environment != AccessEnvironment.PRODUCTION:
            raise AdminUsersError("A administração de usuários só está disponível na Produção oficial.")
        if str(access_session.app_role or "").strip().lower() != "admin":
            raise AdminUsersError("Apenas administradores ativos podem gerenciar usuários.")
        access_token = str(access_session.access_token or "").strip()
        if not access_token:
            raise AdminUsersError("A sessão atual não possui token válido para o backend administrativo.")

    @staticmethod
    def _parse_user(payload: Any) -> AdminUserRecord:
        if not isinstance(payload, dict):
            raise AdminUsersError("O backend administrativo retornou um usuário inválido.")
        user_id = str(payload.get("id") or payload.get("user_id") or "").strip()
        if not user_id:
            raise AdminUsersError("O backend administrativo retornou um usuário sem identificador.")
        return AdminUserRecord(
            user_id=user_id,
            email=str(payload.get("email", "") or "").strip(),
            display_name=str(payload.get("display_name", "") or "").strip(),
            role=str(payload.get("role", "") or "editor").strip().lower(),
            is_active=bool(payload.get("is_active", False)),
            created_at=str(payload.get("created_at", "") or "").strip(),
            updated_at=str(payload.get("updated_at", "") or "").strip(),
        )
