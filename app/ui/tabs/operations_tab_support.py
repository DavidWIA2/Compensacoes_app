from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.application.use_cases.persistence_monitoring import (
    PersistenceRecordOverviewReport,
    PersistenceStatusReport,
)
from app.application.use_cases.runtime_monitoring import RuntimeJobOverviewReport
from app.services.audit_service import AuditEvent, AuditOverview, audit_backup_available, audit_backup_path
from app.services.audit_service import format_audit_timestamp


@dataclass(frozen=True)
class RuntimeOverviewTextPayload:
    summary: str
    active: str
    recent: str
    cancel_enabled: bool


def build_context_text(session_path: str, overview: AuditOverview) -> str:
    session_label = session_path or "nenhuma"
    return "\n".join(
        [
            f"Sessão monitorada: {session_label}",
            (
                f"Última operação: {overview.latest_timestamp or '--'} | "
                f"{overview.latest_summary or 'Nenhuma operação registrada.'}"
            ),
        ]
    )


def build_visible_summary_text(overview: AuditOverview) -> str:
    if overview.action_counts:
        actions_text = " | ".join(f"{action}: {count}" for action, count in overview.action_counts)
    else:
        actions_text = "Nenhuma operação corresponde aos filtros atuais."
    return "\n".join(
        [
            (
                f"Resumo visível: {overview.total_events} operações | "
                f"{overview.events_today} hoje | "
                f"{overview.available_backups}/{overview.configured_backups} backups disponíveis"
            ),
            f"Ações visíveis: {actions_text}",
        ]
    )


def build_visible_counter_text(visible_count: int, total_count: int) -> str:
    return f"Mostrando {visible_count} de {total_count} operações"


def build_backup_status_text(event: AuditEvent) -> str:
    if audit_backup_available(event):
        return "Disponível"
    if audit_backup_path(event):
        return "Configurado"
    return "Sem backup"


def build_persistence_status_text(report: Optional[PersistenceStatusReport]) -> str:
    if report is None:
        return "Espelho local (SQLite): indisponível nesta sessão."

    status_map = {
        "sincronizado": "Sincronizado",
        "atencao": "Em atenção",
        "ausente": "Ainda não sincronizado",
        "indisponivel": "Indisponível",
    }
    status_text = status_map.get(report.status, report.status.title())
    synced_at = format_audit_timestamp(report.synced_at) if report.synced_at else "--"
    lines = [
        f"Espelho local (SQLite): {status_text} | Última sincronização: {synced_at}",
        (
            f"Registros espelhados: {report.mirrored_records}/{report.expected_records} | "
            f"Eventos auditados: {report.mirrored_audit_events}/{report.expected_audit_events} | "
            f"Plantios espelhados: {report.mirrored_plantios}"
        ),
    ]
    if report.issues:
        lines.append("Pendências: " + " | ".join(report.issues))
    return "\n".join(lines)


def format_sample_record(sample: object) -> str:
    status = str(getattr(sample, "compensado", "") or "").strip().upper() or "PENDENTE"
    return (
        f"Linha {int(getattr(sample, 'excel_row', 0) or 0)} | "
        f"{getattr(sample, 'av_tec', '') or '--'} | "
        f"{getattr(sample, 'uid', '') or '--'} | "
        f"{getattr(sample, 'microbacia', '') or '(sem microbacia)'} | "
        f"{status} | plantios {int(getattr(sample, 'plantio_count', 0) or 0)}"
    )


def build_record_overview_text(report: Optional[PersistenceRecordOverviewReport]) -> str:
    if report is None:
        return "Resumo local (SQLite): indisponível nesta sessão."

    if report.status == "indisponivel":
        return "Resumo local (SQLite): o espelho local não está disponível nesta sessão."

    if report.status == "ausente":
        return "Resumo local (SQLite): a sessão ainda não foi sincronizada para consultas locais."

    lines = [
        (
            f"Resumo local (SQLite): {report.total_records} registros | "
            f"{report.compensados_count} compensados | "
            f"{report.pendentes_count} pendentes | "
            f"{report.records_with_plantios_count} com plantios"
        ),
        (
            f"Qualidade do espelho: {report.records_without_microbacia_count} sem microbacia | "
            f"{report.records_without_coordinates_count} sem coordenadas"
        ),
    ]
    if report.top_microbacias:
        lines.append(
            "Microbacias em destaque: "
            + " | ".join(f"{label}: {count}" for label, count in report.top_microbacias)
        )
    if report.sample_records:
        lines.append(
            "Amostra do espelho: "
            + " | ".join(format_sample_record(sample) for sample in report.sample_records)
        )
    return "\n".join(lines)


def build_read_source_text(status: Optional[LocalRecordReadStatus]) -> str:
    if status is None or status.status == "indisponivel":
        return "Leitura operacional atual: sessão em memória."

    if status.uses_sqlite:
        lines = [
            (
                f"Leitura operacional atual: espelho local (SQLite) | "
                f"{status.filtered_records} registro(s) no recorte"
            )
        ]
        if status.strategy == "sqlite_query":
            lines.append("Modo de leitura local: consulta indexada.")
        if status.synced_at:
            lines.append(
                f"Última sincronização válida: {format_audit_timestamp(status.synced_at)}"
            )
        return "\n".join(lines)

    lines = [
        (
            f"Leitura operacional atual: sessão em memória | "
            f"{status.filtered_records} registro(s) no recorte"
        )
    ]
    if status.issues:
        lines.append("Motivos do fallback: " + " | ".join(status.issues))
    return "\n".join(lines)


def build_session_source_text(status: object | None) -> str:
    if status is None:
        return "Sessão carregada: aguardando leitura inicial da sessão."

    source = str(getattr(status, "source", "") or "").strip()
    strategy = str(getattr(status, "strategy", "") or "").strip()
    synced_at = str(getattr(status, "synced_at", "") or "").strip()
    filtered_records = int(getattr(status, "filtered_records", 0) or 0)
    issues = tuple(getattr(status, "issues", ()) or ())

    if source == "sqlite":
        lines = [f"Sessão carregada: espelho local (SQLite) com {filtered_records} registro(s)."]
        if strategy == "sqlite_snapshot":
            lines.append("Modo de carga da sessão: snapshot local validado.")
        if synced_at:
            lines.append(f"Última sincronização usada na carga: {format_audit_timestamp(synced_at)}")
        return "\n".join(lines)

    lines = [f"Sessão carregada: memória da sessão com {filtered_records} registro(s)."]
    if issues:
        lines.append("Motivos do fallback: " + " | ".join(str(issue) for issue in issues))
    return "\n".join(lines)


def build_mutation_sync_text(status: object | None) -> str:
    if status is None:
        return "Escrita local (SQLite): nenhuma mutação registrada nesta sessão."

    sync_status = str(getattr(status, "status", "") or "").strip()
    operation = str(getattr(status, "operation", "") or "").strip() or "mutação"
    strategy = str(getattr(status, "strategy", "") or "").strip()
    record_count = int(getattr(status, "record_count", 0) or 0)
    synced_at = str(getattr(status, "synced_at", "") or "").strip()
    issues = tuple(getattr(status, "issues", ()) or ())

    if sync_status == "sqlite":
        lines = [f"Escrita local (SQLite): {operation} sincronizada com {record_count} registro(s)."]
        if strategy == "incremental":
            lines.append("Modo de escrita local: sincronização incremental.")
        elif strategy == "snapshot_rebuild":
            lines.append("Modo de escrita local: reconstrução completa do snapshot.")
        elif strategy == "remote_snapshot_refresh":
            lines.append("Modo de escrita local: refresh completo do cache remoto.")
        if synced_at:
            lines.append(f"Última sincronização de escrita: {format_audit_timestamp(synced_at)}")
        if issues:
            lines.append("Observações: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    if sync_status == "falha":
        lines = [f"Escrita local (SQLite): falha na sincronização da operação {operation}."]
        if issues:
            lines.append("Detalhes: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    if sync_status == "indisponivel":
        lines = [f"Escrita local (SQLite): indisponível para a operação {operation}."]
        if issues:
            lines.append("Detalhes: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    return "Escrita local (SQLite): aguardando mutações da sessão."


def build_authoritative_write_text(status: object | None) -> str:
    if status is None:
        return "Escrita autoritativa: nenhuma mutação concluída nesta sessão."

    status_value = str(getattr(status, "status", "") or "").strip()
    operation = str(getattr(status, "operation", "") or "").strip() or "mutação"
    authority_source = str(getattr(status, "authority_source", "") or "").strip() or "session"
    sqlite_strategy = str(getattr(status, "sqlite_strategy", "") or "").strip()
    synced_at = str(getattr(status, "synced_at", "") or "").strip()
    record_count = int(getattr(status, "record_count", 0) or 0)
    finalized = bool(getattr(status, "finalized", False))
    rollback_applied = bool(getattr(status, "rollback_applied", False))
    issues = tuple(getattr(status, "issues", ()) or ())

    if status_value == "sqlite_primary":
        lines = [f"Escrita autoritativa: SQLite primário | {operation} confirmada no espelho de planilha."]
        lines.append(f"Fluxo persistido: {record_count} registro(s) projetados para a sessão.")
        if sqlite_strategy == "incremental":
            lines.append("Fluxo autoritativo: escrita local incremental antes do espelho de planilha.")
        elif sqlite_strategy == "snapshot_rebuild":
            lines.append("Fluxo autoritativo: reconstrução do snapshot local antes do espelho de planilha.")
        if finalized:
            lines.append("Identidade final reconciliada após a gravação no espelho de planilha.")
        if synced_at:
            lines.append(f"Última confirmação local: {format_audit_timestamp(synced_at)}")
        if issues:
            lines.append("Observações: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    if status_value == "remote_authoritative":
        lines = [f"Escrita autoritativa: Supabase | {operation} persistida na base oficial."]
        lines.append(f"Cache local atualizado para {record_count} registro(s) na sessão.")
        if sqlite_strategy == "remote_snapshot_refresh":
            lines.append("Fluxo autoritativo: sincronização completa do cache local após a RPC remota.")
        elif sqlite_strategy == "incremental":
            lines.append("Fluxo autoritativo: fallback incremental do cache local após a escrita remota.")
        elif sqlite_strategy == "snapshot_rebuild":
            lines.append("Fluxo autoritativo: reconstrução local do snapshot após a escrita remota.")
        if synced_at:
            lines.append(f"Última confirmação local: {format_audit_timestamp(synced_at)}")
        if issues:
            lines.append("Observações: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    if status_value == "sqlite_authoritative":
        lines = [f"Escrita autoritativa: SQLite | {operation} persistida localmente."]
        lines.append(f"Fluxo persistido: {record_count} registro(s) projetados para a sessão.")
        if sqlite_strategy == "incremental":
            lines.append("Fluxo autoritativo: escrita local incremental no SQLite.")
        elif sqlite_strategy == "snapshot_rebuild":
            lines.append("Fluxo autoritativo: reconstrução do snapshot local no SQLite.")
        if finalized:
            lines.append("Identidade final reconciliada após a mutação local.")
        if synced_at:
            lines.append(f"Última confirmação local: {format_audit_timestamp(synced_at)}")
        if issues:
            lines.append("Observações: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    if status_value == "session_authoritative":
        lines = [f"Escrita autoritativa: sessão em memória | {operation} persistida sem planilha externa."]
        if authority_source != "sqlite":
            lines.append("O SQLite não estava disponível como fonte primária desta mutação.")
        if synced_at:
            lines.append(f"Último status local conhecido: {format_audit_timestamp(synced_at)}")
        if issues:
            lines.append("Detalhes: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    if status_value == "session_fallback":
        lines = [f"Escrita autoritativa: fallback em memória | {operation} confirmada no espelho de planilha."]
        if authority_source != "sqlite":
            lines.append("O SQLite não estava apto para ser a fonte primária desta mutação.")
        if synced_at:
            lines.append(f"Último status local conhecido: {format_audit_timestamp(synced_at)}")
        if issues:
            lines.append("Motivos do fallback: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    if status_value == "rolled_back_after_excel_failure" or rollback_applied:
        lines = [f"Escrita autoritativa: falha ao espelhar {operation} na planilha externa; rollback local aplicado."]
        if issues:
            lines.append("Detalhes: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    if status_value == "excel_failure":
        lines = [f"Escrita autoritativa: falha ao aplicar {operation} na planilha externa."]
        if issues:
            lines.append("Detalhes: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    return "Escrita autoritativa: aguardando mutações da sessão."


def build_runtime_overview_texts(
    report: Optional[RuntimeJobOverviewReport],
) -> RuntimeOverviewTextPayload:
    if report is None or report.total_jobs <= 0:
        return RuntimeOverviewTextPayload(
            summary="Jobs da sessão: nenhuma operação executada ainda.",
            active="Jobs ativos: nenhum.",
            recent="Jobs recentes: nenhum.",
            cancel_enabled=False,
        )

    status_map = {
        "running": "Em execução",
        "completed": "Concluído",
        "failed": "Falhou",
        "cancelled": "Cancelado",
    }
    latest_status = status_map.get(report.latest_status, report.latest_status or "--")
    summary = "\n".join(
        [
            (
                f"Jobs da sessão: {report.total_jobs} | "
                f"{report.running_jobs} em execução | "
                f"{report.completed_jobs} concluídos | "
                f"{report.failed_jobs} falharam | "
                f"{report.cancelled_jobs} cancelados"
            ),
            (
                f"Último job: {latest_status} | "
                f"{report.latest_label or '--'} | "
                f"{report.latest_detail_message or 'Sem detalhes adicionais.'}"
            ),
        ]
    )

    if report.active_jobs:
        active_lines = []
        for job in report.active_jobs:
            progress_suffix = f" ({job.progress_value}/{job.total})" if job.total > 0 else ""
            active_lines.append(f"{job.label}{progress_suffix}: {job.detail_message or 'Em andamento'}")
        active = "Jobs ativos: " + " | ".join(active_lines)
    else:
        active = "Jobs ativos: nenhum."

    recent_lines = []
    for job in report.recent_jobs[:3]:
        status_text = status_map.get(job.status, job.status or "--")
        recent_lines.append(f"[{status_text}] {job.label} - {job.detail_message or 'Sem detalhes'}")
    recent = "Jobs recentes: " + (" | ".join(recent_lines) if recent_lines else "nenhum.")
    return RuntimeOverviewTextPayload(
        summary=summary,
        active=active,
        recent=recent,
        cancel_enabled=report.cancellable_jobs > 0,
    )
