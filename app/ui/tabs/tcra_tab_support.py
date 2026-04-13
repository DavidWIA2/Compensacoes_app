from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtGui import QColor

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.tcra_insights_service import resolve_tcra_sla_profile
from app.services.tcra_records_service import (
    STATUS_CUMPRIDO,
    STATUS_EM_ACOMPANHAMENTO,
    STATUS_PRAZO_VENCIDO,
    STATUS_RELATORIO_PENDENTE,
    STATUS_SEM_STATUS,
    STATUS_SEM_VALIDADE,
    UPCOMING_REPORT_WINDOW_DAYS,
    normalize_orgao_label,
    resolve_operational_issues,
    resolve_operational_status,
    resolve_record_consistency_issues,
    tcra_has_missing_identity,
    tcra_has_missing_orgao,
    tcra_has_missing_responsavel,
    tcra_has_prazo_vencido,
    tcra_has_relatorio_pendente,
    tcra_has_report_due_soon,
    tcra_has_stale_movement,
    tcra_is_mpsp_related,
)


def stringify(value: object) -> str:
    return str(value or "").strip()


def format_date(value: date | None) -> str:
    if value is None:
        return "--"
    return value.strftime("%d/%m/%Y")


def format_date_text(value: date | None) -> str:
    if value is None:
        return ""
    return value.strftime("%d/%m/%Y")


_stringify = stringify
_format_date = format_date
_format_date_text = format_date_text


def format_orgao_context(record: Tcra) -> str:
    orgao = normalize_orgao_label(record.orgao_acompanhamento) or _stringify(record.orgao_acompanhamento)
    if tcra_is_mpsp_related(record) and "MPSP" not in orgao.upper():
        return f"{orgao} + MPSP" if orgao else "MPSP"
    return orgao or "--"


def resolve_record_priority_label(record: Tcra, *, today: date) -> str:
    operational_status = resolve_operational_status(record, today=today)
    if tcra_has_prazo_vencido(record, today=today):
        return "Vencido"
    if tcra_has_relatorio_pendente(record, today=today):
        return "Relatório"
    if tcra_has_report_due_soon(record, today=today):
        return "30 dias"
    if tcra_has_stale_movement(record, today=today):
        return "Sem mov."
    if tcra_has_missing_identity(record) or tcra_has_missing_responsavel(record) or tcra_has_missing_orgao(record):
        return "Cadastro"
    if operational_status == STATUS_CUMPRIDO:
        return "Concluído"
    if operational_status == STATUS_SEM_VALIDADE:
        return "Validade"
    return "Rotina"


def resolve_record_next_action(record: Tcra, *, today: date) -> str:
    operational_status = resolve_operational_status(record, today=today)
    sla_profile = resolve_tcra_sla_profile(record, today=today)
    if tcra_has_prazo_vencido(record, today=today):
        if sla_profile.status == "escalated":
            return "Cobrar cumprimento, revisar prazo e escalar coordenação"
        if sla_profile.status == "overdue":
            return "Cobrar cumprimento / revisar prazo com urgência"
        return "Cobrar cumprimento / revisar prazo"
    if tcra_has_relatorio_pendente(record, today=today):
        return "Cobrar relatório e registrar protocolo"
    if tcra_has_report_due_soon(record, today=today):
        return f"Preparar relatório para {format_date(record.data_proximo_relatorio)}"
    if tcra_has_stale_movement(record, today=today):
        return "Registrar movimentação, cobrança ou vistoria"
    if tcra_has_missing_identity(record):
        return "Completar número do TCRA"
    if tcra_has_missing_responsavel(record):
        return "Definir responsável e distribuir fila"
    if tcra_has_missing_orgao(record):
        return "Definir órgão"
    if operational_status == STATUS_CUMPRIDO:
        return "Conferir arquivamento"
    if operational_status == STATUS_SEM_VALIDADE:
        return "Revisar validade do termo"
    return "Acompanhar rotina"


def serialize_tcra_evento(evento: TcraEvento) -> dict[str, object]:
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


def serialize_tcra(record: Tcra) -> dict[str, object]:
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
        "eventos": [serialize_tcra_evento(evento) for evento in record.eventos],
    }


def latest_event(eventos: list[TcraEvento]) -> TcraEvento | None:
    if not eventos:
        return None
    return max(eventos, key=lambda item: (item.data_evento or date.min, item.sequence))


def build_event_summary_line(evento: TcraEvento, *, separator: str = " | ") -> str:
    parts = [_format_date(evento.data_evento), evento.tipo_evento or "Evento"]
    if evento.status_resultante:
        parts.append(evento.status_resultante)
    if evento.prazo_resultante is not None:
        parts.append(f"prazo {_format_date(evento.prazo_resultante)}")
    if getattr(evento, "protocolo", ""):
        parts.append(f"protocolo {evento.protocolo}")
    if getattr(evento, "documento_ref", ""):
        parts.append(f"doc {evento.documento_ref}")
    if evento.descricao:
        parts.append(evento.descricao)
    return separator.join(part for part in parts if part)


def format_latest_event_label(record: Tcra) -> str:
    evento = latest_event(list(record.eventos))
    if evento is None:
        return "Sem evento"
    parts: list[str] = []
    if evento.data_evento is not None:
        parts.append(_format_date(evento.data_evento))
    parts.append(evento.tipo_evento or "Evento")
    return " | ".join(parts)


def build_event_lines(
    eventos: list[TcraEvento],
    *,
    limit: int = 6,
    separator: str = " | ",
) -> list[str]:
    if not eventos:
        return ["Nenhum evento cadastrado."]
    lines: list[str] = []
    for evento in sorted(eventos, key=lambda item: (item.data_evento or date.min, item.sequence), reverse=True)[:limit]:
        lines.append(build_event_summary_line(evento, separator=separator))
    return lines


@dataclass(frozen=True)
class TcraRecordPanelData:
    title: str
    meta: str
    details: str
    timeline: str


def build_record_panel_data(record: Tcra, *, today: date) -> TcraRecordPanelData:
    operational_status = resolve_operational_status(record, today=today)
    operational_issues = resolve_operational_issues(record, today=today)
    consistency_issues = resolve_record_consistency_issues(record, today=today)
    priority_label = resolve_record_priority_label(record, today=today)
    next_action = resolve_record_next_action(record, today=today)
    sla_profile = resolve_tcra_sla_profile(record, today=today)
    flags: list[str] = []
    if tcra_is_mpsp_related(record):
        flags.append("MPSP")
    if tcra_has_prazo_vencido(record, today=today):
        flags.append("Prazo vencido")
    if tcra_has_relatorio_pendente(record, today=today):
        flags.append("Relatório pendente")
    if tcra_has_report_due_soon(record, today=today):
        flags.append("Próx. 30d")
    if tcra_has_missing_identity(record):
        flags.append("Sem número")
    if tcra_has_missing_responsavel(record):
        flags.append("Sem responsável")
    if tcra_has_missing_orgao(record):
        flags.append("Sem órgão")

    details_lines = [
        f"Prioridade: {priority_label}",
        f"Próxima ação: {next_action}",
        f"SLA operacional: {sla_profile.summary}",
        "",
        f"Processo: {record.numero_processo or '--'}",
        f"TCRA: {record.numero_tcra or '--'}",
        f"Local: {record.local or '--'}",
        f"Endereço: {record.endereco or '--'}",
        f"Bairro: {record.bairro or '--'}",
        f"Responsável: {record.responsavel_execucao or '--'}",
        f"Área: {record.area_m2 if record.area_m2 is not None else '--'}",
        f"Mudas: {record.numero_mudas_previsto if record.numero_mudas_previsto is not None else '--'}",
        f"Flags: {', '.join(flags) if flags else '--'}",
        "",
        "Pendências:",
        *(operational_issues[:3] or ("Nenhuma pendência prioritária.",)),
        "",
        "Qualidade:",
        *(consistency_issues[:3] or ("Cadastro coerente no recorte atual.",)),
    ]
    meta = " | ".join(
        [
            f"Status {operational_status}",
            f"Prazo {_format_date(record.prazo_final)}",
            f"Relatório {_format_date(record.data_proximo_relatorio)}",
            f"Órgão {format_orgao_context(record)}",
        ]
    )
    return TcraRecordPanelData(
        title=_stringify(record.numero_tcra or record.numero_processo or record.local) or "TCRA",
        meta=meta,
        details="\n".join(details_lines),
        timeline="\n".join(build_event_lines(list(record.eventos))),
    )


def neutral_row_background(*, row_index: int, is_dark_mode: bool) -> QColor:
    if is_dark_mode:
        return QColor("#0F172A") if row_index % 2 == 0 else QColor("#111827")
    return QColor("#FFFFFF") if row_index % 2 == 0 else QColor("#F8FAFC")


def neutral_row_foreground(*, is_dark_mode: bool) -> QColor:
    if is_dark_mode:
        return QColor("#E5E7EB")
    return QColor("#111827")


def status_badge_palette(record: Tcra, *, today: date, is_dark_mode: bool) -> tuple[QColor | None, QColor | None]:
    operational_status = resolve_operational_status(record, today=today)
    if is_dark_mode:
        if operational_status == STATUS_PRAZO_VENCIDO:
            return QColor("#5A2328"), QColor("#F8FAFC")
        if operational_status == STATUS_RELATORIO_PENDENTE:
            return QColor("#5B3D20"), QColor("#F8FAFC")
        if operational_status == STATUS_SEM_VALIDADE:
            return QColor("#5A3F24"), QColor("#F8FAFC")
        if operational_status == STATUS_CUMPRIDO:
            return QColor("#1F4B33"), QColor("#F8FAFC")
        if operational_status == STATUS_EM_ACOMPANHAMENTO:
            return QColor("#1E3A5F"), QColor("#F8FAFC")
        if operational_status == STATUS_SEM_STATUS:
            return QColor("#374151"), QColor("#F8FAFC")
        return None, None
    if operational_status == STATUS_PRAZO_VENCIDO:
        return QColor("#F8CDD3"), QColor("#881337")
    if operational_status == STATUS_RELATORIO_PENDENTE:
        return QColor("#FDE68A"), QColor("#92400E")
    if operational_status == STATUS_SEM_VALIDADE:
        return QColor("#FED7AA"), QColor("#9A3412")
    if operational_status == STATUS_CUMPRIDO:
        return QColor("#BBF7D0"), QColor("#166534")
    if operational_status == STATUS_EM_ACOMPANHAMENTO:
        return QColor("#BFDBFE"), QColor("#1E40AF")
    if operational_status == STATUS_SEM_STATUS:
        return QColor("#D1D5DB"), QColor("#374151")
    return None, None


def agenda_row_color(*, priority_rank: int, is_dark_mode: bool) -> QColor | None:
    if is_dark_mode:
        if priority_rank == 0:
            return QColor("#5A2328")
        if priority_rank == 1:
            return QColor("#5B3D20")
        if priority_rank == 2:
            return QColor("#5A5324")
        if priority_rank in {3, 4, 5, 6, 7}:
            return QColor("#233A58")
        return None
    if priority_rank == 0:
        return QColor("#FDE7E9")
    if priority_rank == 1:
        return QColor("#FFF1DD")
    if priority_rank == 2:
        return QColor("#FFF8CC")
    if priority_rank in {3, 4, 5, 6, 7}:
        return QColor("#EEF5FF")
    return None


def quality_row_color(*, severity_rank: int, is_dark_mode: bool) -> QColor:
    if is_dark_mode:
        return QColor("#5A2328") if severity_rank == 0 else QColor("#233A58")
    return QColor("#FDE7E9") if severity_rank == 0 else QColor("#EEF5FF")


def build_row_hint(record: Tcra, *, today: date) -> str:
    operational_status = resolve_operational_status(record, today=today)
    hints = [f"Status operacional: {operational_status}"]
    if tcra_has_prazo_vencido(record, today=today):
        hints.append("Prazo final vencido.")
    if tcra_has_relatorio_pendente(record, today=today):
        hints.append("Relatório pendente.")
    if tcra_has_report_due_soon(record, today=today):
        hints.append(f"Relatório previsto para os próximos {UPCOMING_REPORT_WINDOW_DAYS} dias.")
    if tcra_has_stale_movement(record, today=today):
        hints.append("Sem movimentação recente registrada.")
    if tcra_has_missing_identity(record):
        hints.append("Sem número de TCRA informado.")
    if tcra_has_missing_responsavel(record):
        hints.append("Sem responsável de execução.")
    if tcra_has_missing_orgao(record):
        hints.append("Sem órgão de acompanhamento informado.")
    sla_profile = resolve_tcra_sla_profile(record, today=today)
    if sla_profile.issue_key:
        hints.append(f"SLA: {sla_profile.summary}")
    return "\n".join(hints)


def build_event_timeline_text(eventos: list[TcraEvento]) -> str:
    if not eventos:
        return "Nenhum evento registrado para este termo."
    lines: list[str] = []
    for evento in sorted(eventos, key=lambda item: (item.data_evento or date.min, item.sequence), reverse=True):
        lines.append(build_event_summary_line(evento, separator=" - "))
    return "\n".join(lines)
