from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from app.models.tcra import Tcra
from app.services.tcra_records_service import (
    AGENDA_SCOPE_30D,
    AGENDA_SCOPE_7D,
    AGENDA_SCOPE_HOJE,
    AGENDA_SCOPE_PENDENTES,
    AGENDA_SCOPE_VENCIDOS,
    QUICK_FILTER_ALERTAS,
    QUICK_FILTER_ALL,
    QUICK_FILTER_PROXIMOS,
    QUICK_FILTER_SEM_NUMERO,
    QUICK_FILTER_SEM_RESPONSAVEL,
    TcraAgendaItem,
    TcraQualityQueueItem,
    TcraRecordOverview,
    UPCOMING_REPORT_WINDOW_DAYS,
    apply_quick_filter,
    build_quality_queue,
    build_record_overview,
    build_work_agenda,
    compute_metrics,
    filter_tcras,
    operational_sort_key,
    resolve_quick_filter_count,
    tcra_has_report_due_soon,
)
from app.ui.tabs.tcra_tab_support import format_date


AGENDA_SCOPE_LABELS = {
    AGENDA_SCOPE_HOJE: "Hoje",
    AGENDA_SCOPE_7D: "7 dias",
    AGENDA_SCOPE_30D: "30 dias",
    AGENDA_SCOPE_VENCIDOS: "Vencidos",
    AGENDA_SCOPE_PENDENTES: "Pendentes",
}


@dataclass(frozen=True)
class TcraWorkspaceFilters:
    text: str = ""
    status: str = "Todos"
    selected_orgaos: tuple[str, ...] = ()
    selected_bairros: tuple[str, ...] = ()
    selected_year: str = "Todos"
    only_mpsp: bool = False
    only_relatorio_pendente: bool = False
    only_prazo_vencido: bool = False
    quick_filter_mode: str = QUICK_FILTER_ALL


@dataclass(frozen=True)
class TcraWorkspaceSnapshot:
    base_filtered_records: tuple[Tcra, ...]
    filtered_records: tuple[Tcra, ...]
    metrics: dict[str, object]
    base_metrics: dict[str, object]
    overview: TcraRecordOverview | None
    agenda_items: tuple[TcraAgendaItem, ...]
    agenda_total_count: int
    agenda_summary_text: str
    agenda_button_count: int
    agenda_view_all_enabled: bool
    agenda_view_all_text: str
    quality_items: tuple[TcraQualityQueueItem, ...]
    quality_total_count: int
    quality_summary_text: str
    quality_button_count: int
    quality_view_all_enabled: bool
    quality_view_all_text: str
    context_text: str
    radar_summary_text: str
    data_quality_text: str
    upcoming_summary_text: str
    upcoming_button_text: str
    upcoming_button_enabled: bool
    results_text: str
    quick_filter_labels: dict[str, str]


def _sort_records(records: Sequence[Tcra], *, today: date) -> tuple[Tcra, ...]:
    return tuple(sorted(records, key=lambda record: operational_sort_key(record, today=today)))


def _build_quick_filter_labels(records: Sequence[Tcra], *, today: date) -> dict[str, str]:
    return {
        QUICK_FILTER_ALL: f"Todos ({len(records)})",
        QUICK_FILTER_ALERTAS: f"Alertas ({resolve_quick_filter_count(records, QUICK_FILTER_ALERTAS, today=today)})",
        QUICK_FILTER_PROXIMOS: f"Próx. 30d ({resolve_quick_filter_count(records, QUICK_FILTER_PROXIMOS, today=today)})",
        QUICK_FILTER_SEM_NUMERO: f"Sem número ({resolve_quick_filter_count(records, QUICK_FILTER_SEM_NUMERO, today=today)})",
        QUICK_FILTER_SEM_RESPONSAVEL: (
            f"Sem responsável ({resolve_quick_filter_count(records, QUICK_FILTER_SEM_RESPONSAVEL, today=today)})"
        ),
    }


def _build_agenda_summary(
    agenda_items: Sequence[TcraAgendaItem],
    *,
    shown_count: int,
    agenda_scope: str,
) -> str:
    scope_label = AGENDA_SCOPE_LABELS.get(agenda_scope, "Trabalho")
    if not agenda_items:
        return f"Janela {scope_label}: nenhuma pendência no recorte atual."
    highlights = ", ".join(f"{item.prioridade_label}: {item.termo_label}" for item in agenda_items[:2])
    return f"Janela {scope_label}: {len(agenda_items)} prioridade(s) | mostrando {shown_count} | {highlights}"


def _build_quality_summary(
    quality_items: Sequence[TcraQualityQueueItem],
    *,
    shown_count: int,
) -> str:
    if not quality_items:
        return "Nenhuma pendência cadastral no recorte atual."
    critical_count = sum(1 for item in quality_items if item.severity_rank == 0)
    cadastro_count = len(quality_items) - critical_count
    highlights = ", ".join(f"{item.severity_label}: {item.termo_label}" for item in quality_items[:2])
    return (
        f"Qualidade cadastral: {len(quality_items)} item(ns) | mostrando {shown_count} | "
        f"{critical_count} críticos | {cadastro_count} cadastrais | {highlights}"
    )


def build_workspace_snapshot(
    all_records: Sequence[Tcra],
    *,
    filters: TcraWorkspaceFilters,
    search_index: dict[str, str],
    agenda_scope: str,
    agenda_expanded: bool,
    quality_expanded: bool,
    preview_limit: int,
    today: date,
) -> TcraWorkspaceSnapshot:
    base_filtered_records = _sort_records(
        filter_tcras(
            all_records,
            text=filters.text,
            status=filters.status,
            selected_orgaos=filters.selected_orgaos,
            selected_bairros=filters.selected_bairros,
            selected_year=filters.selected_year,
            only_mpsp=filters.only_mpsp,
            only_relatorio_pendente=filters.only_relatorio_pendente,
            only_prazo_vencido=filters.only_prazo_vencido,
            search_index=search_index,
            today=today,
        ),
        today=today,
    )
    filtered_records = _sort_records(
        apply_quick_filter(base_filtered_records, mode=filters.quick_filter_mode, today=today),
        today=today,
    )
    metrics = compute_metrics(filtered_records, today=today)
    base_metrics = compute_metrics(base_filtered_records, today=today)
    overview = build_record_overview(all_records, today=today) if all_records else None

    base_agenda_items = tuple(build_work_agenda(base_filtered_records, scope=agenda_scope, today=today, limit=0))
    base_quality_items = tuple(build_quality_queue(base_filtered_records, today=today, limit=0))
    agenda_all_items = tuple(build_work_agenda(filtered_records, scope=agenda_scope, today=today, limit=0))
    quality_all_items = tuple(build_quality_queue(filtered_records, today=today, limit=0))
    agenda_items = agenda_all_items if agenda_expanded or len(agenda_all_items) <= preview_limit else agenda_all_items[:preview_limit]
    quality_items = quality_all_items if quality_expanded or len(quality_all_items) <= preview_limit else quality_all_items[:preview_limit]

    upcoming_records = tuple(record for record in base_filtered_records if tcra_has_report_due_soon(record, today=today))
    upcoming_count = len(upcoming_records)
    if upcoming_records:
        upcoming_text = " | ".join(
            f"{record.numero_tcra or record.numero_processo or record.local} ({format_date(record.data_proximo_relatorio)})"
            for record in upcoming_records[:3]
        )
    else:
        upcoming_text = "--"

    if not all_records:
        context_text = "Banco local de TCRA sem registros."
        radar_summary_text = (
            f"Alertas 0 | Revisões 0 | Relatórios pendentes 0 | Próx. {UPCOMING_REPORT_WINDOW_DAYS}d 0"
        )
        data_quality_text = "Qualidade cadastral: sem registros."
    else:
        assert overview is not None
        context_text = (
            f"{overview.total_count} termos | {overview.ativos_count} ativos | "
            f"{base_metrics['count_alertas']} alertas | {overview.mpsp_relacionados_count} MPSP"
        )
        radar_summary_text = (
            f"Foco do recorte: {base_metrics['count_alertas']} alertas | "
            f"{base_metrics['count_relatorio_pendente']} relatórios pendentes | "
            f"{len(base_quality_items)} revisões | "
            f"Próx. {UPCOMING_REPORT_WINDOW_DAYS}d {upcoming_count}"
        )
        data_quality_text = (
            f"Qualidade: {base_metrics['count_sem_numero_tcra']} sem número | "
            f"{base_metrics['count_sem_responsavel']} sem responsável | "
            f"{base_metrics['count_sem_orgao']} sem órgão"
        )

    upcoming_button_text = f"Próx. {UPCOMING_REPORT_WINDOW_DAYS}d ({upcoming_count})" if upcoming_count else f"Próx. {UPCOMING_REPORT_WINDOW_DAYS}d"

    return TcraWorkspaceSnapshot(
        base_filtered_records=base_filtered_records,
        filtered_records=filtered_records,
        metrics=metrics,
        base_metrics=base_metrics,
        overview=overview,
        agenda_items=agenda_items,
        agenda_total_count=len(agenda_all_items),
        agenda_summary_text=_build_agenda_summary(
            agenda_all_items,
            shown_count=len(agenda_items),
            agenda_scope=agenda_scope,
        ),
        agenda_button_count=len(base_agenda_items),
        agenda_view_all_enabled=len(agenda_all_items) > preview_limit,
        agenda_view_all_text="Mostrar menos" if agenda_expanded else "Ver tudo",
        quality_items=quality_items,
        quality_total_count=len(quality_all_items),
        quality_summary_text=_build_quality_summary(
            quality_all_items,
            shown_count=len(quality_items),
        ),
        quality_button_count=len(base_quality_items),
        quality_view_all_enabled=len(quality_all_items) > preview_limit,
        quality_view_all_text="Mostrar menos" if quality_expanded else "Ver tudo",
        context_text=context_text,
        radar_summary_text=radar_summary_text,
        data_quality_text=data_quality_text,
        upcoming_summary_text=f"Próximos relatórios: {upcoming_text}",
        upcoming_button_text=upcoming_button_text,
        upcoming_button_enabled=bool(upcoming_count),
        results_text=(
            f"{len(filtered_records)} exibidos | {len(base_filtered_records)} no recorte base | "
            f"{len(all_records)} no banco"
        ),
        quick_filter_labels=_build_quick_filter_labels(base_filtered_records, today=today),
    )
