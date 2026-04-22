from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.models.compensacao import Compensacao
from app.services.audit_service_support import serialize_record, serialize_records_sample
from app.utils.logger import get_logger


logger = get_logger("Supabase.CompensacoesRPC")


@dataclass(frozen=True)
class SupabaseCompensacoesRpcResult:
    operation: str
    workbook_path: str
    uid: str = ""
    record_id: int = 0
    excel_row: int = 0
    updated_at: str = ""
    record_count: int = 0
    plantio_count: int = 0
    imported_count: int = 0
    audit_event_id: str = ""


class SupabaseCompensacoesRpcError(RuntimeError):
    pass


class SupabaseCompensacoesConflictError(SupabaseCompensacoesRpcError):
    pass


class SupabaseCompensacoesRpcService:
    SAVE_FUNCTION = "rpc_save_compensacao_record"
    DELETE_FUNCTION = "rpc_delete_compensacao_record"
    IMPORT_FUNCTION = "rpc_replace_compensacoes_snapshot"

    def __init__(self) -> None:
        self._legacy_save_signature_required: bool = False
        self._legacy_delete_signature_required: bool = False

    def save_record(
        self,
        client: Any,
        *,
        workbook_path: str,
        record: Compensacao,
        action: str,
        summary: str,
        backup_path: str = "",
        expected_updated_at: str = "",
        metadata: Mapping[str, object] | None = None,
        before: Mapping[str, object] | None = None,
        after: Mapping[str, object] | None = None,
    ) -> SupabaseCompensacoesRpcResult:
        params = {
            "p_workbook_path": str(workbook_path or "").strip(),
            "p_record": serialize_record(record),
            "p_action": str(action or "").strip(),
            "p_summary": str(summary or "").strip(),
            "p_backup_path": str(backup_path or "").strip(),
            "p_expected_updated_at": str(expected_updated_at or "").strip(),
            "p_metadata": self._json_object(metadata),
            "p_before": self._json_object(before) if before is not None else None,
            "p_after": self._json_object(after) if after is not None else serialize_record(record),
        }
        payload = self._execute_rpc_with_conflict_guard_compatibility(
            client,
            self.SAVE_FUNCTION,
            params,
            compatibility_attr="_legacy_save_signature_required",
        )
        return self._build_result("save", payload)

    def delete_record(
        self,
        client: Any,
        *,
        workbook_path: str,
        uid: str,
        action: str,
        summary: str,
        backup_path: str = "",
        expected_updated_at: str = "",
        metadata: Mapping[str, object] | None = None,
        before: Mapping[str, object] | None = None,
    ) -> SupabaseCompensacoesRpcResult:
        params = {
            "p_workbook_path": str(workbook_path or "").strip(),
            "p_uid": str(uid or "").strip(),
            "p_action": str(action or "").strip(),
            "p_summary": str(summary or "").strip(),
            "p_backup_path": str(backup_path or "").strip(),
            "p_expected_updated_at": str(expected_updated_at or "").strip(),
            "p_metadata": self._json_object(metadata),
            "p_before": self._json_object(before) if before is not None else None,
        }
        payload = self._execute_rpc_with_conflict_guard_compatibility(
            client,
            self.DELETE_FUNCTION,
            params,
            compatibility_attr="_legacy_delete_signature_required",
        )
        return self._build_result("delete", payload)

    def replace_records(
        self,
        client: Any,
        *,
        workbook_path: str,
        records: Sequence[Compensacao],
        action: str,
        summary: str,
        backup_path: str = "",
        metadata: Mapping[str, object] | None = None,
        before: Mapping[str, object] | None = None,
        after: Mapping[str, object] | None = None,
    ) -> SupabaseCompensacoesRpcResult:
        serialized_records = [serialize_record(record) for record in records]
        payload = self._execute_rpc(
            client,
            self.IMPORT_FUNCTION,
            {
                "p_workbook_path": str(workbook_path or "").strip(),
                "p_records": serialized_records,
                "p_action": str(action or "").strip(),
                "p_summary": str(summary or "").strip(),
                "p_backup_path": str(backup_path or "").strip(),
                "p_metadata": self._json_object(metadata),
                "p_before": self._json_object(before) if before is not None else None,
                "p_after": self._json_object(after)
                if after is not None
                else {
                    "imported_count": len(serialized_records),
                    "sample_records": serialize_records_sample(records),
                },
            },
        )
        return self._build_result("replace", payload)

    @staticmethod
    def _json_object(mapping: Mapping[str, object] | None) -> dict[str, object]:
        return dict(mapping or {})

    def _execute_rpc(
        self,
        client: Any,
        function_name: str,
        params: Mapping[str, object],
    ) -> dict[str, object]:
        if client is None:
            raise SupabaseCompensacoesRpcError("Cliente Supabase ausente para executar a mutacao remota.")
        try:
            response = client.rpc(function_name, params=dict(params)).execute()
        except Exception as exc:
            raise self._map_rpc_exception(function_name, exc) from exc

        payload = getattr(response, "data", None)
        if not isinstance(payload, dict):
            raise SupabaseCompensacoesRpcError(
                f"A funcao remota '{function_name}' retornou um payload invalido."
            )
        return dict(payload)

    def _execute_rpc_with_conflict_guard_compatibility(
        self,
        client: Any,
        function_name: str,
        params: Mapping[str, object],
        *,
        compatibility_attr: str,
    ) -> dict[str, object]:
        normalized_params = dict(params)
        if getattr(self, compatibility_attr, False):
            normalized_params = self._legacy_conflict_guard_params(normalized_params)
            return self._execute_rpc(client, function_name, normalized_params)

        try:
            return self._execute_rpc(client, function_name, normalized_params)
        except SupabaseCompensacoesConflictError:
            raise
        except SupabaseCompensacoesRpcError as exc:
            if not self._is_conflict_guard_signature_mismatch(function_name, normalized_params, exc):
                raise

            setattr(self, compatibility_attr, True)
            legacy_params = self._legacy_conflict_guard_params(normalized_params)
            logger.warning(
                "Funcao remota '%s' sem assinatura com controle de conflito; usando compatibilidade legada.",
                function_name,
            )
            return self._execute_rpc(client, function_name, legacy_params)

    @staticmethod
    def _legacy_conflict_guard_params(params: Mapping[str, object]) -> dict[str, object]:
        legacy_params = dict(params)
        legacy_params.pop("p_expected_updated_at", None)
        return legacy_params

    @staticmethod
    def _is_conflict_guard_signature_mismatch(
        function_name: str,
        params: Mapping[str, object],
        exc: SupabaseCompensacoesRpcError,
    ) -> bool:
        if "p_expected_updated_at" not in params:
            return False
        message = str(exc or "")
        normalized_message = message.lower()
        return (
            "pgrst202" in normalized_message
            and function_name.lower() in normalized_message
            and "p_expected_updated_at" in message
        )

    @staticmethod
    def _map_rpc_exception(function_name: str, exc: Exception) -> SupabaseCompensacoesRpcError:
        message = str(exc or "").strip()
        normalized_message = message.lower()
        if "compensacao_record_conflict:" in normalized_message:
            friendly_message = message.split(":", 1)[1].strip() if ":" in message else message
            return SupabaseCompensacoesConflictError(
                friendly_message or "Registro remoto desatualizado."
            )
        return SupabaseCompensacoesRpcError(
            f"Falha ao executar a funcao remota '{function_name}': {message}"
        )

    @staticmethod
    def _build_result(operation: str, payload: Mapping[str, object]) -> SupabaseCompensacoesRpcResult:
        return SupabaseCompensacoesRpcResult(
            operation=operation,
            workbook_path=str(payload.get("workbook_path", "") or ""),
            uid=str(payload.get("uid", "") or ""),
            record_id=int(payload.get("record_id") or 0),
            excel_row=int(payload.get("excel_row") or 0),
            updated_at=str(payload.get("updated_at", "") or ""),
            record_count=int(payload.get("record_count") or 0),
            plantio_count=int(payload.get("plantio_count") or 0),
            imported_count=int(payload.get("imported_count") or 0),
            audit_event_id=str(payload.get("audit_event_id", "") or ""),
        )
