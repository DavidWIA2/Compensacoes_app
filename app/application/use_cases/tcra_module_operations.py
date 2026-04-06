from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Callable, Mapping, Sequence

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.tcra_excel_service import TcraExcelService, TcraImportMergeResult, TcraWorkbookAnalysis
from app.services.tcra_records_service import (
    AGENDA_SCOPE_HOJE,
    STATUS_ARQUIVADO,
    STATUS_CUMPRIDO,
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


@dataclass(frozen=True)
class TcraLoadResult:
    records: tuple[Tcra, ...]
    search_index: dict[str, str]


@dataclass(frozen=True)
class TcraSaveResult:
    status: str
    record: Tcra
    previous_record: Tcra | None = None
    saved_record: Tcra | None = None
    saved_uid: str = ""
    duplicate_record: Tcra | None = None
    consistency_issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class TcraDeleteResult:
    status: str
    deleted_uid: str = ""
    previous_record: Tcra | None = None


@dataclass(frozen=True)
class TcraBulkActionResult:
    action: str
    updated_uids: tuple[str, ...] = ()
    updated_records: tuple[Tcra, ...] = ()


@dataclass(frozen=True)
class TcraImportExecutionResult:
    analysis: TcraWorkbookAnalysis
    merge_result: TcraImportMergeResult
    merged_records: tuple[Tcra, ...]
    preferred_uid: str = ""

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
    ):
        self.sqlite_service = sqlite_service
        self.today = today
        self.audit_service_provider = audit_service_provider
        self.session_path_provider = session_path_provider

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

    def load_records(self) -> TcraLoadResult:
        records = tuple(self.sqlite_service.list_tcras())
        return TcraLoadResult(records=records, search_index=build_record_search_index(records))

    def build_dashboard_payload(self, records: Sequence[Tcra]) -> TcraDashboardPayload:
        if not records:
            return TcraDashboardPayload(overview=None, agenda_items=())
        return TcraDashboardPayload(
            overview=build_record_overview(records, today=self.today),
            agenda_items=tuple(build_work_agenda(records, scope=AGENDA_SCOPE_HOJE, today=self.today, limit=5)),
        )

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

        saved_uid = self.sqlite_service.upsert_tcra(record)
        saved_record = self.sqlite_service.get_tcra(saved_uid) or replace(record, uid=saved_uid)
        action = "TCRA_EDIT" if previous_record is not None else "TCRA_CREATE"
        verb = "atualizado" if previous_record is not None else "cadastrado"
        metadata = {"uid": saved_uid}
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
            base_record = replace(record, eventos=list(record.eventos) + [evento])
            return self._apply_event_effects_to_record(base_record, evento)
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
        updated_uids: list[str] = []
        for record in records:
            updated_record = self._apply_bulk_action_to_record(
                record,
                values,
                parse_date=parse_date,
                event_presets=event_presets,
            )
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

    def analyze_import_workbook(self, path: str | Path) -> TcraWorkbookAnalysis:
        return TcraExcelService(sqlite_service=self.sqlite_service, today=self.today).analyze_workbook(path)

    def execute_import_merge(self, analysis: TcraWorkbookAnalysis) -> TcraImportExecutionResult:
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
