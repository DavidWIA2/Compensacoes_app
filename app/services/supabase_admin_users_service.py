from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from app.config import normalize_corporate_email
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
            raise AdminUsersError("A URL de producao do Supabase nao esta configurada.")
        return f"{base_url}/functions/v1/{function_name}"

    def _build_headers(self, access_session: AppAccessSession | None) -> dict[str, str]:
        publishable_key = str(self.production_profile.publishable_key or "").strip()
        if not publishable_key:
            raise AdminUsersError("A chave publishable de producao nao esta configurada.")

        headers = {
            "apikey": publishable_key,
            "Content-Type": "application/json",
        }
        if access_session is not None:
            self._validate_admin_session(access_session)
            access_token = str(access_session.access_token or "").strip()
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    @staticmethod
    def _validate_admin_session(access_session: AppAccessSession) -> None:
        if access_session.environment != AccessEnvironment.PRODUCTION:
            raise AdminUsersError("A administração de usuários só está disponível em Produção.")
        if str(access_session.app_role or "").strip().lower() != "admin":
            raise AdminUsersError("Apenas administradores podem gerenciar usuários.")
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
