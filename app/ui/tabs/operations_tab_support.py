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


def build_event_details_text(event: AuditEvent | None) -> str:
    if event is None:
        return (
            "Nenhuma operação selecionada.\n\n"
            "Selecione um item da linha do tempo para revisar a ação registrada, "
            "o backup disponível e o conteúdo técnico associado."
        )

    lines = [
        "Resumo da operação",
        f"- Data/Hora: {format_audit_timestamp(getattr(event, 'timestamp', ''))}",
        f"- Ação: {str(getattr(event, 'action', '') or '').strip().upper() or '--'}",
        f"- Síntese: {str(getattr(event, 'summary', '') or '').strip() or '--'}",
        f"- Backup: {'Disponível' if audit_backup_available(event) else 'Não disponível'}",
    ]

    backup_path = str(getattr(event, "backup_path", "") or "").strip()
    if backup_path:
        lines.append(f"- Caminho do backup: {backup_path}")

    metadata = getattr(event, "metadata", None)
    before = getattr(event, "before", None)
    after = getattr(event, "after", None)

    if metadata:
        lines.extend(
            [
                "",
                "Metadados",
                json_like_block(metadata),
            ]
        )
    if before is not None:
        lines.extend(
            [
                "",
                "Estado anterior",
                json_like_block(before),
            ]
        )
    if after is not None:
        lines.extend(
            [
                "",
                "Estado posterior",
                json_like_block(after),
            ]
        )
    return "\n".join(lines)


def build_no_results_details_text() -> str:
    return (
        "Nenhuma operação corresponde aos filtros atuais.\n\n"
        "Revise ação, backup e busca textual para ampliar o recorte do histórico."
    )


def json_like_block(payload: object) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2)


def _payload_value(payload: object | None, key: str, default: object) -> object:
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def build_status_highlights_text(
    *,
    access_session: object | None = None,
    remote_sync_status: object | None = None,
    persistence_report: Optional[PersistenceStatusReport] = None,
    session_source_status: object | None = None,
    authoritative_write_status: object | None = None,
    record_integrity_report: object | None = None,
    record_read_status: Optional[LocalRecordReadStatus] = None,
) -> str:
    chips: list[str] = []
    environment = str(getattr(access_session, "environment", "") or "").strip().lower()

    if environment == "production":
        remote_status = str(getattr(remote_sync_status, "status", "") or "").strip()
        if remote_status == "refreshed":
            chips.append("Sincronia: Supabase ok")
        elif remote_status in {"failed", "unavailable"}:
            chips.append("Sincronia: cache em uso")
        elif remote_status == "deferred":
            chips.append("Sincronia: pausada")
        elif persistence_report is not None and str(getattr(persistence_report, "synced_at", "") or "").strip():
            chips.append("Sincronia: cache atualizado")
        else:
            chips.append("Sincronia: aguardando")

    if persistence_report is not None:
        persistence_status = str(getattr(persistence_report, "status", "") or "").strip()
        persistence_map = {
            "sincronizado": "Cache: sincronizado",
            "atencao": "Cache: revisar",
            "ausente": "Cache: pendente",
            "indisponivel": "Cache: indisponível",
        }
        chips.append(persistence_map.get(persistence_status, f"Cache: {persistence_status or 'aguardando'}"))

    if session_source_status is not None:
        source = str(getattr(session_source_status, "source", "") or "").strip()
        strategy = str(getattr(session_source_status, "strategy", "") or "").strip()
        if source == "sqlite":
            if strategy == "sqlite_snapshot":
                chips.append("Sessão: cache local")
            else:
                chips.append("Sessão: cache local")
        elif source:
            chips.append("Sessão: memória")

    if record_read_status is not None:
        chips.append("Leitura: cache local" if record_read_status.uses_sqlite else "Leitura: memória")

    if authoritative_write_status is not None:
        write_status = str(getattr(authoritative_write_status, "status", "") or "").strip()
        write_map = {
            "remote_authoritative": "Escrita oficial: Supabase",
            "sqlite_primary": "Escrita oficial: SQLite",
            "sqlite_authoritative": "Escrita oficial: SQLite",
            "session_authoritative": "Escrita oficial: memória",
            "session_fallback": "Escrita: fallback local",
            "rolled_back_after_excel_failure": "Escrita: rollback",
            "excel_failure": "Escrita: revisar",
        }
        chips.append(write_map.get(write_status, "Escrita: aguardando"))

    if record_integrity_report is not None:
        issue_count = int(_payload_value(record_integrity_report, "issue_count", 0) or 0)
        error_count = int(_payload_value(record_integrity_report, "error_count", 0) or 0)
        if issue_count == 0:
            chips.append("Base: valida")
        elif error_count > 0:
            chips.append("Base: inconsistências")
        else:
            chips.append("Base: alertas")

    issues: list[str] = []
    if remote_sync_status is not None:
        issues.extend(str(item) for item in getattr(remote_sync_status, "issues", ()) or ())
    if persistence_report is not None:
        issues.extend(str(item) for item in getattr(persistence_report, "issues", ()) or ())
    if authoritative_write_status is not None:
        issues.extend(str(item) for item in getattr(authoritative_write_status, "issues", ()) or ())
    if record_integrity_report is not None and int(_payload_value(record_integrity_report, "issue_count", 0) or 0) > 0:
        issues.append("integridade da base com pendências")
    if record_read_status is not None:
        issues.extend(str(item) for item in getattr(record_read_status, "issues", ()) or ())
    if issues:
        chips.append("Atenção: ver detalhes")

    if not chips:
        return "Panorama operacional: aguardando uma base ativa."
    return "Panorama operacional: " + " | ".join(chips)


def build_remote_sync_text(
    remote_status: object | None,
    *,
    access_session: object | None = None,
    persistence_report: Optional[PersistenceStatusReport] = None,
) -> str:
    environment = str(getattr(access_session, "environment", "") or "").strip().lower()
    if environment != "production":
        if environment == "demo":
            return "Sincronia remota: não se aplica no ambiente de demonstração isolada."
        return "Sincronia remota: não se aplica fora da produção oficial."

    if remote_status is None:
        last_synced_at = str(getattr(persistence_report, "synced_at", "") or "").strip()
        if last_synced_at:
            return (
                "Sincronia remota: usando o cache local já sincronizado com a produção.\n"
                f"Última sincronização válida no cache: {format_audit_timestamp(last_synced_at)}"
            )
        return "Sincronia remota: aguardando a primeira checagem com o Supabase nesta sessão."

    status = str(getattr(remote_status, "status", "") or "").strip()
    synced_at = str(getattr(remote_status, "synced_at", "") or "").strip()
    checked_at = str(getattr(remote_status, "checked_at", "") or "").strip()
    workbook_name = str(getattr(remote_status, "workbook_name", "") or "").strip() or "Base oficial"
    record_count = int(getattr(remote_status, "record_count", 0) or 0)
    tcra_count = int(getattr(remote_status, "tcra_count", 0) or 0)
    issues = tuple(str(item) for item in getattr(remote_status, "issues", ()) or () if str(item).strip())

    if status == "refreshed":
        lines = [
            f"Sincronia remota: Supabase confirmado para {workbook_name}.",
            f"Cache local atualizado com {record_count} compensação(ões) e {tcra_count} TCRA(s).",
        ]
        if synced_at:
            lines.append(f"Última sincronização válida: {format_audit_timestamp(synced_at)}")
        if checked_at:
            lines.append(f"Última checagem remota: {format_audit_timestamp(checked_at)}")
        return "\n".join(lines)

    if status == "deferred":
        lines = ["Sincronia remota: pausada temporariamente para proteger alterações pendentes no formulário."]
        if issues:
            lines.append("Motivo: " + " | ".join(issues))
        return "\n".join(lines)

    if status in {"failed", "unavailable"}:
        lines = [
            "Sincronia remota: falha na última tentativa com o Supabase; o app segue operando com o cache local válido."
        ]
        if checked_at:
            lines.append(f"Última checagem remota: {format_audit_timestamp(checked_at)}")
        if synced_at:
            lines.append(f"Última sincronização válida no cache: {format_audit_timestamp(synced_at)}")
        elif persistence_report is not None and str(getattr(persistence_report, "synced_at", "") or "").strip():
            lines.append(
                "Última sincronização válida no cache: "
                + format_audit_timestamp(str(getattr(persistence_report, "synced_at", "") or "").strip())
            )
        if issues:
            lines.append("Detalhes: " + " | ".join(issues))
        return "\n".join(lines)

    if synced_at:
        return (
            "Sincronia remota: cache local sincronizado e pronto para uso.\n"
            f"Última sincronização válida: {format_audit_timestamp(synced_at)}"
        )

    return "Sincronia remota: aguardando nova sincronização com o Supabase."


def build_context_text(session_path: str, overview: AuditOverview) -> str:
    session_label = session_path or "nenhuma"
    return "\n".join(
        [
            f"Base monitorada: {session_label}",
            (
                f"Última operação registrada: {overview.latest_timestamp or '--'} | "
                f"{overview.latest_summary or 'Nenhuma operação registrada.'}"
            ),
        ]
    )


def build_visible_summary_text(overview: AuditOverview) -> str:
    if overview.action_counts:
        actions_text = " | ".join(f"{action}: {count}" for action, count in overview.action_counts)
    else:
        actions_text = "Nenhuma operação corresponde ao recorte atual."
    return "\n".join(
        [
            (
                f"Foco do recorte: {overview.total_events} operações | "
                f"{overview.events_today} hoje | "
                f"{overview.available_backups}/{overview.configured_backups} backups disponíveis"
            ),
            f"Operações em destaque: {actions_text}",
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
        return "Resumo local (SQLite): a base ainda não foi sincronizada para consultas locais."

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


def build_record_integrity_text(report: object | None) -> str:
    if report is None:
        return "Integridade da base: aguardando validação estrutural dos registros."

    issue_count = int(_payload_value(report, "issue_count", 0) or 0)
    error_count = int(_payload_value(report, "error_count", 0) or 0)
    warning_count = int(_payload_value(report, "warning_count", 0) or 0)
    analyzed_records = int(_payload_value(report, "analyzed_records", 0) or 0)
    affected_records = int(_payload_value(report, "affected_records_count", 0) or 0)
    summary = str(_payload_value(report, "summary", "") or "").strip()
    issues = tuple(_payload_value(report, "issues", ()) or ())

    if issue_count == 0:
        return (
            "Integridade da base: nenhuma inconsistência estrutural detectada.\n"
            f"Registros analisados: {analyzed_records}"
        )

    lines = [
        (
            f"Integridade da base: {error_count} erro(s) e {warning_count} alerta(s) "
            f"em {affected_records} registro(s)."
        )
    ]
    if summary:
        lines.append(summary)
    if issues:
        lines.append(
            "Exemplos: "
            + " | ".join(
                str(issue.get("message", issue)) if isinstance(issue, dict) else str(getattr(issue, "message", issue))
                for issue in issues[:3]
            )
        )
    return "\n".join(lines)


def build_read_source_text(status: Optional[LocalRecordReadStatus]) -> str:
    if status is None or status.status == "indisponivel":
        return "Leitura operacional: sessão em memória."

    if status.uses_sqlite:
        lines = [
            (
                f"Leitura operacional atual: espelho local (SQLite) | "
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
            f"Leitura operacional atual: sessão em memória | "
            f"{status.filtered_records} registro(s) no recorte"
        )
    ]
    if status.issues:
        lines.append("Motivos do fallback: " + " | ".join(status.issues))
    return "\n".join(lines)


def build_session_source_text(status: object | None) -> str:
    if status is None:
        return "Sessão carregada: aguardando leitura inicial da base."

    source = str(getattr(status, "source", "") or "").strip()
    strategy = str(getattr(status, "strategy", "") or "").strip()
    synced_at = str(getattr(status, "synced_at", "") or "").strip()
    filtered_records = int(getattr(status, "filtered_records", 0) or 0)
    issues = tuple(getattr(status, "issues", ()) or ())

    if source == "sqlite":
        lines = [f"Sessão carregada: espelho local (SQLite) com {filtered_records} registro(s)."]
        if strategy == "sqlite_snapshot":
            lines.append("Modo de carga: snapshot local validado.")
        if synced_at:
            lines.append(f"Última sincronização usada na carga: {format_audit_timestamp(synced_at)}")
        return "\n".join(lines)

    lines = [f"Sessão carregada: memória da sessão com {filtered_records} registro(s)."]
    if issues:
        lines.append("Motivos do fallback: " + " | ".join(str(issue) for issue in issues))
    return "\n".join(lines)


def build_mutation_sync_text(status: object | None) -> str:
    if status is None:
        return "Escrita local (SQLite): nenhuma operação registrada nesta sessão."

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
            lines.append("Modo de escrita local: atualização completa do cache remoto.")
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

    return "Escrita local (SQLite): aguardando novas operações."


def build_authoritative_write_text(status: object | None) -> str:
    if status is None:
        return "Escrita autoritativa: nenhuma operação concluída nesta sessão."

    status_value = str(getattr(status, "status", "") or "").strip()
    operation = str(getattr(status, "operation", "") or "").strip() or "operação"
    authority_source = str(getattr(status, "authority_source", "") or "").strip() or "session"
    sqlite_strategy = str(getattr(status, "sqlite_strategy", "") or "").strip()
    synced_at = str(getattr(status, "synced_at", "") or "").strip()
    record_count = int(getattr(status, "record_count", 0) or 0)
    finalized = bool(getattr(status, "finalized", False))
    rollback_applied = bool(getattr(status, "rollback_applied", False))
    issues = tuple(getattr(status, "issues", ()) or ())

    if status_value == "sqlite_primary":
        lines = [f"Escrita autoritativa: SQLite primário | {operation} confirmada no espelho externo."]
        lines.append(f"Fluxo persistido: {record_count} registro(s) projetados para a sessão.")
        if sqlite_strategy == "incremental":
            lines.append("Fluxo autoritativo: escrita local incremental antes do espelho externo.")
        elif sqlite_strategy == "snapshot_rebuild":
            lines.append("Fluxo autoritativo: reconstrução do snapshot local antes do espelho externo.")
        if finalized:
            lines.append("Identidade final reconciliada após a gravação no espelho externo.")
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
            lines.append("Fluxo autoritativo: atualização incremental do cache local após a escrita remota.")
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
        lines = [f"Escrita autoritativa: sessão em memória | {operation} persistida sem espelho externo."]
        if authority_source != "sqlite":
            lines.append("O SQLite não estava disponível como fonte primária desta operação.")
        if synced_at:
            lines.append(f"Último status local conhecido: {format_audit_timestamp(synced_at)}")
        if issues:
            lines.append("Detalhes: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    if status_value == "session_fallback":
        lines = [f"Escrita autoritativa: fallback em memória | {operation} confirmada no espelho externo."]
        if authority_source != "sqlite":
            lines.append("O SQLite não estava apto para ser a fonte primária desta operação.")
        if synced_at:
            lines.append(f"Último status local conhecido: {format_audit_timestamp(synced_at)}")
        if issues:
            lines.append("Motivos do fallback: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    if status_value == "rolled_back_after_excel_failure" or rollback_applied:
        lines = [f"Escrita autoritativa: falha ao espelhar {operation} no espelho externo; rollback local aplicado."]
        if issues:
            lines.append("Detalhes: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    if status_value == "excel_failure":
        lines = [f"Escrita autoritativa: falha ao aplicar {operation} no espelho externo."]
        if issues:
            lines.append("Detalhes: " + " | ".join(str(issue) for issue in issues))
        return "\n".join(lines)

    return "Escrita autoritativa: aguardando novas operações da sessão."


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
