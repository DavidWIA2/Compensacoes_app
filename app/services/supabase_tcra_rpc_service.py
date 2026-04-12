from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.utils.logger import get_logger


logger = get_logger("Supabase.TcraRPC")


@dataclass(frozen=True)
class SupabaseTcraRpcResult:
    operation: str
    uid: str = ""
    tcra_count: int = 0
    tcra_event_count: int = 0
    imported_count: int = 0
    audit_event_id: str = ""


class SupabaseTcraRpcError(RuntimeError):
    pass


class SupabaseTcraRpcService:
    SAVE_FUNCTION = "rpc_save_tcra_record"
    DELETE_FUNCTION = "rpc_delete_tcra_record"
    BULK_SAVE_FUNCTION = "rpc_save_tcra_records"
    IMPORT_FUNCTION = "rpc_replace_tcras_snapshot"

    def save_record(
        self,
        client: Any,
        *,
        record: Tcra,
        action: str,
        summary: str,
        workbook_path: str = "session://banco-local",
        metadata: Mapping[str, object] | None = None,
        before: Mapping[str, object] | None = None,
        after: Mapping[str, object] | None = None,
    ) -> SupabaseTcraRpcResult:
        payload = self._execute_rpc(
            client,
            self.SAVE_FUNCTION,
            {
                "p_record": serialize_tcra(record),
                "p_action": str(action or "").strip(),
                "p_summary": str(summary or "").strip(),
                "p_workbook_path": str(workbook_path or "session://banco-local").strip(),
                "p_metadata": self._json_object(metadata),
                "p_before": self._json_object(before) if before is not None else None,
                "p_after": self._json_object(after) if after is not None else serialize_tcra(record),
            },
        )
        return self._build_result("save", payload)

    def delete_record(
        self,
        client: Any,
        *,
        uid: str,
        action: str,
        summary: str,
        workbook_path: str = "session://banco-local",
        metadata: Mapping[str, object] | None = None,
        before: Mapping[str, object] | None = None,
    ) -> SupabaseTcraRpcResult:
        payload = self._execute_rpc(
            client,
            self.DELETE_FUNCTION,
            {
                "p_uid": str(uid or "").strip(),
                "p_action": str(action or "").strip(),
                "p_summary": str(summary or "").strip(),
                "p_workbook_path": str(workbook_path or "session://banco-local").strip(),
                "p_metadata": self._json_object(metadata),
                "p_before": self._json_object(before) if before is not None else None,
            },
        )
        return self._build_result("delete", payload)

    def save_records(
        self,
        client: Any,
        *,
        records: Sequence[Tcra],
        action: str,
        summary: str,
        workbook_path: str = "session://banco-local",
        metadata: Mapping[str, object] | None = None,
        before: object | None = None,
        after: object | None = None,
    ) -> SupabaseTcraRpcResult:
        serialized_records = [serialize_tcra(record) for record in records]
        payload = self._execute_rpc(
            client,
            self.BULK_SAVE_FUNCTION,
            {
                "p_records": serialized_records,
                "p_action": str(action or "").strip(),
                "p_summary": str(summary or "").strip(),
                "p_workbook_path": str(workbook_path or "session://banco-local").strip(),
                "p_metadata": self._json_object(metadata),
                "p_before": before,
                "p_after": after
                if after is not None
                else {
                    "saved_count": len(serialized_records),
                    "sample_records": serialized_records[:10],
                },
            },
        )
        return self._build_result("bulk_save", payload)

    def replace_records(
        self,
        client: Any,
        *,
        records: Sequence[Tcra],
        action: str,
        summary: str,
        workbook_path: str = "session://banco-local",
        metadata: Mapping[str, object] | None = None,
        before: object | None = None,
        after: object | None = None,
    ) -> SupabaseTcraRpcResult:
        serialized_records = [serialize_tcra(record) for record in records]
        payload = self._execute_rpc(
            client,
            self.IMPORT_FUNCTION,
            {
                "p_records": serialized_records,
                "p_action": str(action or "").strip(),
                "p_summary": str(summary or "").strip(),
                "p_workbook_path": str(workbook_path or "session://banco-local").strip(),
                "p_metadata": self._json_object(metadata),
                "p_before": before,
                "p_after": after
                if after is not None
                else {
                    "imported_count": len(serialized_records),
                    "sample_records": serialized_records[:10],
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
            raise SupabaseTcraRpcError("Cliente Supabase ausente para executar a mutacao remota de TCRA.")
        try:
            response = client.rpc(function_name, params=dict(params)).execute()
        except Exception as exc:
            raise SupabaseTcraRpcError(
                f"Falha ao executar a funcao remota de TCRA '{function_name}': {exc}"
            ) from exc

        payload = getattr(response, "data", None)
        if not isinstance(payload, dict):
            raise SupabaseTcraRpcError(
                f"A funcao remota de TCRA '{function_name}' retornou um payload invalido."
            )
        return dict(payload)

    @staticmethod
    def _build_result(operation: str, payload: Mapping[str, object]) -> SupabaseTcraRpcResult:
        return SupabaseTcraRpcResult(
            operation=operation,
            uid=str(payload.get("uid", "") or ""),
            tcra_count=int(payload.get("tcra_count") or 0),
            tcra_event_count=int(payload.get("tcra_event_count") or 0),
            imported_count=int(payload.get("imported_count") or 0),
            audit_event_id=str(payload.get("audit_event_id", "") or ""),
        )


def serialize_tcra(record: Tcra | None) -> dict[str, object] | None:
    if record is None:
        return None
    return {
        "uid": _stringify(record.uid),
        "numero_processo": _stringify(record.numero_processo),
        "numero_tcra": _stringify(record.numero_tcra),
        "local": _stringify(record.local),
        "endereco": _stringify(record.endereco),
        "bairro": _stringify(record.bairro),
        "orgao_acompanhamento": _stringify(record.orgao_acompanhamento),
        "status": _stringify(record.status),
        "data_assinatura": _date_to_json(record.data_assinatura),
        "prazo_final": _date_to_json(record.prazo_final),
        "periodicidade_relatorio_meses": record.periodicidade_relatorio_meses,
        "data_ultimo_relatorio": _date_to_json(record.data_ultimo_relatorio),
        "data_proximo_relatorio": _date_to_json(record.data_proximo_relatorio),
        "area_m2": record.area_m2,
        "numero_mudas_previsto": record.numero_mudas_previsto,
        "servicos_exigidos": _stringify(record.servicos_exigidos),
        "responsavel_execucao": _stringify(record.responsavel_execucao),
        "observacoes": _stringify(record.observacoes),
        "mpsp_relacionado": _stringify(record.mpsp_relacionado),
        "inquerito_civil": _stringify(record.inquerito_civil),
        "eventos": [serialize_tcra_evento(evento) for evento in record.eventos],
    }


def serialize_tcra_evento(evento: TcraEvento) -> dict[str, object]:
    return {
        "sequence": int(evento.sequence or 0),
        "data_evento": _date_to_json(evento.data_evento),
        "tipo_evento": _stringify(evento.tipo_evento),
        "descricao": _stringify(evento.descricao),
        "prazo_resultante": _date_to_json(evento.prazo_resultante),
        "status_resultante": _stringify(evento.status_resultante),
        "protocolo": _stringify(getattr(evento, "protocolo", "")),
        "documento_ref": _stringify(getattr(evento, "documento_ref", "")),
    }


def _stringify(value: object) -> str:
    return str(value or "").strip()


def _date_to_json(value: date | None) -> str | None:
    return value.isoformat() if isinstance(value, date) else None
