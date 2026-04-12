from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from app.models.tcra import Tcra
from app.services.tcra_records_service import resolve_operational_issues, resolve_operational_status


def _stringify(value: object) -> str:
    return str(value or "").strip()


def _format_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value is not None else "--"


def _record_label(record: Tcra) -> str:
    return _stringify(record.numero_tcra or record.numero_processo or record.local or record.uid) or "TCRA"


def build_tcra_document_text(record: Tcra, *, kind: str = "cobranca", today: date | None = None) -> str:
    current_day = today or date.today()
    normalized_kind = _stringify(kind).lower() or "cobranca"
    title_by_kind = {
        "cobranca": "Minuta de cobrança de TCRA",
        "oficio": "Minuta de ofício de acompanhamento",
        "resumo": "Resumo executivo de TCRA",
    }
    title = title_by_kind.get(normalized_kind, title_by_kind["cobranca"])
    issues = resolve_operational_issues(record, today=current_day)
    recent_events = sorted(record.eventos, key=lambda item: (item.data_evento or date.min, item.sequence), reverse=True)[:5]

    lines = [
        title,
        f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "",
        f"Termo: {_record_label(record)}",
        f"Processo: {_stringify(record.numero_processo) or '--'}",
        f"Local: {_stringify(record.local or record.endereco) or '--'}",
        f"Bairro: {_stringify(record.bairro) or '--'}",
        f"Órgão de acompanhamento: {_stringify(record.orgao_acompanhamento) or '--'}",
        f"Responsável: {_stringify(record.responsavel_execucao) or '--'}",
        f"Status operacional: {resolve_operational_status(record, today=current_day)}",
        f"Prazo final: {_format_date(record.prazo_final)}",
        f"Próximo relatório: {_format_date(record.data_proximo_relatorio)}",
        "",
        "Pendências principais:",
        *(f"- {issue}" for issue in (issues or ("Nenhuma pendência prioritária no recorte atual.",))),
        "",
        "Eventos recentes:",
    ]
    if recent_events:
        for evento in recent_events:
            evidence = " | ".join(
                part
                for part in (
                    f"protocolo {_stringify(getattr(evento, 'protocolo', ''))}" if getattr(evento, "protocolo", "") else "",
                    f"doc {_stringify(getattr(evento, 'documento_ref', ''))}" if getattr(evento, "documento_ref", "") else "",
                )
                if part
            )
            suffix = f" | {evidence}" if evidence else ""
            lines.append(
                f"- {_format_date(evento.data_evento)} | {_stringify(evento.tipo_evento) or 'Evento'} | "
                f"{_stringify(evento.descricao) or '--'}{suffix}"
            )
    else:
        lines.append("- Nenhum evento cadastrado.")

    if normalized_kind == "cobranca":
        lines.extend(
            [
                "",
                "Texto base:",
                (
                    "Solicitamos atualizacao sobre o cumprimento das obrigacoes do TCRA acima identificado, "
                    "com envio de relatório, comprovantes e documentos de protocolo pertinentes."
                ),
            ]
        )
    elif normalized_kind == "oficio":
        lines.extend(
            [
                "",
                "Texto base:",
                (
                    "Encaminhamos o resumo do acompanhamento do TCRA para ciencia e providencias cabiveis, "
                    "especialmente quanto aos prazos e pendências indicados."
                ),
            ]
        )
    else:
        lines.extend(["", f"Serviços exigidos: {_stringify(record.servicos_exigidos) or '--'}"])

    return "\n".join(lines).strip() + "\n"


def write_tcra_document(path: str | Path, record: Tcra, *, kind: str = "cobranca", today: date | None = None) -> None:
    target = Path(path)
    target.write_text(build_tcra_document_text(record, kind=kind, today=today), encoding="utf-8")
