import os

from app.config import SEARCH_FILTER_DEBOUNCE_MS
from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.models.compensacao import Compensacao
from app.services.app_settings import AppSettings


class MemorySettings:
    def __init__(self):
        self._data = {}

    def value(self, key, default=None):
        return self._data.get(key, default)

    def setValue(self, key, value):
        self._data[key] = value

    def remove(self, key):
        self._data.pop(key, None)


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "Gregorio",
        "compensado": "",
        "endereco_plantio": "",
        "latitude": "-22.01",
        "longitude": "-47.89",
        "uid": "workflow-uid-1",
    }
    base.update(overrides)
    return Compensacao(**base)


def test_edit_workflow_persists_form_changes_and_reload(ui_window_factory, monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda path: True if path == "dummy.xlsx" else real_exists(path))

    window = ui_window_factory()
    window.session_runtime.path = "dummy.xlsx"
    window.records = [make_record()]
    window.filtered_records = list(window.records)
    monkeypatch.setattr(window, "_run_map_js", lambda *args, **kwargs: None)

    window._update_ui_after_load()

    index = window.data_tab.proxy.index(0, 0)
    window._on_table_clicked(index)

    executed = {}
    refreshed = []
    monkeypatch.setattr(
        window.form_controller.persistence,
        "prepare_update",
        lambda *args, **kwargs: type(
            "Preparation",
            (),
            {
                "base_records": tuple(window.records),
                "selected_record": window.selected,
                "effective_record": None,
                "duplicate_row": None,
                "issues": (),
            },
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.persistence,
        "execute_edit",
        lambda record, **kwargs: executed.update({"record": record, **kwargs})
        or type(
            "WriteResult",
            (),
            {
                "status": type(
                    "Status",
                    (),
                    {
                        "status": "sqlite",
                        "operation": "edit",
                        "strategy": "incremental",
                        "issues": (),
                        "uses_sqlite": True,
                    },
                )(),
                "write_status": type(
                    "WriteStatus",
                    (),
                    {"status": "sqlite_authoritative", "operation": "edit", "issues": (), "finalized": False},
                )(),
                "records": (record,),
                "excel_result": None,
                "rollback_issues": (),
                "finalized": False,
            },
        )(),
    )
    monkeypatch.setattr(window, "reload", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("reload nao deveria ser usado")))
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)

    window.data_tab.chk_compensado.setChecked(True)
    window.data_tab.in_end_plantio.setText("Rua Plantio Nova")

    window.save_edit()

    assert executed["record"].endereco_plantio == "Rua Plantio Nova"
    assert executed["record"].compensado == "SIM"
    assert executed["authoritative_records"][0].uid == "workflow-uid-1"
    assert window._local_mutation_sync_status is not None
    assert window._local_mutation_sync_status.operation == "edit"
    assert window._local_mutation_sync_status.strategy == "incremental"
    assert len(refreshed) == 1
    window.close()


def test_form_undo_redo_tracks_dirty_state(ui_window_factory, monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda path: True if path == "dummy.xlsx" else real_exists(path))

    window = ui_window_factory()
    window.session_runtime.path = "dummy.xlsx"
    record = make_record(uid="workflow-uid-2")
    window.selected = record
    window._fill_form(record)

    assert window.form_state_label.text() == "Sem alterações"
    assert window.data_tab.form_group.title() == "Cadastro / Edição"
    assert window.data_tab.btn_save_edit.isEnabled() is False

    window.data_tab.in_oficio.setText("999/2026")

    assert window.form_state_label.text() == "Alterações pendentes"
    assert window.data_tab.form_group.title().endswith("*")
    assert window.data_tab.btn_save_edit.isEnabled() is True
    window.close()

    window.form_controller.undo()

    assert window.data_tab.in_oficio.text() == "123/2026"
    assert window.form_state_label.text() == "Sem alterações"
    assert window.data_tab.btn_save_edit.isEnabled() is False

    window.form_controller.redo()

    assert window.data_tab.in_oficio.text() == "999/2026"
    assert window.form_state_label.text() == "Alterações pendentes"
    assert window.data_tab.btn_save_edit.isEnabled() is True


def test_table_selection_can_cancel_discarding_pending_changes(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    window.records = [
        make_record(uid="workflow-uid-3"),
        make_record(excel_row=3, oficio_processo="456/2026", av_tec="AT-2", uid="workflow-uid-4"),
    ]
    window.filtered_records = list(window.records)
    window.data_tab.table_model.update_data(window.filtered_records)
    window.selected = window.records[0]
    window._fill_form(window.selected)
    window.data_tab.in_oficio.setText("ALTERADO")

    second_index = window.data_tab.proxy.index(1, 0)
    monkeypatch.setattr(window.form_controller, "has_pending_changes", lambda: True)
    monkeypatch.setattr(window.form_controller, "confirm_discard_changes", lambda action: False)

    window._on_table_clicked(second_index)

    assert window.selected.uid == "workflow-uid-3"
    assert window.data_tab.in_oficio.text() == "ALTERADO"
    window.close()


def test_table_selection_can_hydrate_selected_record_from_sqlite_detail(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    stale_record = make_record(uid="workflow-uid-10", endereco="Sessao", endereco_plantio="", compensado="")
    fresh_record = make_record(
        uid="workflow-uid-10",
        endereco="SQLite",
        endereco_plantio="Plantio SQLite",
        compensado="SIM",
    )
    window.records = [stale_record]
    window.filtered_records = list(window.records)
    window.data_tab.table_model.update_data(window.filtered_records)

    monkeypatch.setattr(
        window.shell_controller.local_record_queries,
        "resolve_selected_record",
        lambda workbook_path, **kwargs: type(
            "SelectionResult",
            (),
            {"record": fresh_record},
        )(),
    )

    index = window.data_tab.proxy.index(0, 0)
    window._on_table_clicked(index)

    assert window.selected is fresh_record
    assert window.data_tab.in_end.text() == "SQLite"
    assert window.data_tab.in_end_plantio.text() == "Plantio SQLite"
    assert window.data_tab.chk_compensado.isChecked() is True
    window.close()


def test_table_selection_rebinds_runtime_persistence_service_after_swap(ui_window_factory, tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("stub", encoding="utf-8")
    stat_result = workbook_path.stat()
    window = ui_window_factory()
    stale_record = make_record(uid="workflow-uid-11", endereco="Sessao")
    fresh_record = make_record(uid="workflow-uid-11", endereco="SQLite Runtime", compensado="SIM")
    window.session_runtime.path = str(workbook_path)
    window.records = [stale_record]
    window.filtered_records = list(window.records)
    window.data_tab.table_model.update_data(window.filtered_records)

    class SwappedPersistenceService:
        def get_workbook_snapshot_summary(self, workbook_path):
            return type(
                "SnapshotSummary",
                (),
                {
                    "workbook_path": workbook_path,
                    "synced_at": "2026-03-31T12:00:00+00:00",
                    "record_count": 1,
                    "source_mtime_ns": int(stat_result.st_mtime_ns),
                    "source_size": int(stat_result.st_size),
                },
            )()

        def find_record_by_uid_for_workbook(self, workbook_path, uid):
            return fresh_record if uid == "workflow-uid-11" else None

        def find_record_by_excel_row_for_workbook(self, workbook_path, excel_row):
            return fresh_record if excel_row == int(fresh_record.excel_row) else None

    window.persistence_service = SwappedPersistenceService()

    index = window.data_tab.proxy.index(0, 0)
    window._on_table_clicked(index)

    assert window.selected is fresh_record
    assert window.data_tab.in_end.text() == "SQLite Runtime"
    window.close()


def test_schedule_apply_filter_uses_debounce_interval(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    started = []

    monkeypatch.setattr(window.data_controller.filter_timer, "start", lambda ms: started.append(ms))

    window.schedule_apply_filter()

    assert started == [SEARCH_FILTER_DEBOUNCE_MS]
    window.close()


def test_export_dialog_uses_last_export_dir_and_remembers_selection(ui_window_factory, monkeypatch, tmp_path):
    window = ui_window_factory()
    window.settings = AppSettings(MemorySettings())
    window.settings.set_last_export_dir(str(tmp_path))

    target = tmp_path / "relatorios" / "saida.xlsx"
    target.parent.mkdir()
    captured = {}

    def fake_get_save_file_name(_parent, _title, initial_dir, _file_filter):
        captured["initial_dir"] = initial_dir
        return str(target), "Excel (*.xlsx)"

    monkeypatch.setattr("app.ui.controllers.export_controller.QFileDialog.getSaveFileName", fake_get_save_file_name)

    path = window._get_save_path("Salvar Excel", "Excel (*.xlsx)")

    assert captured["initial_dir"] == str(tmp_path)
    assert path == str(target)
    assert window.settings.last_export_dir() == str(target.parent)
    window.close()


def test_open_session_ensures_singleton_database_and_loads_it(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    captured = {}
    window.session_runtime.path = ""
    session_entry = type(
        "SessionEntry",
        (),
        {
            "session_path": "session://banco-local",
            "display_name": "Banco local",
        },
    )()

    monkeypatch.setattr(
        window.data_controller.persistence,
        "ensure_singleton_session",
        lambda: session_entry,
    )
    monkeypatch.setattr(
        window.data_controller,
        "load_session",
        lambda path, confirm_discard=True: captured.update({"loaded": path, "confirm_discard": confirm_discard}) or True,
    )

    window.open_session()

    assert captured["loaded"] == "session://banco-local"
    assert captured["confirm_discard"] is True
    window.close()


def test_open_session_success_message_uses_authoritative_total(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    infos = []
    session_entry = type(
        "SessionEntry",
        (),
        {
            "session_path": "session://banco-local",
            "display_name": "Banco local",
        },
    )()

    monkeypatch.setattr(
        window.data_controller.persistence,
        "ensure_singleton_session",
        lambda: session_entry,
    )
    monkeypatch.setattr(window.data_controller, "load_session", lambda _path, confirm_discard=True: True)
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.QMessageBox.information",
        lambda *args, **kwargs: infos.append(args[2]),
    )
    window._local_session_source_status = LocalRecordReadStatus(
        status="sqlite",
        source="sqlite",
        strategy="sqlite_snapshot",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-31T12:00:00+00:00",
        mirrored_records=5,
        session_records=0,
        filtered_records=5,
    )

    window.open_session()

    assert infos[-1] == "Banco local pronto: 5 registros."
    window.close()


def test_new_session_alias_uses_singleton_database(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    calls = []
    window.session_runtime.path = ""
    session_entry = type(
        "SessionEntry",
        (),
        {
            "session_path": "session://banco-local",
            "display_name": "Banco local",
        },
    )()

    monkeypatch.setattr(
        window.data_controller.persistence,
        "ensure_singleton_session",
        lambda: session_entry,
    )
    monkeypatch.setattr(window.data_controller, "load_session", lambda path, confirm_discard=True: calls.append((path, confirm_discard)) or True)

    window.new_session()

    assert calls == [("session://banco-local", True)]
    window.close()


def test_export_workflow_shows_busy_indicator_during_generation(ui_window_factory, monkeypatch, tmp_path):
    window = ui_window_factory()
    window.records = [make_record()]
    window.filtered_records = list(window.records)
    observed = {}

    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "saida.csv"))

    def fake_export(path, records, selected_cols):
        observed["busy_during_export"] = not window.progress_bar.isHidden()
        observed["range"] = (window.progress_bar.minimum(), window.progress_bar.maximum())
        observed["selected_cols"] = list(selected_cols)

    monkeypatch.setattr("app.ui.controllers.export_controller.export_csv", fake_export)

    window.export_csv_clicked()

    export_job = next(job for job in window.list_runtime_jobs(limit=10) if job.name == "export_csv")

    assert observed["busy_during_export"] is True
    assert observed["range"] == (0, 0)
    assert observed["selected_cols"]
    assert export_job.status == "completed"
    assert export_job.detail_message == "CSV exportado com sucesso."
    assert window.progress_bar.isHidden() is True
    window.close()


def test_import_external_data_is_disabled_and_guides_to_sqlite_sessions(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    infos = []

    monkeypatch.setattr(
        "app.ui.controllers.data_controller.QMessageBox.information",
        lambda *args, **kwargs: infos.append(args[2]),
    )

    result = window.import_external_data()

    assert result is False
    assert "banco SQLite único" in infos[-1]
    assert "Excel" in infos[-1]
    assert "desativada" in window.statusBar().currentMessage().lower()
    assert not any(job.name in {"analyze_import", "execute_import"} for job in window.list_runtime_jobs(limit=20))
    window.close()


def test_batch_geocode_workflow_uses_busy_indicator(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    window.records = [
        make_record(uid="geo-1", microbacia="", latitude="", longitude="", endereco="Rua A"),
    ]
    captured = {}

    class FakeSignal:
        def __init__(self):
            self._callback = None

        def connect(self, callback):
            self._callback = callback

        def disconnect(self):
            self._callback = None

        def emit(self, *args, **kwargs):
            if self._callback:
                self._callback(*args, **kwargs)

    class FakeWorker:
        def __init__(self, pending):
            captured["pending"] = list(pending)
            self.progress_update = FakeSignal()
            self.finished_process = FakeSignal()
            self.cancelled_process = FakeSignal()

        def start(self):
            captured["busy_on_start"] = not window.progress_bar.isHidden()
            self.progress_update.emit(1, "Geocodificando...")
            self.finished_process.emit({})

        def isRunning(self):
            return False

        def stop(self):
            return None

    monkeypatch.setattr("app.ui.controllers.map_controller.GeocodeWorker", FakeWorker)

    window.run_batch_geocode()

    geocode_job = next(job for job in window.list_runtime_jobs(limit=10) if job.name == "batch_geocode")

    assert len(captured["pending"]) == 1
    assert captured["busy_on_start"] is True
    assert geocode_job.status == "completed"
    assert geocode_job.detail_message == "Nenhum endereco pode ser processado."
    assert window.progress_bar.isHidden() is True
    window.close()


def test_batch_geocode_can_be_cancelled_from_status_bar(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    window.records = [
        make_record(uid="geo-cancel-1", microbacia="", latitude="", longitude="", endereco="Rua B"),
    ]
    captured = {"stop_calls": 0}

    class FakeSignal:
        def __init__(self):
            self._callback = None

        def connect(self, callback):
            self._callback = callback

        def disconnect(self, *_args, **_kwargs):
            self._callback = None

        def emit(self, *args, **kwargs):
            if self._callback:
                self._callback(*args, **kwargs)

    class FakeWorker:
        def __init__(self, pending):
            self.progress_update = FakeSignal()
            self.finished_process = FakeSignal()
            self.cancelled_process = FakeSignal()
            self._running = False

        def start(self):
            self._running = True

        def isRunning(self):
            return self._running

        def stop(self):
            captured["stop_calls"] += 1
            self._running = False
            self.cancelled_process.emit("Geocodificacao em lote cancelada.")

        def quit(self):
            self._running = False

        def wait(self, _timeout):
            return True

    monkeypatch.setattr("app.ui.controllers.map_controller.GeocodeWorker", FakeWorker)

    window.run_batch_geocode()

    assert window.progress_cancel_button.isHidden() is False

    window.cancel_active_operation()

    assert captured["stop_calls"] == 1
    assert window.progress_bar.isHidden() is True
    assert window.progress_cancel_button.isHidden() is True
    assert window.geo_worker is None
    window.close()



