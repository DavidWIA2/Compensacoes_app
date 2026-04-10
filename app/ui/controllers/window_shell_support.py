from __future__ import annotations

from dataclasses import dataclass

from app.config import display_corporate_email_local_part
from app.services.audit_service import format_audit_timestamp


COMPENSACOES_SEARCH_PLACEHOLDER = (
    "Buscar compensações por ofício, Av. Tec., endereço ou microbacia..."
)
TCRA_SEARCH_PLACEHOLDER = (
    "Buscar TCRAs por processo, local, órgão, evento ou observação..."
)


@dataclass(frozen=True)
class WindowChromeSnapshot:
    window_title: str
    file_label: str
    file_tooltip: str
    sync_label: str
    sync_tooltip: str
    records_label: str
    records_tooltip: str
    write_label: str
    write_tooltip: str
    selection_label: str
    selection_tooltip: str


def build_user_identity_label_text(access_session: object | None) -> str:
    environment = _environment_kind(access_session)
    user_email = str(getattr(access_session, "user_email", "") or "").strip()
    if user_email:
        identity = display_corporate_email_local_part(user_email) or user_email
        return f"Conta: {identity}"
    if environment == "production":
        return "Conta: autenticada"
    if environment == "demo":
        return "Conta: demonstração"
    return "Conta: local"


def build_user_identity_tooltip_text(access_session: object | None) -> str:
    environment = _environment_kind(access_session)
    user_email = str(getattr(access_session, "user_email", "") or "").strip()
    role_display = _role_display_name(access_session)
    environment_display = _environment_display_name(access_session)
    if user_email:
        lines = [f"Usuário autenticado: {user_email}.", f"Ambiente atual: {environment_display}."]
        if role_display:
            lines.append(f"Perfil de acesso: {role_display}.")
        if environment == "production":
            lines.append('Use "Sair" para encerrar a sessão e voltar à tela de login.')
        return "\n".join(lines)
    if environment == "demo":
        return 'Sessão de demonstração isolada ativa. Use "Sair" para voltar à tela de login.'
    return 'Sessão local de contingência ativa. Use "Sair" para voltar à tela de login.'


def _environment_kind(access_session: object | None) -> str:
    return str(getattr(access_session, "environment", "") or "").strip().lower()


def _environment_display_name(access_session: object | None) -> str:
    session_value = getattr(access_session, "environment_display_name", "")
    if str(session_value).strip():
        return str(session_value).strip()
    environment = _environment_kind(access_session)
    if environment == "production":
        return "Produção oficial"
    if environment == "demo":
        return "Demonstração isolada"
    return "Contingência local"


def _role_display_name(access_session: object | None) -> str:
    session_value = getattr(access_session, "role_display_name", "")
    if str(session_value).strip():
        return str(session_value).strip()
    role = str(getattr(access_session, "app_role", "") or "").strip().lower()
    if role == "admin":
        return "Administrador"
    if role == "viewer":
        return "Leitura"
    if role:
        return "Edição"
    return ""


def _has_active_session(path: str) -> bool:
    return bool(str(path or "").strip())


def _availability_label(availability: object | None) -> str:
    return str(getattr(availability, "display_label", "") or "").strip() or "local"


def _availability_tooltip(
    availability: object | None,
    *,
    has_active_session: bool,
    access_session: object | None = None,
) -> str:
    if not has_active_session:
        return "Nenhuma base ativa foi inicializada nesta sessão."

    detail_message = str(getattr(availability, "detail_message", "") or "").strip()
    environment = _environment_kind(access_session)
    if environment == "production":
        base_message = "Cache local sincronizado da base oficial do Supabase."
        return f"{base_message}\n{detail_message}" if detail_message else base_message
    if environment == "demo":
        base_message = "Base de demonstração isolada para testes."
        return f"{base_message}\n{detail_message}" if detail_message else base_message
    return detail_message or "Base local carregada."


def build_sync_label_text(
    remote_sync_status: object | None,
    *,
    access_session: object | None = None,
    has_active_session: bool,
    persistence_report: object | None = None,
) -> str:
    environment = _environment_kind(access_session)
    if not has_active_session:
        return "Sincronia: n/a"
    if environment == "demo":
        return "Sincronia: demo"
    if environment != "production":
        return "Sincronia: local"

    remote_status = str(getattr(remote_sync_status, "status", "") or "").strip()
    if remote_status == "refreshed":
        return "Sincronia: Supabase ok"
    if remote_status in {"failed", "unavailable"}:
        return "Sincronia: cache em uso"
    if remote_status == "deferred":
        return "Sincronia: pausada"
    if str(getattr(persistence_report, "synced_at", "") or "").strip():
        return "Sincronia: cache atualizado"
    return "Sincronia: aguardando"


def build_sync_tooltip_text(
    remote_sync_status: object | None,
    *,
    access_session: object | None = None,
    has_active_session: bool,
    persistence_report: object | None = None,
) -> str:
    if not has_active_session:
        return "Nenhuma sessão ativa para sincronizar."

    environment = _environment_kind(access_session)
    if environment == "demo":
        return "O modo demonstração usa uma base isolada e não depende da sincronia da produção."
    if environment != "production":
        return "A sincronia remota só é usada no ambiente de produção."

    remote_status_value = str(getattr(remote_sync_status, "status", "") or "").strip()
    synced_at = str(getattr(remote_sync_status, "synced_at", "") or "").strip()
    checked_at = str(getattr(remote_sync_status, "checked_at", "") or "").strip()
    workbook_name = str(getattr(remote_sync_status, "workbook_name", "") or "").strip() or "Base oficial"
    issues = tuple(
        str(item) for item in getattr(remote_sync_status, "issues", ()) or () if str(item).strip()
    )
    persistence_synced_at = str(getattr(persistence_report, "synced_at", "") or "").strip()

    if remote_status_value == "refreshed":
        lines = [f"Leitura remota confirmada no Supabase para {workbook_name}."]
        if synced_at:
            lines.append(f"Cache local sincronizado em {format_audit_timestamp(synced_at)}.")
        if checked_at:
            lines.append(f"Checagem remota concluída em {format_audit_timestamp(checked_at)}.")
        if issues:
            lines.append("Observações: " + " | ".join(issues))
        return "\n".join(lines)

    if remote_status_value == "deferred":
        lines = [
            "A sincronização remota foi pausada para não sobrescrever alterações pendentes no formulário."
        ]
        if issues:
            lines.append("Detalhes: " + " | ".join(issues))
        return "\n".join(lines)

    if remote_status_value in {"failed", "unavailable"}:
        lines = [
            "A última tentativa de sincronização com o Supabase falhou. O app continua operando com o cache local válido."
        ]
        if checked_at:
            lines.append(f"Última checagem remota: {format_audit_timestamp(checked_at)}.")
        if synced_at:
            lines.append(f"Última sincronização válida: {format_audit_timestamp(synced_at)}.")
        elif persistence_synced_at:
            lines.append(f"Última sincronização válida: {format_audit_timestamp(persistence_synced_at)}.")
        if issues:
            lines.append("Detalhes: " + " | ".join(issues))
        return "\n".join(lines)

    if persistence_synced_at:
        return (
            "A interface está usando o cache local já sincronizado com a produção.\n"
            f"Última sincronização válida: {format_audit_timestamp(persistence_synced_at)}."
        )

    return "Aguardando a primeira sincronização remota da produção nesta sessão."


def build_records_label_text(total_records: int, filtered_records: int) -> str:
    if total_records <= 0:
        return "Registros: 0"
    if filtered_records == total_records:
        return f"Registros: {total_records}"
    return f"Registros: {filtered_records} de {total_records}"


def _payload_value(payload: object | None, key: str, default: object) -> object:
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def build_integrity_tooltip_text(record_integrity_report: object | None) -> str:
    if record_integrity_report is None:
        return ""

    issue_count = int(_payload_value(record_integrity_report, "issue_count", 0) or 0)
    if issue_count <= 0:
        return ""

    return (
        "Integridade: "
        f"{int(_payload_value(record_integrity_report, 'error_count', 0) or 0)} erro(s) e "
        f"{int(_payload_value(record_integrity_report, 'warning_count', 0) or 0)} alerta(s)."
    )


def build_records_tooltip_text(
    search_text: str,
    record_integrity_report: object | None = None,
) -> str:
    normalized_search = str(search_text or "").strip()
    lines = [
        f"Busca atual: {normalized_search}"
        if normalized_search
        else "Resumo do recorte atualmente visível na tela."
    ]
    integrity_text = build_integrity_tooltip_text(record_integrity_report)
    if integrity_text:
        lines.append(integrity_text)
    return "\n".join(lines)


def _selected_summary(selected: object | None) -> str:
    if selected is None:
        return ""

    summary = str(getattr(selected, "av_tec", "") or "").strip()
    if not summary:
        summary = str(getattr(selected, "oficio_processo", "") or "").strip()
    if not summary:
        row_number = max(int(getattr(selected, "excel_row", 0) or 0) - 1, 0)
        summary = f"linha {row_number}" if row_number else "registro ativo"
    return summary


def build_selection_label_text(selected: object | None) -> str:
    summary = _selected_summary(selected)
    if not summary:
        return "Modo: novo cadastro"
    return f"Selecionado: {summary}"


def build_selection_tooltip_text(selected: object | None) -> str:
    if selected is None:
        return "Formulário pronto para iniciar um novo cadastro."
    return "Registro atualmente carregado no formulário."


def build_write_label_text(status: object | None, *, has_active_session: bool) -> str:
    if not has_active_session:
        return "Escrita: n/a"
    if status is None:
        return "Escrita: aguardando"

    status_value = str(getattr(status, "status", "") or "").strip()
    if status_value == "sqlite_authoritative":
        return "Escrita: SQLite"
    if status_value == "session_authoritative":
        return "Escrita: memória"
    if status_value == "remote_authoritative":
        return "Escrita: Supabase"
    if status_value == "sqlite_primary":
        return "Escrita: SQLite + cache"
    if status_value == "session_fallback":
        return "Escrita: fallback local"
    if status_value == "rolled_back_after_excel_failure":
        return "Escrita: rollback"
    if status_value == "excel_failure":
        return "Escrita: erro"
    return "Escrita: aguardando"


def build_write_tooltip_text(status: object | None, *, has_active_session: bool) -> str:
    if not has_active_session:
        return "Nenhum banco local carregado."
    if status is None:
        return "Nenhuma escrita autoritativa concluída nesta sessão."

    status_value = str(getattr(status, "status", "") or "").strip()
    operation = str(getattr(status, "operation", "") or "").strip() or "mutação"
    issues = tuple(getattr(status, "issues", ()) or ())
    lines = [f"Última operação: {operation}."]

    if status_value == "sqlite_authoritative":
        lines.append("Fluxo: SQLite como autoridade operacional do banco local.")
    elif status_value == "session_authoritative":
        lines.append("Fluxo: estado em memória mantido sem confirmação em espelho externo.")
    elif status_value == "remote_authoritative":
        lines.append("Fluxo: base oficial gravada no Supabase e cache local atualizado em seguida.")
    elif status_value == "sqlite_primary":
        lines.append("Fluxo: gravação local confirmada e refletida no cache operacional.")
    elif status_value == "session_fallback":
        lines.append("Fluxo: gravação preservada localmente após falha na atualização completa do cache.")
    elif status_value == "rolled_back_after_excel_failure":
        lines.append("Fluxo: falha no espelho externo com rollback aplicado no banco local.")
    elif status_value == "excel_failure":
        lines.append("Fluxo: falha ao confirmar a operação no espelho externo.")
    else:
        lines.append("Fluxo: aguardando novas operações.")

    if bool(getattr(status, "finalized", False)):
        lines.append("Identidade final reconciliada após a gravação.")
    if issues:
        lines.append("Observações: " + " | ".join(str(issue) for issue in issues))
    return "\n".join(lines)


def build_window_title(
    app_title: str,
    *,
    session_path: str,
    display_label: str,
    access_session: object | None = None,
    total_records: int,
    filtered_records: int,
) -> str:
    if not _has_active_session(session_path):
        return app_title

    environment = _environment_kind(access_session)
    if environment == "production":
        title = f"{app_title}[*] - Produção oficial sincronizada"
    elif environment == "demo":
        title = f"{app_title}[*] - Demonstração isolada"
    else:
        title = f"{app_title}[*] - Base local de contingência"
    if total_records > 0:
        title = f"{title} ({filtered_records}/{total_records})"
    return title


def build_window_chrome_snapshot(
    app_title: str,
    *,
    session_path: str,
    availability: object | None,
    access_session: object | None = None,
    remote_sync_status: object | None = None,
    persistence_report: object | None = None,
    record_integrity_report: object | None = None,
    total_records: int,
    filtered_records: int,
    search_text: str,
    selected: object | None,
    write_status: object | None,
) -> WindowChromeSnapshot:
    has_active_session = _has_active_session(session_path)
    display_label = _availability_label(availability)
    environment = _environment_kind(access_session)

    if not has_active_session:
        file_label = "Fonte: local"
    elif environment == "production":
        file_label = "Fonte: cache oficial"
    elif environment == "demo":
        file_label = "Fonte: demonstração isolada"
    else:
        file_label = f"Fonte: {display_label}"

    return WindowChromeSnapshot(
        window_title=build_window_title(
            app_title,
            session_path=session_path,
            display_label=display_label,
            access_session=access_session,
            total_records=total_records,
            filtered_records=filtered_records,
        ),
        file_label=file_label,
        file_tooltip=_availability_tooltip(
            availability,
            has_active_session=has_active_session,
            access_session=access_session,
        ),
        sync_label=build_sync_label_text(
            remote_sync_status,
            access_session=access_session,
            has_active_session=has_active_session,
            persistence_report=persistence_report,
        ),
        sync_tooltip=build_sync_tooltip_text(
            remote_sync_status,
            access_session=access_session,
            has_active_session=has_active_session,
            persistence_report=persistence_report,
        ),
        records_label=build_records_label_text(total_records, filtered_records),
        records_tooltip=build_records_tooltip_text(
            search_text,
            record_integrity_report=record_integrity_report,
        ),
        write_label=build_write_label_text(write_status, has_active_session=has_active_session),
        write_tooltip=build_write_tooltip_text(write_status, has_active_session=has_active_session),
        selection_label=build_selection_label_text(selected),
        selection_tooltip=build_selection_tooltip_text(selected),
    )
