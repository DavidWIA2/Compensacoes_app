from datetime import datetime, timedelta, timezone

from app.ui.components.job_specs import BackgroundJobSpec
from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.application.use_cases.persistence_monitoring import (
    PersistenceRecordOverviewReport,
    PersistenceRecordSampleReport,
    PersistenceStatusReport,
)
from app.services.access_service import AccessEnvironment, AppAccessSession
from app.services.audit_service import AuditEvent


def make_event(*, event_id, timestamp, action, summary, backup_path="", metadata=None):
    return AuditEvent(
        event_id=event_id,
        timestamp=timestamp,
        workbook_path="C:/tmp/base.xlsx",
        action=action,
        summary=summary,
        backup_path=backup_path,
        metadata=dict(metadata or {}),
    )


def test_operations_tab_refreshes_cards_and_recent_events(ui_window_factory, monkeypatch, tmp_path):
    window = ui_window_factory()
    backup_path = tmp_path / "edit.xlsx"
    backup_path.write_text("snapshot", encoding="utf-8")
    now = datetime.now(timezone.utc)
    events = [
        make_event(
            event_id="evt-1",
            timestamp=now.isoformat(),
            action="edit",
            summary="Registro alterado: AT-1",
            backup_path=str(backup_path),
            metadata={"uid": "uid-1"},
        ),
        make_event(
            event_id="evt-2",
            timestamp=(now - timedelta(days=2)).isoformat(),
            action="import",
            summary="2 registro(s) importado(s)",
            metadata={"source_path": "importar.xlsx"},
        ),
    ]

    monkeypatch.setattr(window.audit_service, "list_events_for_workbook", lambda *_args, **_kwargs: events)
    monkeypatch.setattr(
        window.operations_controller.persistence_use_cases,
        "build_status_report",
        lambda *_args, **_kwargs: PersistenceStatusReport(
            status="sincronizado",
            workbook_path="dummy.xlsx",
            synced_at=now.isoformat(),
            mirrored_records=8,
            mirrored_plantios=2,
            mirrored_audit_events=2,
            expected_records=8,
            expected_audit_events=2,
        ),
    )
    monkeypatch.setattr(
        window.operations_controller.persistence_use_cases,
        "build_record_overview_report",
        lambda *_args, **_kwargs: PersistenceRecordOverviewReport(
            status="sincronizado",
            workbook_path="dummy.xlsx",
            synced_at=now.isoformat(),
            total_records=8,
            compensados_count=3,
            pendentes_count=5,
            records_with_plantios_count=2,
            records_without_microbacia_count=1,
            records_without_coordinates_count=4,
            top_microbacias=(("Gregorio", 5), ("Medeiros", 3)),
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
        ),
    )
    window.access_session = AppAccessSession(
        environment=AccessEnvironment.PRODUCTION,
        label="Produção",
        auth_mode="password",
        user_id="user-123",
        user_email="analista@prefeitura.sp.gov.br",
        supabase_url="https://yonvcnnkewzoqwnnmcdx.supabase.co",
        local_db_path="C:/tmp/producao.db",
        local_session_path="dummy.xlsx",
        app_role="editor",
        access_token="token",
        refresh_token="refresh-token",
    )
    window.records = [object()] * 8
    window.session_runtime.path = "dummy.xlsx"
    window._local_record_read_status = LocalRecordReadStatus(
        status="sqlite",
        source="sqlite",
        strategy="sqlite_query",
        workbook_path="dummy.xlsx",
        synced_at=now.isoformat(),
        mirrored_records=8,
        session_records=8,
        filtered_records=2,
    )
    window._local_session_source_status = LocalRecordReadStatus(
        status="sqlite",
        source="sqlite",
        strategy="sqlite_snapshot",
        workbook_path="dummy.xlsx",
        synced_at=now.isoformat(),
        mirrored_records=8,
        session_records=8,
        filtered_records=8,
    )
    window._local_mutation_sync_status = type(
        "MutationStatus",
        (),
        {
            "status": "sqlite",
            "operation": "edit",
            "strategy": "incremental",
            "synced_at": now.isoformat(),
            "record_count": 8,
            "issues": (),
        },
    )()
    window._authoritative_write_status = type(
        "WriteStatus",
        (),
        {
            "status": "sqlite_primary",
            "operation": "edit",
            "authority_source": "sqlite",
            "sqlite_strategy": "incremental",
            "synced_at": now.isoformat(),
            "record_count": 8,
            "finalized": True,
            "rollback_applied": False,
            "issues": (),
        },
    )()
    window._remote_snapshot_refresh_status = type(
        "RemoteStatus",
        (),
        {
            "status": "refreshed",
            "synced_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "workbook_name": "Base oficial",
            "record_count": 8,
            "tcra_count": 18,
            "issues": (),
        },
    )()

    window.refresh_operations_overview()

    assert window.tabs.count() == 4
    assert window.tabs.tabText(2) == "Operações"
    assert window.tabs.tabText(3) == "TCRAs"
    assert window.operations_tab.card_total.lbl_value.text() == "2"
    assert window.operations_tab.card_today.lbl_value.text() == "1"
    assert window.operations_tab.card_backups.lbl_value.text() == "1"
    assert window.operations_tab.card_latest.lbl_value.text() == "EDIT"
    assert window.operations_tab.table.rowCount() == 2
    assert window.operations_tab.selected_event.event_id == "evt-1"
    assert window.operations_tab.btn_open_backup.isEnabled() is True
    assert "Foco do recorte: 2 operações" in window.operations_tab.lbl_summary.text()
    assert "Panorama operacional:" in window.operations_tab.lbl_highlights.text()
    assert "Sincronia remota: Supabase confirmado" in window.operations_tab.lbl_remote_sync.text()
    assert "Espelho local (SQLite): Sincronizado" in window.operations_tab.lbl_persistence.text()
    assert "Registros espelhados: 8/8" in window.operations_tab.lbl_persistence.text()
    assert "Resumo local (SQLite): 8 registros" in window.operations_tab.lbl_records_overview.text()
    assert "Sessão carregada: espelho local (SQLite) com 8 registro(s)." in window.operations_tab.lbl_session_source.text()
    assert "Escrita autoritativa: SQLite primário | edit confirmada no espelho externo." in window.operations_tab.lbl_authoritative_write.text()
    assert "Identidade final reconciliada" in window.operations_tab.lbl_authoritative_write.text()
    assert "Escrita local (SQLite): edit sincronizada com 8 registro(s)." in window.operations_tab.lbl_mutation_sync.text()
    assert "Modo de escrita local: sincronização incremental." in window.operations_tab.lbl_mutation_sync.text()
    assert "espelho local (SQLite)" in window.operations_tab.lbl_read_source.text()
    assert "2 registro(s) no recorte" in window.operations_tab.lbl_read_source.text()
    assert "Gregorio: 5" in window.operations_tab.lbl_records_overview.text()
    assert "Linha 2 | AT-1 | uid-1" in window.operations_tab.lbl_records_overview.text()
    assert window.operations_tab.lbl_visible.text() == "Mostrando 2 de 2 operações"
    assert window.operations_tab.btn_sync_production.isEnabled() is True
    assert window.operations_tab.technical_details_frame.isHidden() is True

    window.operations_tab.filter_action.setCurrentText("EDIT")

    assert window.operations_tab.table.rowCount() == 1
    assert window.operations_tab.card_total.lbl_value.text() == "1"
    assert window.operations_tab.selected_event.event_id == "evt-1"

    window.operations_tab.filter_action.setCurrentText("Todas")
    window.operations_tab.search_input.setText("importar.xlsx")

    assert window.operations_tab.table.rowCount() == 1
    assert window.operations_tab.selected_event.event_id == "evt-2"
    assert window.operations_tab.btn_open_backup.isEnabled() is False
    assert window.operations_tab.lbl_visible.text() == "Mostrando 1 de 2 operações"
    window.close()


def test_operations_overview_uses_authoritative_total_record_count(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    captured = {}
    window.session_runtime.path = "dummy.xlsx"
    window.records = [object()]
    window._local_session_source_status = LocalRecordReadStatus(
        status="sqlite",
        source="sqlite",
        strategy="sqlite_snapshot",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-31T12:00:00+00:00",
        mirrored_records=6,
        session_records=1,
        filtered_records=6,
    )

    monkeypatch.setattr(window.audit_service, "list_events_for_workbook", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        window.operations_controller.persistence_use_cases,
        "build_status_report",
        lambda workbook_path, **kwargs: captured.update(
            {
                "workbook_path": workbook_path,
                "expected_records": kwargs["expected_records"],
                "expected_audit_events": kwargs["expected_audit_events"],
            }
        )
        or PersistenceStatusReport(
            status="ausente",
            workbook_path=workbook_path,
            synced_at="",
            mirrored_records=0,
            mirrored_plantios=0,
            mirrored_audit_events=0,
            expected_records=kwargs["expected_records"],
            expected_audit_events=kwargs["expected_audit_events"],
        ),
    )
    monkeypatch.setattr(
        window.operations_controller.persistence_use_cases,
        "build_record_overview_report",
        lambda workbook_path, **_kwargs: PersistenceRecordOverviewReport(
            status="ausente",
            workbook_path=workbook_path,
            synced_at="",
            total_records=0,
            compensados_count=0,
            pendentes_count=0,
            records_with_plantios_count=0,
            records_without_microbacia_count=0,
            records_without_coordinates_count=0,
        ),
    )

    window.refresh_operations_overview()

    assert captured == {
        "workbook_path": "dummy.xlsx",
        "expected_records": 6,
        "expected_audit_events": 0,
    }
    window.close()


def test_operations_overview_prefers_shell_monitoring_resolvers(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    now = datetime.now(timezone.utc)
    calls = {"status": 0, "overview": 0}
    window.session_runtime.path = "dummy.xlsx"
    window.records = [object()] * 3
    window._local_session_source_status = LocalRecordReadStatus(
        status="sqlite",
        source="sqlite",
        strategy="sqlite_snapshot",
        workbook_path="dummy.xlsx",
        synced_at=now.isoformat(),
        mirrored_records=3,
        session_records=3,
        filtered_records=3,
    )

    monkeypatch.setattr(window.audit_service, "list_events_for_workbook", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        window.shell_controller,
        "resolved_persistence_status_report",
        lambda **kwargs: calls.__setitem__("status", calls["status"] + 1)
        or PersistenceStatusReport(
            status="sincronizado",
            workbook_path="dummy.xlsx",
            synced_at=now.isoformat(),
            mirrored_records=3,
            mirrored_plantios=1,
            mirrored_audit_events=0,
            expected_records=3,
            expected_audit_events=kwargs["expected_audit_events"],
        ),
    )
    monkeypatch.setattr(
        window.shell_controller,
        "resolved_dashboard_record_overview",
        lambda **_kwargs: calls.__setitem__("overview", calls["overview"] + 1)
        or PersistenceRecordOverviewReport(
            status="sincronizado",
            workbook_path="dummy.xlsx",
            synced_at=now.isoformat(),
            total_records=3,
            compensados_count=1,
            pendentes_count=2,
            records_with_plantios_count=1,
            records_without_microbacia_count=0,
            records_without_coordinates_count=1,
        ),
    )

    window.refresh_operations_overview()

    assert calls == {"status": 1, "overview": 1}
    assert window.operations_tab.lbl_persistence.text().startswith("Espelho local (SQLite): Sincronizado")
    assert window.operations_tab.lbl_records_overview.text().startswith("Resumo local (SQLite): 3 registros")
    assert window.operations_tab.lbl_highlights.text().startswith("Panorama operacional:")
    window.close()


def test_operations_tab_buttons_route_actions_and_refresh_on_tab_change(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    calls = {"refresh": 0, "sync": 0, "history": 0, "rollback": 0, "backup": 0}

    monkeypatch.setattr(
        window.operations_controller,
        "refresh_overview",
        lambda *args, **kwargs: calls.__setitem__("refresh", calls["refresh"] + 1),
    )
    monkeypatch.setattr(
        window.operations_controller,
        "refresh_production_snapshot",
        lambda: calls.__setitem__("sync", calls["sync"] + 1),
    )
    monkeypatch.setattr(
        window.data_controller,
        "show_operation_history",
        lambda: calls.__setitem__("history", calls["history"] + 1),
    )
    monkeypatch.setattr(
        window.data_controller,
        "show_rollback_dialog",
        lambda: calls.__setitem__("rollback", calls["rollback"] + 1),
    )
    monkeypatch.setattr(
        window.operations_controller,
        "open_selected_backup",
        lambda: calls.__setitem__("backup", calls["backup"] + 1),
    )

    window.tabs.setCurrentWidget(window.operations_tab)
    window.operations_tab.btn_open_backup.setEnabled(True)
    window.operations_tab.btn_sync_production.setEnabled(True)
    window.operations_tab.btn_refresh.click()
    window.operations_tab.btn_sync_production.click()
    window.operations_tab.btn_history.click()
    window.operations_tab.btn_rollback.click()
    window.operations_tab.btn_open_backup.click()

    assert calls["refresh"] >= 2
    assert calls["sync"] == 1
    assert calls["history"] == 1
    assert calls["rollback"] == 1
    assert calls["backup"] == 1
    window.close()


def test_operations_tab_shows_runtime_jobs_and_cancel_action(ui_window_factory):
    window = ui_window_factory()
    calls = []

    class FakeSignal:
        def __init__(self):
            self._handlers = []

        def connect(self, handler):
            self._handlers.append(handler)

        def disconnect(self, handler=None):
            if handler is None:
                self._handlers.clear()
                return
            self._handlers = [current for current in self._handlers if current is not handler]

        def emit(self, *args, **kwargs):
            for handler in list(self._handlers):
                handler(*args, **kwargs)

    class FakeWorker:
        def __init__(self):
            self.finished = FakeSignal()
            self._running = False

        def start(self):
            self._running = True

        def isRunning(self):
            return self._running

    worker = FakeWorker()
    window.start_background_job(
        BackgroundJobSpec(
            name="runtime-sync",
            worker=worker,
            busy_message="Sincronizando espelho local...",
            total=5,
            cancellable=True,
            cancel_callback=lambda: calls.append("cancel"),
        )
    )

    window.operations_controller.refresh_runtime_overview()

    assert any(job.name == "runtime-sync" for job in window.list_runtime_jobs(limit=10))
    assert "Sincronizando espelho local..." in window.operations_tab.lbl_runtime_summary.text()
    assert "Sincronizando espelho local..." in window.operations_tab.lbl_runtime_active.text()
    assert window.operations_tab.btn_cancel_runtime.isEnabled() is True

    window.operations_tab.btn_cancel_runtime.click()

    assert calls == ["cancel"]

    window.mark_job_completed("runtime-sync", "Espelho sincronizado.")
    worker._running = False
    worker.finished.emit()
    window.end_busy_operation("Espelho sincronizado.")
    window.operations_controller.refresh_runtime_overview()

    assert "Espelho sincronizado." in window.operations_tab.lbl_runtime_summary.text()
    assert "runtime-sync" not in window.operations_tab.lbl_runtime_active.text()
    assert "Espelho sincronizado." in window.operations_tab.lbl_runtime_recent.text()
    assert window.operations_tab.btn_cancel_runtime.isEnabled() is False
    window.close()


def test_operations_tab_can_toggle_technical_details(ui_window_factory):
    window = ui_window_factory()

    assert window.operations_tab.technical_details_frame.isVisible() is False
    assert window.operations_tab.btn_toggle_details.text() == "Ver diagnóstico técnico"

    window.operations_tab.btn_toggle_details.click()

    assert window.operations_tab.technical_details_frame.isHidden() is False
    assert window.operations_tab.btn_toggle_details.text() == "Ocultar diagnóstico"

    window.operations_tab.btn_toggle_details.click()

    assert window.operations_tab.technical_details_frame.isHidden() is True
    assert window.operations_tab.btn_toggle_details.text() == "Ver diagnóstico técnico"
    window.close()



