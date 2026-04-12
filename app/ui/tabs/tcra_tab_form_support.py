from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Mapping, Sequence

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.tcra_records_service import (
    STATUS_EM_ACOMPANHAMENTO,
    normalize_event_type_label,
    remove_accents,
    normalize_orgao_label,
    normalize_status_label,
    resolve_operational_issues,
    resolve_operational_status,
    resolve_record_consistency_issues,
    suggest_issue_fix,
    tcra_has_missing_identity,
    tcra_has_missing_orgao,
    tcra_has_missing_responsavel,
    tcra_has_prazo_vencido,
    tcra_has_relatorio_pendente,
    tcra_has_report_due_soon,
)
from app.ui.tabs.tcra_tab_support import format_date_text, stringify


@dataclass(frozen=True)
class TcraFormPreviewData:
    primary_issue: str
    guidance_text: str
    details_text: str
    operational_issues: tuple[str, ...]
    consistency_issues: tuple[str, ...]


def capture_form_state_snapshot(
    *,
    uid: str,
    numero_processo: str,
    numero_tcra: str,
    local: str,
    endereco: str,
    bairro: str,
    orgao: str,
    status: str,
    data_assinatura: str,
    prazo_final: str,
    periodicidade: str,
    data_ultimo_relatorio: str,
    data_proximo_relatorio: str,
    area_m2: str,
    numero_mudas: str,
    responsavel: str,
    mpsp: bool,
    inquerito: str,
    servicos: str,
    observacoes: str,
    eventos: Sequence[TcraEvento],
) -> dict[str, object]:
    return {
        "uid": stringify(uid),
        "numero_processo": stringify(numero_processo),
        "numero_tcra": stringify(numero_tcra),
        "local": stringify(local),
        "endereco": stringify(endereco),
        "bairro": stringify(bairro),
        "orgao": stringify(orgao),
        "status": normalize_status_label(stringify(status)) or "Em acompanhamento",
        "data_assinatura": stringify(data_assinatura),
        "prazo_final": stringify(prazo_final),
        "periodicidade": stringify(periodicidade),
        "data_ultimo_relatorio": stringify(data_ultimo_relatorio),
        "data_proximo_relatorio": stringify(data_proximo_relatorio),
        "area_m2": stringify(area_m2),
        "numero_mudas": stringify(numero_mudas),
        "responsavel": stringify(responsavel),
        "mpsp": bool(mpsp),
        "inquerito": stringify(inquerito),
        "servicos": stringify(servicos),
        "observacoes": stringify(observacoes),
        "eventos": tuple(
            (
                evento.sequence,
                format_date_text(evento.data_evento),
                stringify(evento.tipo_evento),
                stringify(evento.descricao),
                format_date_text(evento.prazo_resultante),
                stringify(evento.status_resultante),
                stringify(getattr(evento, "protocolo", "")),
                stringify(getattr(evento, "documento_ref", "")),
            )
            for evento in eventos
        ),
    }


def build_record_form_snapshot(record: Tcra) -> dict[str, object]:
    return capture_form_state_snapshot(
        uid=record.uid,
        numero_processo=record.numero_processo,
        numero_tcra=record.numero_tcra,
        local=record.local,
        endereco=record.endereco,
        bairro=record.bairro,
        orgao=normalize_orgao_label(record.orgao_acompanhamento),
        status=normalize_status_label(record.status) or STATUS_EM_ACOMPANHAMENTO,
        data_assinatura=format_date_text(record.data_assinatura),
        prazo_final=format_date_text(record.prazo_final),
        periodicidade="" if record.periodicidade_relatorio_meses is None else str(record.periodicidade_relatorio_meses),
        data_ultimo_relatorio=format_date_text(record.data_ultimo_relatorio),
        data_proximo_relatorio=format_date_text(record.data_proximo_relatorio),
        area_m2="" if record.area_m2 is None else str(record.area_m2),
        numero_mudas="" if record.numero_mudas_previsto is None else str(record.numero_mudas_previsto),
        responsavel=record.responsavel_execucao,
        mpsp=remove_accents(stringify(record.mpsp_relacionado)).lower() == "sim",
        inquerito=record.inquerito_civil,
        servicos=record.servicos_exigidos,
        observacoes=record.observacoes,
        eventos=record.eventos,
    )


def build_empty_form_snapshot(*, default_status: str = STATUS_EM_ACOMPANHAMENTO) -> dict[str, object]:
    return capture_form_state_snapshot(
        uid="",
        numero_processo="",
        numero_tcra="",
        local="",
        endereco="",
        bairro="",
        orgao="",
        status=default_status,
        data_assinatura="",
        prazo_final="",
        periodicidade="",
        data_ultimo_relatorio="",
        data_proximo_relatorio="",
        area_m2="",
        numero_mudas="",
        responsavel="",
        mpsp=False,
        inquerito="",
        servicos="",
        observacoes="",
        eventos=(),
    )


def restore_form_eventos_snapshot(
    rows: Sequence[object],
    *,
    parse_date: Callable[[str, str], date | None],
) -> list[TcraEvento]:
    eventos: list[TcraEvento] = []
    for index, row in enumerate(list(rows or ()), start=1):
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        data_evento = stringify(row[1])
        prazo_resultante = stringify(row[4])
        eventos.append(
            TcraEvento(
                sequence=int(row[0] or index),
                data_evento=parse_date(data_evento, "Data do evento") if data_evento else None,
                tipo_evento=normalize_event_type_label(row[2]),
                descricao=stringify(row[3]),
                prazo_resultante=parse_date(prazo_resultante, "Prazo resultante") if prazo_resultante else None,
                status_resultante=normalize_status_label(stringify(row[5])),
                protocolo=stringify(row[6]) if len(row) > 6 else "",
                documento_ref=stringify(row[7]) if len(row) > 7 else "",
            )
        )
    return eventos


def resolve_issue_focus_field(issue: str) -> str:
    normalized_issue = remove_accents(issue).lower()
    if "numero tcra" in normalized_issue:
        return "numero_tcra"
    if "responsavel" in normalized_issue:
        return "responsavel"
    if "orgao" in normalized_issue:
        return "orgao"
    if "periodicidade" in normalized_issue:
        return "periodicidade"
    if "proximo relatorio" in normalized_issue:
        return "data_proximo_relatorio"
    if "ultimo relatorio" in normalized_issue:
        return "data_ultimo_relatorio"
    if "prazo final" in normalized_issue or "prazo vencido" in normalized_issue:
        return "prazo_final"
    if "status" in normalized_issue:
        return "status"
    if "assinatura" in normalized_issue:
        return "data_assinatura"
    return ""


def resolve_safe_fix_updates(issue: str, snapshot: Mapping[str, object]) -> dict[str, object]:
    normalized_issue = remove_accents(issue).lower()
    ultimo_relatorio = stringify(snapshot.get("data_ultimo_relatorio"))
    if "cumprido/arquivado" in normalized_issue and "proximo relatorio" in normalized_issue:
        return {"data_proximo_relatorio": ""}
    if "proximo relatorio nao pode ser anterior" in normalized_issue and ultimo_relatorio:
        return {"data_proximo_relatorio": ultimo_relatorio}
    if "prazo final nao pode ser anterior" in normalized_issue:
        return {"prazo_final": ""}
    if "relatorio pendente" in normalized_issue and "exige data do proximo relatorio" in normalized_issue and ultimo_relatorio:
        return {"data_proximo_relatorio": ultimo_relatorio}
    return {}


def issue_supports_safe_fix(issue: str) -> bool:
    return bool(resolve_safe_fix_updates(issue, {})) or any(
        marker in remove_accents(issue).lower()
        for marker in (
            "cumprido/arquivado",
            "proximo relatorio nao pode ser anterior",
            "prazo final nao pode ser anterior",
            "relatorio pendente",
        )
    )


def build_form_preview_data(
    *,
    snapshot: Mapping[str, object],
    preview_record: Tcra | None,
    recent_event_lines: Sequence[str],
    today: date,
) -> TcraFormPreviewData:
    operational_status = resolve_operational_status(preview_record, today=today) if preview_record is not None else "--"
    operational_issues = (
        tuple(resolve_operational_issues(preview_record, today=today)) if preview_record is not None else ()
    )
    consistency_issues = (
        tuple(resolve_record_consistency_issues(preview_record, today=today)) if preview_record is not None else ()
    )
    alert_flags: list[str] = []
    if preview_record is not None:
        if tcra_has_prazo_vencido(preview_record, today=today):
            alert_flags.append("Prazo vencido")
        if tcra_has_relatorio_pendente(preview_record, today=today):
            alert_flags.append("Relatório pendente")
        if tcra_has_report_due_soon(preview_record, today=today):
            alert_flags.append("Relatório nos próximos 30 dias")
        if tcra_has_missing_identity(preview_record):
            alert_flags.append("Sem número TCRA")
        if tcra_has_missing_responsavel(preview_record):
            alert_flags.append("Sem responsável")
        if tcra_has_missing_orgao(preview_record):
            alert_flags.append("Sem órgão")

    primary_issue = consistency_issues[0] if consistency_issues else (operational_issues[0] if operational_issues else "")
    if primary_issue:
        guidance_text = f"Correção assistida: {primary_issue} Sugestão: {suggest_issue_fix(primary_issue)}"
    else:
        guidance_text = "Correção assistida: cadastro coerente no recorte atual."

    lines = [
        f"Processo: {stringify(snapshot.get('numero_processo')) or '--'}",
        f"TCRA: {stringify(snapshot.get('numero_tcra')) or '--'}",
        f"Local: {stringify(snapshot.get('local')) or '--'}",
        f"Endereço: {stringify(snapshot.get('endereco')) or '--'}",
        f"Bairro: {stringify(snapshot.get('bairro')) or '--'}",
        f"Órgão de acompanhamento: {normalize_orgao_label(snapshot.get('orgao')) or '--'}",
        f"Status informado: {normalize_status_label(snapshot.get('status')) or '--'}",
        f"Status operacional: {operational_status}",
        f"Assinatura: {stringify(snapshot.get('data_assinatura')) or '--'}",
        f"Prazo final: {stringify(snapshot.get('prazo_final')) or '--'}",
        f"Último relatório: {stringify(snapshot.get('data_ultimo_relatorio')) or '--'}",
        f"Próximo relatório: {stringify(snapshot.get('data_proximo_relatorio')) or '--'}",
        f"Periodicidade (meses): {stringify(snapshot.get('periodicidade')) or '--'}",
        f"Area (m2): {stringify(snapshot.get('area_m2')) or '--'}",
        f"Número de mudas: {stringify(snapshot.get('numero_mudas')) or '--'}",
        f"Responsável: {stringify(snapshot.get('responsavel')) or '--'}",
        f"MPSP relacionado: {'Sim' if snapshot.get('mpsp') else 'Não'}",
        f"Inquérito civil: {stringify(snapshot.get('inquerito')) or '--'}",
        f"Eventos cadastrados: {len(list(snapshot.get('eventos') or ())) }",
        f"Alertas: {', '.join(alert_flags) if alert_flags else '--'}",
        "",
        "Pendências operacionais:",
        *list(operational_issues or ("Nenhuma pendência prioritária.",)),
        "",
        "Inconsistências de cadastro:",
        *list(consistency_issues or ("Nenhuma inconsistência estrutural detectada.",)),
        "",
        "Timeline recente:",
        *list(recent_event_lines or ("Nenhum evento cadastrado.",)),
        "",
        "Serviços exigidos:",
        stringify(snapshot.get("servicos")) or "--",
        "",
        "Observações:",
        stringify(snapshot.get("observacoes")) or "--",
    ]
    return TcraFormPreviewData(
        primary_issue=primary_issue,
        guidance_text=guidance_text,
        details_text="\n".join(lines),
        operational_issues=operational_issues,
        consistency_issues=consistency_issues,
    )
