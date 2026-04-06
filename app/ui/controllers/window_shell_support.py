from __future__ import annotations

from dataclasses import dataclass


COMPENSACOES_SEARCH_PLACEHOLDER = "Buscar (ofício, av. tec., endereço...)"
TCRA_SEARCH_PLACEHOLDER = "Buscar TCRA por processo, local, órgão, evento ou observação..."


@dataclass(frozen=True)
class WindowChromeSnapshot:
    window_title: str
    file_label: str
    file_tooltip: str
    records_label: str
    records_tooltip: str
    write_label: str
    write_tooltip: str
    selection_label: str
    selection_tooltip: str


def _has_active_session(path: str) -> bool:
    return bool(str(path or "").strip())


def _availability_label(availability: object | None) -> str:
    return str(getattr(availability, "display_label", "") or "").strip() or "local"


def _availability_tooltip(availability: object | None, *, has_active_session: bool) -> str:
    if not has_active_session:
        return "Banco SQLite local ainda nao foi inicializado."
    return str(getattr(availability, "detail_message", "") or "").strip() or "Banco local carregado."


def build_records_label_text(total_records: int, filtered_records: int) -> str:
    if total_records <= 0:
        return "Registros: 0"
    if filtered_records == total_records:
        return f"Registros: {total_records}"
    return f"Registros: {filtered_records} de {total_records}"


def build_records_tooltip_text(search_text: str) -> str:
    normalized_search = str(search_text or "").strip()
    if normalized_search:
        return f"Busca atual: {normalized_search}"
    return "Resumo do conjunto filtrado na tela."


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
        return "Formulário pronto para novo cadastro."
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
        return "Escrita: SQLite -> espelho"
    if status_value == "session_fallback":
        return "Escrita: memória -> espelho"
    if status_value == "rolled_back_after_excel_failure":
        return "Escrita: rollback"
    if status_value == "excel_failure":
        return "Escrita: erro"
    return "Escrita: aguardando"


def build_write_tooltip_text(status: object | None, *, has_active_session: bool) -> str:
    if not has_active_session:
        return "Nenhum banco local carregado."
    if status is None:
        return "Nenhuma escrita autoritativa concluída no banco local."

    status_value = str(getattr(status, "status", "") or "").strip()
    operation = str(getattr(status, "operation", "") or "").strip() or "mutação"
    issues = tuple(getattr(status, "issues", ()) or ())
    lines = [f"Última mutação: {operation}"]

    if status_value == "sqlite_authoritative":
        lines.append("Fluxo: SQLite como autoridade operacional do banco local.")
    elif status_value == "session_authoritative":
        lines.append("Fluxo: estado em memória mantido sem confirmação em planilha externa.")
    elif status_value == "remote_authoritative":
        lines.append("Fluxo: Supabase como autoridade da produção com cache SQLite sincronizado.")
    elif status_value == "sqlite_primary":
        lines.append("Fluxo: SQLite primário com espelho em planilha externa.")
    elif status_value == "session_fallback":
        lines.append("Fluxo: fallback em memória com confirmação em planilha externa.")
    elif status_value == "rolled_back_after_excel_failure":
        lines.append("Fluxo: falha no espelho de planilha com rollback aplicado no SQLite.")
    elif status_value == "excel_failure":
        lines.append("Fluxo: falha ao confirmar a mutação no espelho de planilha.")
    else:
        lines.append("Fluxo: aguardando novas mutações.")

    if bool(getattr(status, "finalized", False)):
        lines.append("Identidade final reconciliada após gravação.")
    if issues:
        lines.append("Observações: " + " | ".join(str(issue) for issue in issues))
    return "\n".join(lines)


def build_window_title(
    app_title: str,
    *,
    session_path: str,
    display_label: str,
    total_records: int,
    filtered_records: int,
) -> str:
    if not _has_active_session(session_path):
        return app_title

    title = f"{app_title}[*] - Banco local"
    if total_records > 0:
        title = f"{title} ({filtered_records}/{total_records})"
    return title


def build_window_chrome_snapshot(
    app_title: str,
    *,
    session_path: str,
    availability: object | None,
    total_records: int,
    filtered_records: int,
    search_text: str,
    selected: object | None,
    write_status: object | None,
) -> WindowChromeSnapshot:
    has_active_session = _has_active_session(session_path)
    display_label = _availability_label(availability)
    file_label = "Banco: local" if not has_active_session else f"Banco: {display_label}"

    return WindowChromeSnapshot(
        window_title=build_window_title(
            app_title,
            session_path=session_path,
            display_label=display_label,
            total_records=total_records,
            filtered_records=filtered_records,
        ),
        file_label=file_label,
        file_tooltip=_availability_tooltip(availability, has_active_session=has_active_session),
        records_label=build_records_label_text(total_records, filtered_records),
        records_tooltip=build_records_tooltip_text(search_text),
        write_label=build_write_label_text(write_status, has_active_session=has_active_session),
        write_tooltip=build_write_tooltip_text(write_status, has_active_session=has_active_session),
        selection_label=build_selection_label_text(selected),
        selection_tooltip=build_selection_tooltip_text(selected),
    )
