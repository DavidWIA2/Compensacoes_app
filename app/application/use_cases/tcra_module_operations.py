from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.tcra_insights_service import TcraPotentialDuplicate, find_potential_duplicate_tcras
from app.services.tcra_excel_service import TcraExcelService, TcraImportMergeResult, TcraWorkbookAnalysis
from app.services.tcra_document_service import write_tcra_document
from app.services.tcra_records_service import (
    AGENDA_SCOPE_HOJE,
    STATUS_ARQUIVADO,
    STATUS_CUMPRIDO,
    STATUS_EM_ACOMPANHAMENTO,
    build_record_overview,
    build_record_search_index,
    build_work_agenda,
    normalize_orgao_label,
    normalize_status_label,
    operational_sort_key,
    resolve_record_consistency_issues,
)
from app.services.tcra_report_service import export_tcra_excel_report, export_tcra_pdf_report
from app.services.tcra_sqlite_service import TcraSqliteService
from app.services.access_service import AccessEnvironment, AppAccessSession, SupabaseAccessService
from app.services.supabase_tcra_rpc_service import SupabaseTcraRpcService, serialize_tcra
from app.utils.logger import get_logger


logger = get_logger("UseCases.TCRA")


def _stringify(value: object) -> str:
    return str(value or "").strip()


def _format_date_text(value: date | None) -> str:
    if value is None:
        return ""
    return value.strftime("%d/%m/%Y")


def _serialize_tcra_evento(evento: TcraEvento) -> dict[str, object]:
    return {
        "sequence": int(evento.sequence),
        "data_evento": _format_date_text(evento.data_evento),
        "tipo_evento": _stringify(evento.tipo_evento),
        "descricao": _stringify(evento.descricao),
        "prazo_resultante": _format_date_text(evento.prazo_resultante),
        "status_resultante": _stringify(evento.status_resultante),
        "protocolo": _stringify(getattr(evento, "protocolo", "")),
        "documento_ref": _stringify(getattr(evento, "documento_ref", "")),
    }


def _serialize_tcra(record: Tcra | None) -> dict[str, object] | None:
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
        "data_assinatura": _format_date_text(record.data_assinatura),
        "prazo_final": _format_date_text(record.prazo_final),
        "periodicidade_relatorio_meses": record.periodicidade_relatorio_meses,
        "data_ultimo_relatorio": _format_date_text(record.data_ultimo_relatorio),
        "data_proximo_relatorio": _format_date_text(record.data_proximo_relatorio),
        "area_m2": record.area_m2,
        "numero_mudas_previsto": record.numero_mudas_previsto,
        "servicos_exigidos": _stringify(record.servicos_exigidos),
        "responsavel_execucao": _stringify(record.responsavel_execucao),
        "observacoes": _stringify(record.observacoes),
        "mpsp_relacionado": _stringify(record.mpsp_relacionado),
        "inquerito_civil": _stringify(record.inquerito_civil),
        "eventos": [_serialize_tcra_evento(evento) for evento in record.eventos],
    }


def _record_label(record: Tcra | None) -> str:
    if record is None:
        return "--"
    return _stringify(record.numero_tcra or record.numero_processo or record.local or record.uid)


def _changed_tcra_fields(before: Tcra | None, after: Tcra | None) -> tuple[str, ...]:
    before_payload = _serialize_tcra(before) or {}
    after_payload = _serialize_tcra(after) or {}
    keys = sorted(set(before_payload) | set(after_payload))
    return tuple(key for key in keys if before_payload.get(key) != after_payload.get(key))


@dataclass(frozen=True)
class TcraLoadResult:
    records: tuple[Tcra, ...]
    search_index: dict[str, str]
    sync_issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class TcraSaveResult:
    status: str
    record: Tcra
    previous_record: Tcra | None = None
    saved_record: Tcra | None = None
    saved_uid: str = ""
    duplicate_record: Tcra | None = None
    consistency_issues: tuple[str, ...] = ()
    authority_source: str = "local"
    sync_issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class TcraDeleteResult:
    status: str
    deleted_uid: str = ""
    previous_record: Tcra | None = None
    authority_source: str = "local"
    sync_issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class TcraBulkActionResult:
    action: str
    updated_uids: tuple[str, ...] = ()
    updated_records: tuple[Tcra, ...] = ()
    authority_source: str = "local"
    sync_issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class TcraBulkCampaignResult:
    directory: str
    manifest_path: str
    document_paths: tuple[str, ...]
    updated_uids: tuple[str, ...] = ()
    updated_records: tuple[Tcra, ...] = ()
    authority_source: str = "local"
    sync_issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class TcraImportExecutionResult:
    analysis: TcraWorkbookAnalysis
    merge_result: TcraImportMergeResult
    merged_records: tuple[Tcra, ...]
    preferred_uid: str = ""
    authority_source: str = "local"
    sync_issues: tuple[str, ...] = ()

    @property
    def import_status_text(self) -> str:
        return (
            "Importacao em merge: "
            + " | ".join(self.merge_result.summary_lines())
            + " | "
            + " | ".join(self.analysis.summary_lines())
        )


@dataclass(frozen=True)
class TcraExportResult:
    export_format: str
    path: str
    record_count: int


@dataclass(frozen=True)
class TcraDashboardPayload:
    overview: object | None
    agenda_items: tuple[object, ...] = ()


class TcraModuleOperations:
    def __init__(
        self,
        sqlite_service: TcraSqliteService,
        *,
        today: date,
        audit_service_provider: Callable[[], object | None] | None = None,
        session_path_provider: Callable[[], str] | None = None,
        access_session_provider: Callable[[], object | None] | None = None,
        access_service: SupabaseAccessService | None = None,
        remote_tcra_service: SupabaseTcraRpcService | None = None,
    ):
        self.sqlite_service = sqlite_service
        self.today = today
        self.audit_service_provider = audit_service_provider
        self.session_path_provider = session_path_provider
        self.access_session_provider = access_session_provider
        self.access_service = access_service or SupabaseAccessService()
        self.remote_tcra_service = remote_tcra_service or SupabaseTcraRpcService()

    def _audit_service(self):
        if self.audit_service_provider is None:
            return None
        try:
            return self.audit_service_provider()
        except Exception as exc:
            logger.warning("Falha ao resolver servico de auditoria do modulo TCRA: %s", exc)
            return None

    def _session_path(self) -> str:
        if self.session_path_provider is None:
            return "session://banco-local"
        try:
            session_path = _stringify(self.session_path_provider())
        except Exception as exc:
            logger.warning("Falha ao resolver session_path do modulo TCRA: %s", exc)
            return "session://banco-local"
        return session_path or "session://banco-local"

    def _current_access_session(self) -> AppAccessSession:
        if self.access_session_provider is None:
            return AppAccessSession.local_default()
        try:
            access_session = self.access_session_provider()
        except Exception as exc:
            logger.warning("Falha ao resolver sessao de acesso do modulo TCRA: %s", exc)
            return AppAccessSession.local_default()
        if isinstance(access_session, AppAccessSession):
            return access_session
        return AppAccessSession.local_default()

    def _can_use_remote_tcra_write(self) -> bool:
        access_session = self._current_access_session()
        if access_session.environment != AccessEnvironment.PRODUCTION:
            return False

        session_path = self._session_path()
        expected_session_path = _stringify(getattr(access_session, "local_session_path", ""))
        if expected_session_path and session_path != expected_session_path:
            return False

        return bool(
            _stringify(getattr(access_session, "access_token", ""))
            and _stringify(getattr(access_session, "refresh_token", ""))
        )

    def _create_remote_client(self):
        return self.access_service.create_authenticated_client(self._current_access_session())

    def _can_use_remote_tcra_snapshot_refresh(self) -> bool:
        access_session = self._current_access_session()
        if access_session.environment != AccessEnvironment.PRODUCTION:
            return False

        session_path = self._session_path()
        expected_session_path = _stringify(getattr(access_session, "local_session_path", ""))
        if expected_session_path and session_path != expected_session_path:
            return False

        return bool(
            session_path
            and _stringify(getattr(access_session, "access_token", ""))
            and _stringify(getattr(access_session, "refresh_token", ""))
        )

    def refresh_remote_cache_if_production(self) -> tuple[str, ...]:
        if not self._can_use_remote_tcra_snapshot_refresh():
            return ()

        sync_service = getattr(self.access_service, "production_sync_service", None)
        if sync_service is None:
            issue = "Servico de sincronizacao da producao indisponivel para leitura remote-first de TCRA."
            logger.warning(issue)
            return (issue,)

        try:
            client = self._create_remote_client()
            sync_service.sync_authenticated_client(
                client,
                local_db_path=self.sqlite_service.db_path,
                session_path=self._session_path(),
            )
        except Exception as exc:
            issue = f"Falha ao sincronizar snapshot remoto de TCRA antes da leitura: {exc}"
            logger.warning(issue, exc_info=True)
            return (issue,)
        return ()

    def _sync_remote_cache_after_write(
        self,
        *,
        client,
        operation: str,
        fallback_local_apply: Callable[[], object],
    ) -> tuple[str, ...]:
        sync_service = getattr(self.access_service, "production_sync_service", None)
        if sync_service is None:
            issue = "Servico de sincronizacao da producao indisponivel para atualizar o cache local de TCRA."
        else:
            try:
                sync_service.sync_authenticated_client(
                    client,
                    local_db_path=self.sqlite_service.db_path,
                    session_path=self._session_path(),
                )
                return ()
            except Exception as exc:
                issue = f"Sincronizacao completa do cache local de TCRA apos escrita remota falhou: {exc}"
                logger.warning(issue, exc_info=True)

        try:
            fallback_local_apply()
        except Exception as exc:
            fallback_issue = f"Fallback local de TCRA apos escrita remota tambem falhou: {exc}"
            logger.warning(fallback_issue, exc_info=True)
            return (issue, fallback_issue)
        return (issue,)

    def _append_audit_event(
        self,
        *,
        action: str,
        summary: str,
        before_record: Tcra | None = None,
        after_record: Tcra | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        audit_service = self._audit_service()
        if audit_service is None or not hasattr(audit_service, "append_session_event"):
            return
        try:
            audit_service.append_session_event(
                session_path=self._session_path(),
                action=action,
                summary=summary,
                metadata=dict(metadata or {}),
                before=_serialize_tcra(before_record),
                after=_serialize_tcra(after_record),
            )
        except Exception as exc:
            logger.warning("Falha ao registrar auditoria do modulo TCRA (%s): %s", action, exc)

    def load_records(self, *, refresh_remote: bool = False) -> TcraLoadResult:
        sync_issues = self.refresh_remote_cache_if_production() if refresh_remote else ()
        records = tuple(self.sqlite_service.list_tcras())
        return TcraLoadResult(
            records=records,
            search_index=build_record_search_index(records),
            sync_issues=tuple(sync_issues),
        )

    def build_dashboard_payload(self, records: Sequence[Tcra]) -> TcraDashboardPayload:
        if not records:
            return TcraDashboardPayload(overview=None, agenda_items=())
        return TcraDashboardPayload(
            overview=build_record_overview(records, today=self.today),
            agenda_items=tuple(build_work_agenda(records, scope=AGENDA_SCOPE_HOJE, today=self.today, limit=5)),
        )

    def find_potential_duplicates(self, record: Tcra, *, limit: int = 3) -> tuple[TcraPotentialDuplicate, ...]:
        candidates = tuple(self.sqlite_service.list_tcras())
        return find_potential_duplicate_tcras(record, candidates, limit=limit)

    def save_record(
        self,
        record: Tcra,
        *,
        pending_audit_metadata: Mapping[str, object] | None = None,
    ) -> TcraSaveResult:
        previous_record = self.sqlite_service.get_tcra(record.uid)
        duplicate_record = self.sqlite_service.find_duplicate_tcra(
            numero_processo=record.numero_processo,
            numero_tcra=record.numero_tcra,
            local=record.local,
            exclude_uid=record.uid,
        )
        if duplicate_record is not None:
            return TcraSaveResult(
                status="duplicate",
                record=record,
                previous_record=previous_record,
                duplicate_record=duplicate_record,
            )
        consistency_issues = tuple(resolve_record_consistency_issues(record, today=self.today))
        if consistency_issues:
            return TcraSaveResult(
                status="invalid",
                record=record,
                previous_record=previous_record,
                consistency_issues=consistency_issues,
            )

        if self._can_use_remote_tcra_write():
            client = self._create_remote_client()
            action = "TCRA_EDIT" if previous_record is not None else "TCRA_CREATE"
            verb = "atualizado" if previous_record is not None else "cadastrado"
            metadata = {"uid": _stringify(record.uid), "authority": "supabase_remote", "environment": "production"}
            metadata["changed_fields"] = list(_changed_tcra_fields(previous_record, record))
            metadata.update(dict(pending_audit_metadata or {}))
            remote_result = self.remote_tcra_service.save_record(
                client,
                record=record,
                workbook_path=self._session_path(),
                action=action,
                summary=f"TCRA {verb}: {_record_label(record)}",
                metadata=metadata,
                before=_serialize_tcra(previous_record),
                after=_serialize_tcra(record),
            )
            saved_uid = _stringify(remote_result.uid or record.uid)
            saved_record = replace(record, uid=saved_uid) if saved_uid else record
            sync_issues = self._sync_remote_cache_after_write(
                client=client,
                operation="tcra_save",
                fallback_local_apply=lambda: self.sqlite_service.upsert_tcra(saved_record),
            )
            cached_record = self.sqlite_service.get_tcra(saved_uid) if saved_uid else None
            return TcraSaveResult(
                status="saved",
                record=record,
                previous_record=previous_record,
                saved_record=cached_record or saved_record,
                saved_uid=saved_uid,
                authority_source="remote",
                sync_issues=sync_issues,
            )

        saved_uid = self.sqlite_service.upsert_tcra(record)
        saved_record = self.sqlite_service.get_tcra(saved_uid) or replace(record, uid=saved_uid)
        action = "TCRA_EDIT" if previous_record is not None else "TCRA_CREATE"
        verb = "atualizado" if previous_record is not None else "cadastrado"
        metadata = {"uid": saved_uid}
        metadata["changed_fields"] = list(_changed_tcra_fields(previous_record, saved_record))
        metadata.update(dict(pending_audit_metadata or {}))
        self._append_audit_event(
            action=action,
            summary=f"TCRA {verb}: {_record_label(saved_record)}",
            before_record=previous_record,
            after_record=saved_record,
            metadata=metadata,
        )
        return TcraSaveResult(
            status="saved",
            record=record,
            previous_record=previous_record,
            saved_record=saved_record,
            saved_uid=saved_uid,
        )

    def delete_record(self, uid: str) -> TcraDeleteResult:
        normalized_uid = _stringify(uid)
        if not normalized_uid:
            return TcraDeleteResult(status="missing")
        previous_record = self.sqlite_service.get_tcra(normalized_uid)
        if self._can_use_remote_tcra_write():
            client = self._create_remote_client()
            self.remote_tcra_service.delete_record(
                client,
                uid=normalized_uid,
                workbook_path=self._session_path(),
                action="TCRA_DELETE",
                summary=f"TCRA excluido: {_record_label(previous_record)}",
                metadata={"uid": normalized_uid, "authority": "supabase_remote", "environment": "production"},
                before=_serialize_tcra(previous_record),
            )
            sync_issues = self._sync_remote_cache_after_write(
                client=client,
                operation="tcra_delete",
                fallback_local_apply=lambda: self.sqlite_service.delete_tcra(normalized_uid),
            )
            return TcraDeleteResult(
                status="deleted",
                deleted_uid=normalized_uid,
                previous_record=previous_record,
                authority_source="remote",
                sync_issues=sync_issues,
            )

        self.sqlite_service.delete_tcra(normalized_uid)
        self._append_audit_event(
            action="TCRA_DELETE",
            summary=f"TCRA excluido: {_record_label(previous_record)}",
            before_record=previous_record,
            metadata={"uid": normalized_uid},
        )
        return TcraDeleteResult(
            status="deleted",
            deleted_uid=normalized_uid,
            previous_record=previous_record,
        )

    def _build_bulk_event(
        self,
        values: Mapping[str, object],
        *,
        sequence: int,
        parse_date: Callable[[str, str], date | None],
        event_presets: Sequence[Mapping[str, object]],
    ) -> TcraEvento:
        preset_key = _stringify(values.get("event_preset"))
        selected_preset = next(
            (item for item in event_presets if _stringify(item.get("key")) == preset_key),
            None,
        )
        return TcraEvento(
            sequence=sequence,
            data_evento=parse_date(_stringify(values.get("event_date")), "Data do evento"),
            tipo_evento=_stringify((selected_preset or {}).get("tipo_evento")),
            descricao=_stringify((selected_preset or {}).get("descricao")),
            prazo_resultante=(
                parse_date(_stringify(values.get("event_deadline")), "Prazo resultante")
                if _stringify(values.get("event_deadline"))
                else None
            ),
            status_resultante=normalize_status_label((selected_preset or {}).get("status_resultante")),
            protocolo=_stringify(values.get("event_protocol")),
            documento_ref=_stringify(values.get("event_document")),
        )

    def _apply_event_effects_to_record(self, record: Tcra, evento: TcraEvento) -> Tcra:
        status = normalize_status_label(evento.status_resultante) or normalize_status_label(record.status)
        prazo_final = evento.prazo_resultante or record.prazo_final
        data_ultimo_relatorio = record.data_ultimo_relatorio
        data_proximo_relatorio = record.data_proximo_relatorio
        if "RELATORIO" in _stringify(evento.tipo_evento).upper() and evento.data_evento is not None:
            data_ultimo_relatorio = evento.data_evento
            if evento.prazo_resultante is not None:
                data_proximo_relatorio = evento.prazo_resultante
        if status in {STATUS_CUMPRIDO, STATUS_ARQUIVADO}:
            data_proximo_relatorio = None
        return replace(
            record,
            status=status or record.status,
            prazo_final=prazo_final,
            data_ultimo_relatorio=data_ultimo_relatorio,
            data_proximo_relatorio=data_proximo_relatorio,
        )

    def append_event_to_record(self, record: Tcra, evento: TcraEvento) -> Tcra:
        base_record = replace(record, eventos=list(record.eventos) + [evento])
        return self._apply_event_effects_to_record(base_record, evento)

    def _apply_bulk_action_to_record(
        self,
        record: Tcra,
        values: Mapping[str, object],
        *,
        parse_date: Callable[[str, str], date | None],
        event_presets: Sequence[Mapping[str, object]],
    ) -> Tcra:
        action = _stringify(values.get("action"))
        if action == "status":
            normalized_status = normalize_status_label(values.get("status"))
            if not normalized_status:
                raise ValueError("Acao em lote: informe um status valido.")
            return replace(record, status=normalized_status)
        if action == "responsavel":
            text_value = _stringify(values.get("text_value"))
            if not text_value:
                raise ValueError("Acao em lote: informe o responsavel desejado.")
            return replace(record, responsavel_execucao=text_value)
        if action == "orgao":
            orgao = normalize_orgao_label(values.get("text_value"))
            if not orgao:
                raise ValueError("Acao em lote: informe o orgao desejado.")
            return replace(record, orgao_acompanhamento=orgao)
        if action == "proximo_relatorio":
            return replace(
                record,
                data_proximo_relatorio=(
                    parse_date(_stringify(values.get("date_value")), "Proximo relatorio")
                    if _stringify(values.get("date_value"))
                    else None
                ),
            )
        if action == "evento":
            evento = self._build_bulk_event(
                values,
                sequence=max((evento.sequence for evento in record.eventos), default=0) + 1,
                parse_date=parse_date,
                event_presets=event_presets,
            )
            return self.append_event_to_record(record, evento)
        return record

    def apply_bulk_action(
        self,
        records: Sequence[Tcra],
        values: Mapping[str, object],
        *,
        parse_date: Callable[[str, str], date | None],
        event_presets: Sequence[Mapping[str, object]],
    ) -> TcraBulkActionResult:
        action = _stringify(values.get("action"))
        updated_records: list[Tcra] = []
        for record in records:
            updated_records.append(
                self._apply_bulk_action_to_record(
                    record,
                    values,
                    parse_date=parse_date,
                    event_presets=event_presets,
                )
            )

        if self._can_use_remote_tcra_write():
            client = self._create_remote_client()
            self.remote_tcra_service.save_records(
                client,
                records=updated_records,
                workbook_path=self._session_path(),
                action="TCRA_BULK_UPDATE",
                summary=f"Acao em lote aplicada em {len(updated_records)} TCRA(s): {action}",
                metadata={
                    "count": len(updated_records),
                    "bulk_action": action,
                    "uids": [_stringify(record.uid) for record in updated_records[:20]],
                    "authority": "supabase_remote",
                    "environment": "production",
                },
                before=[_serialize_tcra(record) for record in records[:20]],
                after=[_serialize_tcra(record) for record in updated_records[:20]],
            )
            sync_issues = self._sync_remote_cache_after_write(
                client=client,
                operation="tcra_bulk_update",
                fallback_local_apply=lambda: [self.sqlite_service.upsert_tcra(record) for record in updated_records],
            )
            updated_uids = tuple(_stringify(record.uid) for record in updated_records if _stringify(record.uid))
            cached_records = tuple(self.sqlite_service.get_tcras_by_uids(updated_uids)) if updated_uids else tuple(updated_records)
            return TcraBulkActionResult(
                action=action,
                updated_uids=updated_uids,
                updated_records=cached_records or tuple(updated_records),
                authority_source="remote",
                sync_issues=sync_issues,
            )

        updated_uids: list[str] = []
        for updated_record in updated_records:
            saved_uid = self.sqlite_service.upsert_tcra(updated_record)
            updated_uids.append(saved_uid)
        updated_records = tuple(self.sqlite_service.get_tcras_by_uids(updated_uids))
        self._append_audit_event(
            action="TCRA_BULK_UPDATE",
            summary=f"Acao em lote aplicada em {len(updated_uids)} TCRA(s): {action}",
            metadata={
                "count": len(updated_uids),
                "bulk_action": action,
                "uids": list(updated_uids[:20]),
            },
        )
        return TcraBulkActionResult(
            action=action,
            updated_uids=tuple(updated_uids),
            updated_records=updated_records,
        )

    @staticmethod
    def _safe_document_stem(value: object) -> str:
        raw_value = _stringify(value) or "tcra"
        cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in raw_value)
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned.strip("_") or "tcra"

    def create_cobranca_campaign(
        self,
        records: Sequence[Tcra],
        *,
        directory: str | Path,
        response_deadline: date | None = None,
        register_event: bool = True,
    ) -> TcraBulkCampaignResult:
        target_dir = Path(directory)
        target_dir.mkdir(parents=True, exist_ok=True)

        document_paths: list[str] = []
        manifest_lines = [
            f"Campanha de cobranca gerada em {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            f"Qtd. de TCRAs: {len(records)}",
            f"Retorno esperado: {_format_date_text(response_deadline) or '--'}",
            "",
        ]

        updated_records: list[Tcra] = []
        for index, record in enumerate(records, start=1):
            file_name = f"{index:02d}_{self._safe_document_stem(_record_label(record))}_cobranca.txt"
            document_path = target_dir / file_name
            write_tcra_document(document_path, record, kind="cobranca", today=self.today)
            document_paths.append(str(document_path))
            manifest_lines.append(f"- {_record_label(record)} | {document_path}")

            if not register_event:
                continue
            event_description = "Cobranca em lote registrada."
            if response_deadline is not None:
                event_description = (
                    f"Cobranca em lote registrada. Retorno esperado ate {_format_date_text(response_deadline)}."
                )
            evento = TcraEvento(
                sequence=max((evento.sequence for evento in record.eventos), default=0) + 1,
                data_evento=self.today,
                tipo_evento="Cobranca",
                descricao=event_description,
                prazo_resultante=response_deadline,
                status_resultante=normalize_status_label(record.status) or STATUS_EM_ACOMPANHAMENTO,
                documento_ref=str(document_path),
            )
            updated_records.append(self.append_event_to_record(record, evento))

        manifest_path = target_dir / "manifesto_campanha_cobranca.txt"
        manifest_path.write_text("\n".join(manifest_lines).strip() + "\n", encoding="utf-8")

        if not register_event:
            self._append_audit_event(
                action="TCRA_BULK_CAMPAIGN",
                summary=f"Campanha de cobranca gerada para {len(records)} TCRA(s)",
                metadata={
                    "count": len(records),
                    "directory": str(target_dir),
                    "manifest_path": str(manifest_path),
                    "document_paths": document_paths[:20],
                },
            )
            return TcraBulkCampaignResult(
                directory=str(target_dir),
                manifest_path=str(manifest_path),
                document_paths=tuple(document_paths),
            )

        if self._can_use_remote_tcra_write():
            client = self._create_remote_client()
            self.remote_tcra_service.save_records(
                client,
                records=updated_records,
                workbook_path=self._session_path(),
                action="TCRA_BULK_CAMPAIGN",
                summary=f"Campanha de cobranca gerada para {len(updated_records)} TCRA(s)",
                metadata={
                    "count": len(updated_records),
                    "directory": str(target_dir),
                    "manifest_path": str(manifest_path),
                    "uids": [_stringify(record.uid) for record in updated_records[:20]],
                    "authority": "supabase_remote",
                    "environment": "production",
                },
                before=[_serialize_tcra(record) for record in records[:20]],
                after=[_serialize_tcra(record) for record in updated_records[:20]],
            )
            sync_issues = self._sync_remote_cache_after_write(
                client=client,
                operation="tcra_bulk_campaign",
                fallback_local_apply=lambda: [self.sqlite_service.upsert_tcra(record) for record in updated_records],
            )
            updated_uids = tuple(_stringify(record.uid) for record in updated_records if _stringify(record.uid))
            cached_records = tuple(self.sqlite_service.get_tcras_by_uids(updated_uids)) if updated_uids else tuple(updated_records)
            return TcraBulkCampaignResult(
                directory=str(target_dir),
                manifest_path=str(manifest_path),
                document_paths=tuple(document_paths),
                updated_uids=updated_uids,
                updated_records=cached_records or tuple(updated_records),
                authority_source="remote",
                sync_issues=sync_issues,
            )

        updated_uids: list[str] = []
        for updated_record in updated_records:
            updated_uids.append(self.sqlite_service.upsert_tcra(updated_record))
        persisted_records = tuple(self.sqlite_service.get_tcras_by_uids(updated_uids))
        self._append_audit_event(
            action="TCRA_BULK_CAMPAIGN",
            summary=f"Campanha de cobranca gerada para {len(updated_uids)} TCRA(s)",
            metadata={
                "count": len(updated_uids),
                "directory": str(target_dir),
                "manifest_path": str(manifest_path),
                "uids": updated_uids[:20],
            },
        )
        return TcraBulkCampaignResult(
            directory=str(target_dir),
            manifest_path=str(manifest_path),
            document_paths=tuple(document_paths),
            updated_uids=tuple(updated_uids),
            updated_records=persisted_records,
        )

    def analyze_import_workbook(self, path: str | Path) -> TcraWorkbookAnalysis:
        return TcraExcelService(sqlite_service=self.sqlite_service, today=self.today).analyze_workbook(path)

    def _build_import_merge_records(
        self,
        analysis: TcraWorkbookAnalysis,
    ) -> tuple[TcraImportMergeResult, tuple[Tcra, ...]]:
        service = TcraExcelService(sqlite_service=self.sqlite_service, today=self.today)
        created_count = 0
        updated_count = 0
        imported_uids: list[str] = []
        merged_records: list[Tcra] = []
        for imported_record in analysis.tcras:
            existing = self.sqlite_service.find_duplicate_tcra(
                numero_processo=imported_record.numero_processo,
                numero_tcra=imported_record.numero_tcra,
                local=imported_record.local,
            )
            if existing is None:
                merged_record = imported_record
                created_count += 1
            else:
                merged_record = service._merge_records(existing, imported_record)
                updated_count += 1
            merged_records.append(merged_record)
            imported_uids.append(_stringify(merged_record.uid))

        return (
            TcraImportMergeResult(
                importable_count=analysis.importable_count,
                created_count=created_count,
                updated_count=updated_count,
                imported_uids=tuple(imported_uids),
            ),
            tuple(merged_records),
        )

    def execute_import_merge(self, analysis: TcraWorkbookAnalysis) -> TcraImportExecutionResult:
        if self._can_use_remote_tcra_write():
            merge_result, merged_records = self._build_import_merge_records(analysis)
            client = self._create_remote_client()
            self.remote_tcra_service.save_records(
                client,
                records=merged_records,
                workbook_path=self._session_path(),
                action="TCRA_IMPORT",
                summary=f"Importacao TCRA concluida: {analysis.importable_count} termo(s)",
                metadata={
                    "mode": "merge",
                    "importable_count": analysis.importable_count,
                    "created_count": merge_result.created_count,
                    "updated_count": merge_result.updated_count,
                    "skipped_count": analysis.skipped_count,
                    "issue_count": len(analysis.issues),
                    "issue_codes": [issue.code for issue in analysis.issues[:10]],
                    "authority": "supabase_remote",
                    "environment": "production",
                },
                after={
                    "importable_count": analysis.importable_count,
                    "sample_records": [serialize_tcra(record) for record in merged_records[:10]],
                },
            )
            sync_issues = self._sync_remote_cache_after_write(
                client=client,
                operation="tcra_import",
                fallback_local_apply=lambda: [self.sqlite_service.upsert_tcra(record) for record in merged_records],
            )
            cached_records = tuple(self.sqlite_service.get_tcras_by_uids(merge_result.imported_uids))
            resolved_records = cached_records or merged_records
            preferred_record = (
                min(resolved_records, key=lambda record: operational_sort_key(record, today=self.today))
                if resolved_records
                else None
            )
            return TcraImportExecutionResult(
                analysis=analysis,
                merge_result=merge_result,
                merged_records=resolved_records,
                preferred_uid=_stringify(getattr(preferred_record, "uid", "")),
                authority_source="remote",
                sync_issues=sync_issues,
            )

        service = TcraExcelService(sqlite_service=self.sqlite_service, today=self.today)
        merge_result = service.merge_workbook(analysis)
        merged_records = tuple(self.sqlite_service.get_tcras_by_uids(merge_result.imported_uids))
        preferred_record = min(merged_records, key=lambda record: operational_sort_key(record, today=self.today)) if merged_records else None
        self._append_audit_event(
            action="TCRA_IMPORT",
            summary=f"Importacao TCRA concluida: {analysis.importable_count} termo(s)",
            metadata={
                "mode": "merge",
                "importable_count": analysis.importable_count,
                "created_count": merge_result.created_count,
                "updated_count": merge_result.updated_count,
                "skipped_count": analysis.skipped_count,
                "issue_count": len(analysis.issues),
                "issue_codes": [issue.code for issue in analysis.issues[:10]],
            },
        )
        return TcraImportExecutionResult(
            analysis=analysis,
            merge_result=merge_result,
            merged_records=merged_records,
            preferred_uid=_stringify(getattr(preferred_record, "uid", "")),
        )

    def export_excel_report(self, path: str, records: Sequence[Tcra], *, filter_summary: str) -> TcraExportResult:
        export_tcra_excel_report(path, records, filter_summary=filter_summary, today=self.today)
        return TcraExportResult(export_format="excel", path=str(path), record_count=len(list(records)))

    def export_pdf_report(self, path: str, records: Sequence[Tcra], *, filter_summary: str) -> TcraExportResult:
        export_tcra_pdf_report(path, records, filter_summary=filter_summary, today=self.today)
        return TcraExportResult(export_format="pdf", path=str(path), record_count=len(list(records)))

    def export_record_document(self, path: str, record: Tcra, *, kind: str = "cobranca") -> TcraExportResult:
        write_tcra_document(path, record, kind=kind, today=self.today)
        return TcraExportResult(export_format=kind or "documento", path=str(path), record_count=1)
