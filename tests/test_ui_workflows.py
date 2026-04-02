import os

from app.config import SEARCH_FILTER_DEBOUNCE_MS
from app.models.compensacao import Compensacao
from app.services.app_settings import AppSettings
from app.services.excel_service import WorkbookModifiedExternallyError


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
    window.excel.path = "dummy.xlsx"
    window.records = [make_record()]
    window.filtered_records = list(window.records)
    monkeypatch.setattr(window, "_run_map_js", lambda *args, **kwargs: None)

    window._update_ui_after_load()

    index = window.data_tab.proxy.index(0, 0)
    window._on_table_clicked(index)

    saved = []
    refreshed = []
    mirrored = {}
    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.excel, "save_edit", lambda record: saved.append(record))
    monkeypatch.setattr(window, "reload", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("reload nao deveria ser usado")))
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(
        window.persistence_service,
        "update_record_in_workbook",
        lambda workbook_path, record: mirrored.update(
            {
                "workbook_path": workbook_path,
                "uid": record.uid,
                "plantio": record.endereco_plantio,
            }
        )
        or type(
            "Summary",
            (),
            {"workbook_path": workbook_path, "synced_at": "2026-03-31T12:00:00+00:00", "record_count": 1},
        )(),
    )

    window.data_tab.chk_compensado.setChecked(True)
    window.data_tab.in_end_plantio.setText("Rua Plantio Nova")

    window.save_edit()

    assert len(saved) == 1
    assert saved[0].endereco_plantio == "Rua Plantio Nova"
    assert saved[0].compensado == "SIM"
    assert mirrored["workbook_path"] == "dummy.xlsx"
    assert mirrored["uid"] == "workflow-uid-1"
    assert mirrored["plantio"] == "Rua Plantio Nova"
    assert window._local_mutation_sync_status is not None
    assert window._local_mutation_sync_status.operation == "edit"
    assert window._local_mutation_sync_status.strategy == "incremental"
    assert len(refreshed) == 1
    window.close()


def test_form_undo_redo_tracks_dirty_state(ui_window_factory, monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda path: True if path == "dummy.xlsx" else real_exists(path))

    window = ui_window_factory()
    window.excel.path = "dummy.xlsx"
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


def test_open_excel_uses_last_excel_directory(ui_window_factory, monkeypatch, tmp_path):
    window = ui_window_factory()
    window.settings = AppSettings(MemorySettings())

    excel_path = tmp_path / "base.xlsx"
    excel_path.write_text("stub", encoding="utf-8")
    window.settings.set_last_excel_path(str(excel_path))

    captured = {}

    def fake_get_open_file_name(_parent, _title, initial_dir, _file_filter):
        captured["initial_dir"] = initial_dir
        return str(excel_path), "Excel (*.xlsx)"

    def fake_load_excel(path):
        captured["loaded"] = path
        return True

    monkeypatch.setattr("app.ui.controllers.data_controller.QFileDialog.getOpenFileName", fake_get_open_file_name)
    monkeypatch.setattr(window.data_controller, "load_excel", fake_load_excel)

    window.open_excel()

    assert captured["initial_dir"] == str(tmp_path)
    assert captured["loaded"] == str(excel_path)
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


def test_import_workflow_updates_progress_and_hides_busy_indicator(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    window.excel.path = "base.xlsx"
    window.records = [make_record(uid="existing-uid", av_tec="AT-1")]
    window.filtered_records = list(window.records)
    captured = {"progress_values": [], "preview_analyses": [], "audit_events": []}
    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)

    monkeypatch.setattr(
        "app.ui.controllers.data_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("importar.xlsx", "Excel (*.xlsx)"),
    )
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.ExcelService.load",
        lambda self, path: [make_record(uid="novo-uid", av_tec="AT-99")],
    )

    def fake_import_records_atomic(records, progress_callback):
        captured["busy_during_import"] = not window.progress_bar.isHidden()
        progress_callback(1, len(records))
        captured["progress_values"].append(window.progress_bar.value())

    class FakeImportPreviewDialog:
        def __init__(self, _parent, analysis):
            captured["preview_analyses"].append(analysis)

        def exec(self):
            return True

    refreshed = []
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.ImportPreviewDialog",
        FakeImportPreviewDialog,
    )
    monkeypatch.setattr(window.excel, "create_operation_backup", lambda label: f"C:/tmp/{label}.xlsx")
    monkeypatch.setattr(window.excel, "import_records_atomic", fake_import_records_atomic)
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: captured["audit_events"].append(payload))
    monkeypatch.setattr(
        window.persistence_service,
        "append_records_to_workbook",
        lambda workbook_path, records: captured.update(
            {
                "mirror_workbook_path": workbook_path,
                "mirror_uids": [record.uid for record in records],
            }
        )
        or type(
            "Summary",
            (),
            {
                "workbook_path": workbook_path,
                "synced_at": "2026-03-31T12:00:00+00:00",
                "record_count": len(records) + len(window.records),
            },
        )(),
    )

    window.import_excel_data()

    analyze_job = next(job for job in window.list_runtime_jobs(limit=10) if job.name == "analyze_import")
    import_job = next(job for job in window.list_runtime_jobs(limit=10) if job.name == "execute_import")

    assert captured["busy_during_import"] is True
    assert captured["progress_values"] == [1]
    assert len(captured["preview_analyses"]) == 1
    assert captured["preview_analyses"][0].total_new_records == 1
    assert captured["preview_analyses"][0].skipped_by_uid == 0
    assert captured["preview_analyses"][0].skipped_by_av_tec == 0
    assert captured["audit_events"][0]["action"] == "import"
    assert captured["audit_events"][0]["metadata"]["imported_records"] == 1
    assert captured["mirror_workbook_path"] == "base.xlsx"
    assert captured["mirror_uids"] == ["novo-uid"]
    assert window._local_mutation_sync_status is not None
    assert window._local_mutation_sync_status.operation == "import"
    assert window._local_mutation_sync_status.strategy == "incremental"
    assert len(refreshed) == 1
    assert analyze_job.status == "completed"
    assert analyze_job.detail_message == "Analise concluida."
    assert import_job.status == "completed"
    assert import_job.detail_message == "Importacao concluida."
    assert window.progress_bar.isHidden() is True
    window.close()


def test_import_workflow_blocks_invalid_source_rows_before_persisting(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    window.excel.path = "base.xlsx"
    window.records = [make_record(uid="existing-uid", av_tec="AT-1")]
    previews = []
    imported = []
    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)

    monkeypatch.setattr(
        "app.ui.controllers.data_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("importar.xlsx", "Excel (*.xlsx)"),
    )
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.ExcelService.load",
        lambda self, path: [make_record(uid="novo-uid", av_tec="AT-99", oficio_processo="")],
    )
    class FakeImportPreviewDialog:
        def __init__(self, _parent, analysis):
            previews.append(analysis)

        def exec(self):
            return True

    monkeypatch.setattr("app.ui.controllers.data_controller.ImportPreviewDialog", FakeImportPreviewDialog)
    monkeypatch.setattr(window.excel, "import_records_atomic", lambda *args, **kwargs: imported.append(True))

    window.import_excel_data()

    assert imported == []
    assert len(previews) == 1
    assert previews[0].total_invalid == 1
    assert window.statusBar().currentMessage() == "Importacao interrompida por registros invalidos"
    window.close()


def test_import_workflow_reports_external_workbook_change_before_analysis(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    window.excel.path = "base.xlsx"
    errors = []
    loaded = []

    monkeypatch.setattr(
        "app.ui.controllers.data_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("importar.xlsx", "Excel (*.xlsx)"),
    )
    monkeypatch.setattr(
        window.excel,
        "ensure_workbook_is_current",
        lambda: (_ for _ in ()).throw(WorkbookModifiedExternallyError("stale")),
    )
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.ExcelService.load",
        lambda self, path: loaded.append(path) or [],
    )
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.QMessageBox.critical",
        lambda *args, **kwargs: errors.append((args[1], args[2])),
    )

    window.import_excel_data()

    assert loaded == []
    assert errors == [("Planilha Desatualizada", "A planilha foi alterada fora do aplicativo. Recarregue antes de continuar.")]
    assert window.statusBar().currentMessage() == "Falha na importacao"
    window.close()


def test_import_workflow_can_analyze_against_authoritative_sqlite_base(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    window.excel.path = "base.xlsx"
    window.records = [make_record(uid="existing-session", av_tec="AT-1")]
    infos = []
    imported = []
    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)

    monkeypatch.setattr(
        "app.ui.controllers.data_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("importar.xlsx", "Excel (*.xlsx)"),
    )
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.ExcelService.load",
        lambda self, path: [make_record(uid="novo-uid", av_tec="AT-99")],
    )
    monkeypatch.setattr(
        window.data_controller.local_record_queries,
        "resolve_record_source",
        lambda workbook_path, **kwargs: type(
            "RecordSource",
            (),
            {
                "records": (make_record(uid="existing-sqlite", av_tec="AT-99", excel_row=9),),
                "issues": (),
            },
        )(),
    )
    monkeypatch.setattr("app.ui.controllers.data_controller.QMessageBox.information", lambda *args, **kwargs: infos.append(args[2]))
    monkeypatch.setattr(window.excel, "import_records_atomic", lambda *args, **kwargs: imported.append(True))

    window.import_excel_data()

    assert imported == []
    assert infos == ["Nenhum registro novo encontrado para importar (1 ja existentes)."]
    window.close()


def test_import_workflow_uses_authoritative_runtime_base_for_projection_and_sync(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    window.excel.path = "base.xlsx"
    window.records = [make_record(uid="existing-session", av_tec="AT-1")]
    refreshed = []
    sync_calls = []
    project_calls = []
    authoritative_base = [make_record(uid="existing-sqlite", av_tec="AT-SQL", excel_row=9)]
    monkeypatch.setattr(window.excel, "ensure_workbook_is_current", lambda: None)

    monkeypatch.setattr(
        "app.ui.controllers.data_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("importar.xlsx", "Excel (*.xlsx)"),
    )
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.ExcelService.load",
        lambda self, path: [make_record(uid="novo-uid", av_tec="AT-99", excel_row=10)],
    )

    class FakeImportPreviewDialog:
        def __init__(self, _parent, _analysis):
            return None

        def exec(self):
            return True

    monkeypatch.setattr("app.ui.controllers.data_controller.ImportPreviewDialog", FakeImportPreviewDialog)
    monkeypatch.setattr(window.excel, "create_operation_backup", lambda label: f"C:/tmp/{label}.xlsx")
    monkeypatch.setattr(window.excel, "import_records_atomic", lambda records, progress_callback: progress_callback(1, len(records)))
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: None)
    monkeypatch.setattr(
        window.data_controller.local_record_queries,
        "resolve_authoritative_record_source",
        lambda workbook_path, **kwargs: type(
            "RecordSource",
            (),
            {"records": tuple(authoritative_base), "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.data_controller.local_mutation_sync,
        "apply_after_import",
        lambda **kwargs: sync_calls.append(kwargs)
        or project_calls.append((list(kwargs["existing_records"]), list(kwargs["imported_records"])))
        or type(
            "MutationResult",
            (),
            {
                "status": type("Status", (), {"issues": (), "operation": "import"})(),
                "records": tuple([*authoritative_base, make_record(uid="novo-uid", av_tec="AT-99", excel_row=10)]),
            },
        )(),
    )

    window.import_excel_data()

    assert len(sync_calls) == 1
    assert [record.uid for record in sync_calls[0]["existing_records"]] == ["existing-sqlite"]
    assert len(project_calls) == 1
    assert [record.uid for record in project_calls[0][0]] == ["existing-sqlite"]
    assert [record.uid for record in refreshed[0]] == ["existing-sqlite", "novo-uid"]
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
