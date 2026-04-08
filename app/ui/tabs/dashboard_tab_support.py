from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence

from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.application.use_cases.persistence_monitoring import PersistenceRecordOverviewReport
from app.services.audit_service import format_audit_timestamp
from app.services.tcra_records_service import TcraAgendaItem, TcraRecordOverview


@dataclass(frozen=True)
class DashboardChartPayload:
    kind: str
    payload: dict[str, object]


@dataclass(frozen=True)
class DashboardExportContext:
    title: str
    kpi_lines: tuple[str, ...]
    filter_summary: str


def _extend_unique_labels(target: list[str], labels: Iterable[object]) -> None:
    for label in labels:
        normalized_label = str(label or "").strip()
        if normalized_label and normalized_label not in target:
            target.append(normalized_label)


def build_dashboard_micro_palette_keys(
    metrics: Dict[str, object],
    record_overview: Optional[PersistenceRecordOverviewReport],
) -> list[str]:
    keys: list[str] = []
    if record_overview is not None:
        _extend_unique_labels(
            keys,
            [label for label, _count in getattr(record_overview, "top_microbacias", ())],
        )
    _extend_unique_labels(
        keys,
        [label for label, _count in metrics.get("pend_micro_sorted", ())],
    )
    return keys


def build_compensation_chart_payload(
    metrics: Dict[str, object],
    *,
    is_dark: bool,
    micro_palette_keys: Sequence[str],
) -> dict[str, object]:
    return {
        "kind": "compensacoes",
        "is_dark": is_dark,
        "metrics": dict(metrics or {}),
        "micro_palette_keys": list(micro_palette_keys or []),
    }


def build_tcra_chart_payload(
    overview: Optional[TcraRecordOverview],
    *,
    is_dark: bool,
) -> dict[str, object]:
    if overview is None:
        return {
            "kind": "tcra",
            "is_dark": is_dark,
            "status_rows": [],
            "attention_rows": [],
        }

    em_acompanhamento = max(
        int(overview.ativos_count or 0)
        - int(overview.prazo_vencido_count or 0)
        - int(overview.relatorio_pendente_count or 0),
        0,
    )
    status_rows = [
        {"name": "Em acompanhamento", "value": em_acompanhamento, "color": "#1e88e5"},
        {"name": "Relatório pendente", "value": int(overview.relatorio_pendente_count or 0), "color": "#fb8c00"},
        {"name": "Prazo vencido", "value": int(overview.prazo_vencido_count or 0), "color": "#d32f2f"},
        {"name": "Cumpridos", "value": int(overview.cumpridos_count or 0), "color": "#2e7d32"},
    ]
    attention_rows = [
        {"label": "Alertas", "value": int(overview.alertas_count or 0), "color": "#d32f2f"},
        {"label": "Próx. 30d", "value": int(overview.upcoming_30d_count or 0), "color": "#fb8c00"},
        {"label": "Sem número", "value": int(overview.sem_numero_tcra_count or 0), "color": "#8e24aa"},
        {"label": "Sem responsável", "value": int(overview.sem_responsavel_count or 0), "color": "#6d4c41"},
        {"label": "MPSP", "value": int(overview.mpsp_relacionados_count or 0), "color": "#3949ab"},
    ]
    return {
        "kind": "tcra",
        "is_dark": is_dark,
        "status_rows": status_rows,
        "attention_rows": attention_rows,
    }


def build_local_overview_text(report: Optional[PersistenceRecordOverviewReport]) -> str:
    if report is None or report.status == "indisponivel":
        return "Cache local sincronizado: indisponível nesta sessão."

    if report.status == "ausente":
        return "Cache local sincronizado: a sessão ainda não foi sincronizada para leitura local."

    lines = [
        (
            f"Cache local sincronizado: {report.total_records} registro(s) | "
            f"{report.compensados_count} compensados | "
            f"{report.pendentes_count} pendentes | "
            f"{report.records_with_plantios_count} com plantios"
        ),
        (
            f"Qualidade dos dados: {report.records_without_microbacia_count} sem microbacia | "
            f"{report.records_without_coordinates_count} sem coordenadas"
        ),
    ]
    if report.top_microbacias:
        lines.append(
            "Top microbacias: "
            + " | ".join(f"{label}: {count}" for label, count in report.top_microbacias)
        )
    return "\n".join(lines)


def build_read_source_text(status: Optional[LocalRecordReadStatus]) -> str:
    if status is None or status.status == "indisponivel":
        return "Leitura operacional: sessão em memória."

    if status.uses_sqlite:
        lines = [
            (
                f"Leitura operacional: cache local sincronizado | "
                f"{status.filtered_records} registro(s) no recorte"
            )
        ]
        if status.strategy == "sqlite_query":
            lines.append("Modo de leitura: consulta indexada no cache.")
        if status.synced_at:
            lines.append(
                f"Última sincronização válida: {format_audit_timestamp(status.synced_at)}"
            )
        return "\n".join(lines)

    lines = [
        (
            f"Leitura operacional: sessão em memória | "
            f"{status.filtered_records} registro(s) no recorte"
        )
    ]
    if status.issues:
        lines.append("Motivos do fallback: " + " | ".join(status.issues))
    return "\n".join(lines)


def build_tcra_summary_text(overview: Optional[TcraRecordOverview]) -> str:
    if overview is None:
        return "TCRAs: nenhum termo carregado no cache sincronizado."
    return (
        f"Base TCRA: {overview.total_count} | "
        f"{overview.ativos_count} ativos | "
        f"{overview.mpsp_relacionados_count} MPSP | "
        f"{overview.sem_numero_tcra_count} sem número | "
        f"{overview.sem_responsavel_count} sem responsável"
    )


def build_tcra_agenda_text(
    agenda_items: Sequence[TcraAgendaItem],
    *,
    limit: int = 4,
) -> str:
    if not agenda_items:
        return "Agenda TCRA: sem pendências prioritárias."
    agenda_text = " | ".join(
        f"{item.prioridade_label}: {item.termo_label}"
        for item in list(agenda_items)[: max(limit, 0)]
    )
    return "Agenda TCRA: " + agenda_text


def build_dashboard_agenda_summary_text(
    metrics: Optional[Dict[str, object]],
    tcra_overview: Optional[TcraRecordOverview],
    tcra_agenda: Sequence[TcraAgendaItem],
    *,
    tcra_focus_limit: int = 2,
) -> str:
    metrics = dict(metrics or {})
    comp_pendentes = int(metrics.get("total_pendente", 0) or 0)
    comp_total = int(metrics.get("count_total", 0) or 0)
    comp_volume = f"Compensações: {comp_total} registro(s) | {comp_pendentes} pendentes no recorte atual."

    if tcra_overview is None:
        tcra_volume = "TCRAs: aguardando leitura."
    else:
        tcra_volume = (
            f"TCRAs: {tcra_overview.alertas_count} alerta(s) | "
            f"{tcra_overview.upcoming_30d_count} próximos | "
            f"{tcra_overview.sem_responsavel_count} sem responsável."
        )

    if tcra_agenda:
        foco = " | ".join(
            f"{item.prioridade_label}: {item.termo_label}"
            for item in list(tcra_agenda)[: max(tcra_focus_limit, 0)]
        )
        tcra_focus = f"Foco TCRA de hoje: {foco}"
    else:
        tcra_focus = "Foco TCRA de hoje: sem pendências prioritárias."

    return "\n".join([comp_volume, tcra_volume, tcra_focus])


def build_tcra_dashboard_export_context(
    overview: Optional[TcraRecordOverview],
    agenda_items: Sequence[TcraAgendaItem],
) -> DashboardExportContext:
    if overview is None:
        return DashboardExportContext(
            title="Painel TCRA",
            kpi_lines=("TCRAs: nenhum termo carregado no cache sincronizado.",),
            filter_summary="Cache sincronizado TCRA",
        )

    kpi_lines = (
        f"Total de TCRAs: {overview.total_count}",
        f"Ativos: {overview.ativos_count}",
        f"Cumpridos: {overview.cumpridos_count}",
        f"Alertas: {overview.alertas_count}",
        f"Próximos 30 dias: {overview.upcoming_30d_count}",
        f"Sem número TCRA: {overview.sem_numero_tcra_count}",
        f"Sem responsável: {overview.sem_responsavel_count}",
        f"Relacionados ao MPSP: {overview.mpsp_relacionados_count}",
    )
    if agenda_items:
        filter_summary = "Agenda TCRA: " + " | ".join(
            f"{item.prioridade_label}: {item.termo_label}"
            for item in list(agenda_items)[:3]
        )
    else:
        filter_summary = "Agenda TCRA: sem pendências prioritárias."
    return DashboardExportContext(
        title="Painel TCRA",
        kpi_lines=kpi_lines,
        filter_summary=filter_summary,
    )
