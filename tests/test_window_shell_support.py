from app.config import APP_WINDOW_TITLE
from app.application.use_cases.persistence_monitoring import PersistenceStatusReport
from app.ui.controllers.window_shell_support import (
    COMPENSACOES_SEARCH_PLACEHOLDER,
    TCRA_SEARCH_PLACEHOLDER,
    build_user_identity_label_text,
    build_user_identity_tooltip_text,
    build_window_chrome_snapshot,
)


def test_window_shell_support_builds_professional_window_chrome_snapshot():
    access_session = type("AccessSession", (), {"environment": "production"})()
    availability = type(
        "Availability",
        (),
        {
            "display_label": "Banco local",
            "detail_message": "Cache local sincronizado disponível em Banco local.",
        },
    )()
    write_status = type(
        "WriteStatus",
        (),
        {
            "status": "sqlite_primary",
            "operation": "import",
            "finalized": True,
            "issues": (),
        },
    )()
    selected = type(
        "SelectedRecord",
        (),
        {
            "av_tec": "AT-1",
            "oficio_processo": "123/2026",
            "excel_row": 2,
        },
    )()

    snapshot = build_window_chrome_snapshot(
        APP_WINDOW_TITLE,
        session_path="session://banco-local",
        availability=availability,
        access_session=access_session,
        remote_sync_status=type(
            "RemoteSyncStatus",
            (),
            {
                "status": "refreshed",
                "synced_at": "2026-04-07T12:00:00+00:00",
                "checked_at": "2026-04-07T12:01:00+00:00",
                "workbook_name": "Base oficial",
                "issues": (),
            },
        )(),
        persistence_report=PersistenceStatusReport(
            status="sincronizado",
            workbook_path="session://banco-local",
            synced_at="2026-04-07T12:00:00+00:00",
            mirrored_records=4,
            mirrored_plantios=1,
            mirrored_audit_events=0,
            expected_records=4,
            expected_audit_events=0,
        ),
        record_integrity_report=type(
            "IntegrityReport",
            (),
            {
                "issue_count": 2,
                "error_count": 1,
                "warning_count": 1,
            },
        )(),
        total_records=4,
        filtered_records=2,
        search_text="Gregorio",
        selected=selected,
        write_status=write_status,
    )

    assert snapshot.window_title.endswith("Produção sincronizada (2/4)")
    assert snapshot.file_label == "Fonte: cache sincronizado"
    assert "Supabase" in snapshot.file_tooltip
    assert snapshot.sync_label == "Sincronia: Supabase ok"
    assert "Base oficial" in snapshot.sync_tooltip
    assert snapshot.records_label == "Registros: 2 de 4"
    assert snapshot.records_tooltip == "Busca atual: Gregorio\nIntegridade: 1 erro(s) e 1 alerta(s)."
    assert snapshot.write_label == "Escrita: SQLite -> espelho"
    assert "Última mutação: import" in snapshot.write_tooltip
    assert "Identidade final reconciliada após gravação." in snapshot.write_tooltip
    assert snapshot.selection_label == "Selecionado: AT-1"
    assert snapshot.selection_tooltip == "Registro atualmente carregado no formulário."
    assert "ofício" in COMPENSACOES_SEARCH_PLACEHOLDER.lower()
    assert "órgão" in TCRA_SEARCH_PLACEHOLDER.lower()


def test_window_shell_support_distinguishes_remote_authoritative_writes():
    snapshot = build_window_chrome_snapshot(
        APP_WINDOW_TITLE,
        session_path="session://banco-local",
        availability=type("Availability", (), {"display_label": "Banco local", "detail_message": "ok"})(),
        access_session=type("AccessSession", (), {"environment": "production"})(),
        remote_sync_status=type(
            "RemoteSyncStatus",
            (),
            {
                "status": "failed",
                "synced_at": "2026-04-07T12:00:00+00:00",
                "checked_at": "2026-04-07T12:05:00+00:00",
                "issues": ("timeout",),
            },
        )(),
        persistence_report=PersistenceStatusReport(
            status="sincronizado",
            workbook_path="session://banco-local",
            synced_at="2026-04-07T12:00:00+00:00",
            mirrored_records=1,
            mirrored_plantios=0,
            mirrored_audit_events=0,
            expected_records=1,
            expected_audit_events=0,
        ),
        total_records=1,
        filtered_records=1,
        search_text="",
        selected=None,
        write_status=type(
            "WriteStatus",
            (),
            {
                "status": "remote_authoritative",
                "operation": "edit",
                "issues": (),
            },
        )(),
    )

    assert snapshot.write_label == "Escrita: Supabase"
    assert "Supabase como autoridade da produção" in snapshot.write_tooltip
    assert snapshot.sync_label == "Sincronia: offline"
    assert "cache local" in snapshot.sync_tooltip.lower()
    assert snapshot.records_tooltip == "Resumo do recorte atualmente visivel na tela."


def test_window_shell_support_builds_user_identity_text_and_tooltip():
    access_session = type(
        "AccessSession",
        (),
        {
            "environment": "production",
            "user_email": "david.oliveira@saocarlos.sp.gov.br",
            "app_role": "admin",
        },
    )()

    assert build_user_identity_label_text(access_session) == "Conta: david.oliveira"
    tooltip = build_user_identity_tooltip_text(access_session)
    assert "david.oliveira@saocarlos.sp.gov.br" in tooltip
    assert "admin" in tooltip
