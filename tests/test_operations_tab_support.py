from datetime import datetime, timezone

from app.application.use_cases.persistence_monitoring import (
    PersistenceRecordOverviewReport,
    PersistenceRecordSampleReport,
    PersistenceStatusReport,
)
from app.application.use_cases.runtime_monitoring import RuntimeJobOverviewReport, RuntimeJobSnapshot
from app.services.audit_service import AuditOverview
from app.ui.tabs.operations_tab_support import (
    build_authoritative_write_text,
    build_context_text,
    build_mutation_sync_text,
    build_persistence_status_text,
    build_record_overview_text,
    build_remote_sync_text,
    build_runtime_overview_texts,
    build_session_source_text,
    build_status_highlights_text,
    build_visible_summary_text,
)


def test_operations_tab_support_builds_overview_and_persistence_texts():
    now = datetime.now(timezone.utc).isoformat()
    overview = AuditOverview(
        total_events=2,
        events_today=1,
        available_backups=1,
        configured_backups=1,
        latest_summary="Registro alterado: AT-1",
        latest_timestamp="31/03/2026 09:00:00",
        action_counts=(("EDIT", 1), ("IMPORT", 1)),
    )
    persistence_report = PersistenceStatusReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at=now,
        mirrored_records=8,
        mirrored_plantios=2,
        mirrored_audit_events=2,
        expected_records=8,
        expected_audit_events=2,
    )
    record_overview = PersistenceRecordOverviewReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at=now,
        total_records=8,
        compensados_count=3,
        pendentes_count=5,
        records_with_plantios_count=2,
        records_without_microbacia_count=1,
        records_without_coordinates_count=4,
        top_microbacias=(("Gregorio", 5),),
        sample_records=(
            PersistenceRecordSampleReport(
                excel_row=2,
                uid="uid-1",
                av_tec="AT-1",
                microbacia="Gregorio",
                compensado="SIM",
                plantio_count=1,
            ),
        ),
    )
    session_status = type(
        "SessionStatus",
        (),
        {
            "source": "sqlite",
            "strategy": "sqlite_snapshot",
            "synced_at": now,
            "filtered_records": 8,
            "issues": (),
        },
    )()

    assert "Sessão monitorada: dummy.xlsx" in build_context_text("dummy.xlsx", overview)
    assert "Resumo visível: 2 operações" in build_visible_summary_text(overview)
    assert "EDIT: 1 | IMPORT: 1" in build_visible_summary_text(overview)
    assert "Espelho local (SQLite): Sincronizado" in build_persistence_status_text(persistence_report)
    assert "Registros espelhados: 8/8" in build_persistence_status_text(persistence_report)
    record_text = build_record_overview_text(record_overview)
    assert "Resumo local (SQLite): 8 registros" in record_text
    assert "Gregorio: 5" in record_text
    assert "Linha 2 | AT-1 | uid-1" in record_text
    session_text = build_session_source_text(session_status)
    assert "Sessão carregada: espelho local (SQLite) com 8 registro(s)." in session_text
    assert "snapshot local validado" in session_text
    highlights = build_status_highlights_text(
        access_session=type("AccessSession", (), {"environment": "production"})(),
        remote_sync_status=type("RemoteStatus", (), {"status": "refreshed"})(),
        persistence_report=persistence_report,
        session_source_status=session_status,
        record_read_status=type("ReadStatus", (), {"uses_sqlite": True, "issues": ()})(),
        authoritative_write_status=type("WriteStatus", (), {"status": "remote_authoritative", "issues": ()})(),
    )
    remote_sync = build_remote_sync_text(
        type(
            "RemoteStatus",
            (),
            {
                "status": "refreshed",
                "synced_at": now,
                "checked_at": now,
                "workbook_name": "Base oficial",
                "record_count": 8,
                "tcra_count": 18,
                "issues": (),
            },
        )(),
        access_session=type("AccessSession", (), {"environment": "production"})(),
        persistence_report=persistence_report,
    )
    assert "Supabase confirmado" in remote_sync
    assert "Cache: sincronizado" in highlights
    assert "Sincronia: Supabase ok" in highlights
    assert "Sessão: snapshot local" in highlights
    assert "Leitura: cache local" in highlights
    assert "Escrita oficial: Supabase" in highlights


def test_operations_tab_support_builds_write_and_runtime_texts():
    now = datetime.now(timezone.utc).isoformat()
    mutation_status = type(
        "MutationStatus",
        (),
        {
            "status": "sqlite",
            "operation": "edit",
            "strategy": "incremental",
            "synced_at": now,
            "record_count": 8,
            "issues": (),
        },
    )()
    write_status = type(
        "WriteStatus",
        (),
        {
            "status": "sqlite_primary",
            "operation": "edit",
            "authority_source": "sqlite",
            "sqlite_strategy": "incremental",
            "synced_at": now,
            "record_count": 8,
            "finalized": True,
            "rollback_applied": False,
            "issues": (),
        },
    )()
    runtime_report = RuntimeJobOverviewReport(
        total_jobs=1,
        running_jobs=1,
        completed_jobs=0,
        failed_jobs=0,
        cancelled_jobs=0,
        cancellable_jobs=1,
        latest_status="running",
        latest_label="runtime-sync",
        latest_detail_message="Sincronizando espelho local...",
        recent_jobs=(
            RuntimeJobSnapshot(
                name="runtime-sync",
                kind="sync",
                status="running",
                label="runtime-sync",
                detail_message="Sincronizando espelho local...",
                total=5,
                progress_value=2,
                cancellable=True,
                started_at=now,
            ),
        ),
        active_jobs=(
            RuntimeJobSnapshot(
                name="runtime-sync",
                kind="sync",
                status="running",
                label="runtime-sync",
                detail_message="Sincronizando espelho local...",
                total=5,
                progress_value=2,
                cancellable=True,
                started_at=now,
            ),
        ),
    )

    mutation_text = build_mutation_sync_text(mutation_status)
    assert "Escrita local (SQLite): edit sincronizada com 8 registro(s)." in mutation_text
    assert "Modo de escrita local: sincronização incremental." in mutation_text
    write_text = build_authoritative_write_text(write_status)
    assert "Escrita autoritativa: SQLite primário | edit confirmada no espelho de planilha." in write_text
    assert "Identidade final reconciliada" in write_text
    runtime_texts = build_runtime_overview_texts(runtime_report)
    assert "Sincronizando espelho local..." in runtime_texts.summary
    assert "runtime-sync (2/5)" in runtime_texts.active
    assert "Sincronizando espelho local..." in runtime_texts.recent
    assert runtime_texts.cancel_enabled is True


def test_operations_tab_support_describes_remote_authoritative_writes():
    now = datetime.now(timezone.utc).isoformat()
    remote_status = type(
        "WriteStatus",
        (),
        {
            "status": "remote_authoritative",
            "operation": "delete",
            "authority_source": "remote",
            "sqlite_strategy": "remote_snapshot_refresh",
            "synced_at": now,
            "record_count": 12,
            "finalized": False,
            "rollback_applied": False,
            "issues": (),
        },
    )()

    text = build_authoritative_write_text(remote_status)

    assert "Escrita autoritativa: Supabase | delete persistida na base oficial." in text
    assert "sincronização completa do cache local" in text.lower()


def test_operations_tab_support_describes_remote_sync_failures():
    now = datetime.now(timezone.utc).isoformat()
    persistence_report = PersistenceStatusReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at=now,
        mirrored_records=8,
        mirrored_plantios=2,
        mirrored_audit_events=2,
        expected_records=8,
        expected_audit_events=2,
    )

    text = build_remote_sync_text(
        type(
            "RemoteStatus",
            (),
            {
                "status": "failed",
                "synced_at": now,
                "checked_at": now,
                "issues": ("timeout",),
            },
        )(),
        access_session=type("AccessSession", (), {"environment": "production"})(),
        persistence_report=persistence_report,
    )

    assert "falha na última tentativa" in text.lower()
    assert "cache local" in text.lower()
    assert "timeout" in text
