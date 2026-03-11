import os
from types import SimpleNamespace

from app.models.compensacao import Compensacao

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from PySide6.QtWidgets import QApplication

from app.ui import main_window as main_window_module
from app.ui.main_window import MainWindow


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "",
        "compensado": "",
        "latitude": "",
        "longitude": "",
    }
    base.update(overrides)
    return Compensacao(**base)


def get_app():
    return QApplication.instance() or QApplication([])


def test_load_last_excel_runs_even_if_map_setup_is_stubbed(monkeypatch):
    get_app()
    calls = []

    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: calls.append("map"))
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: calls.append("excel"))

    window = MainWindow()

    assert calls == ["map", "excel"]
    window.close()


def test_main_window_uses_readable_core_labels(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()

    assert window.windowTitle() == "Compensações - Cadastro e Consulta"
    assert "ofício" in window.search.placeholderText().lower()
    assert window.filter_eletronico.lineEdit().placeholderText() == "Eletrônico"
    assert window.btn_maps.text() == "Pesquisar Endereço"
    assert window.kpi_model.horizontalHeaderItem(0).text() == "Métrica"
    window.close()


def test_startup_reenables_ui_when_last_excel_is_loaded(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)

    def fake_load_last_excel(self):
        self.excel.path = "dummy.xlsx"
        self.records = [make_record()]
        self.filtered_records = list(self.records)

    monkeypatch.setattr(MainWindow, "_load_last_excel", fake_load_last_excel)

    window = MainWindow()

    assert window.table.isEnabled() is True
    assert window.in_oficio.isEnabled() is True
    assert window.btn_add.isEnabled() is True
    window.close()


def test_apply_filter_updates_visible_results_label(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    window.records = [
        make_record(oficio_processo="ABC-1"),
        make_record(excel_row=3, oficio_processo="XYZ-2"),
    ]
    window.search.setText("ABC")
    window.apply_filter()

    assert window.lbl_results.text() == "1 registros"

    window.search.setText("SEM-RESULTADO")
    window.apply_filter()

    assert window.lbl_results.text() == "Nenhum registro"
    window.close()


def test_export_excel_reuses_cached_filtered_metrics(monkeypatch, tmp_path):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    window.records = [
        make_record(oficio_processo="ABC-1", compensacao="10", microbacia="Gregorio"),
        make_record(excel_row=3, oficio_processo="XYZ-2", compensacao="5", microbacia="Medeiros"),
    ]
    window.search.setText("ABC")
    window.filter_status.setCurrentText("Pendentes")
    window.apply_filter()

    captured = {}
    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "saida.xlsx"))
    monkeypatch.setattr(window, "_show_export_success", lambda: None)
    monkeypatch.setattr(
        main_window_module,
        "export_excel_two_sheets",
        lambda path, records, filtros_txt, selected_cols, kpis, pend_micro_sorted, pend_ele_sorted: captured.update(
            {
                "path": path,
                "records": records,
                "filtros_txt": filtros_txt,
                "kpis": kpis,
                "pend_micro_sorted": pend_micro_sorted,
            }
        ),
    )
    monkeypatch.setattr(
        window,
        "_compute_metrics",
        lambda records: (_ for _ in ()).throw(AssertionError("nao deveria recalcular metrics no export")),
    )

    window.export_excel_clicked()

    assert captured["path"].endswith("saida.xlsx")
    assert len(captured["records"]) == 1
    assert captured["filtros_txt"] == "Busca: ABC | Status: Pendentes"
    assert captured["kpis"][0] == ("Total", 10.0)
    assert captured["pend_micro_sorted"] == [("Gregorio", 10.0)]
    window.close()


def test_export_csv_reports_failure_without_raising(monkeypatch, tmp_path):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    window.records = [make_record(oficio_processo="ABC-1")]
    window.filtered_records = list(window.records)
    errors = []
    successes = []

    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "saida.csv"))
    monkeypatch.setattr(window, "_show_export_success", lambda: successes.append("ok"))
    monkeypatch.setattr(
        main_window_module,
        "export_csv",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("disco cheio")),
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *args, **kwargs: errors.append(args[2]))

    window.export_csv_clicked()

    assert not successes
    assert errors and "disco cheio" in errors[0]
    window.close()


def test_export_dashboard_pdf_uses_temporary_directory(monkeypatch, tmp_path):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    window.records = [make_record(compensacao="10", microbacia="Gregorio")]
    window.filtered_records = list(window.records)
    window._mark_metrics_dirty()
    window.search.setText("Gregorio")

    state = {"exited": False}
    temp_dir_path = tmp_path / "dash-temp"

    class FakeTemporaryDirectory:
        def __enter__(self):
            temp_dir_path.mkdir(exist_ok=True)
            return str(temp_dir_path)

        def __exit__(self, exc_type, exc, tb):
            state["exited"] = True

    captured = {}
    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "painel.pdf"))
    monkeypatch.setattr(window, "_show_export_success", lambda: None)
    monkeypatch.setattr(main_window_module.tempfile, "TemporaryDirectory", FakeTemporaryDirectory)

    def fake_export_dashboard_images(temp_dir):
        captured["temp_dir"] = temp_dir
        return str(temp_dir_path / "p.png"), str(temp_dir_path / "b.png")

    monkeypatch.setattr(window, "_export_dashboard_images", fake_export_dashboard_images)
    monkeypatch.setattr(
        main_window_module,
        "export_dashboard_pdf",
        lambda path, titulo, kpi_lines, filtros_txt, chart_images: captured.update(
            {
                "path": path,
                "kpi_lines": kpi_lines,
                "filtros_txt": filtros_txt,
                "chart_images": chart_images,
            }
        ),
    )

    window.export_dashboard_pdf_clicked()

    assert captured["temp_dir"] == str(temp_dir_path)
    assert captured["path"].endswith("painel.pdf")
    assert captured["filtros_txt"] == "Busca: Gregorio"
    assert captured["kpi_lines"] == ["Total: 10.0", "Pendente: 10.0", "Compensado: 0.0"]
    assert state["exited"] is True
    window.close()


def test_form_action_buttons_follow_selection_state(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    window.excel.path = "dummy.xlsx"
    window._set_enabled_all(True)
    window.clear_form()

    assert window.btn_add.isEnabled() is True
    assert window.btn_save_edit.isEnabled() is False
    assert window.btn_delete.isEnabled() is False
    assert window.selected is None

    window.fill_form(make_record())

    assert window.btn_save_edit.isEnabled() is False
    assert window.btn_delete.isEnabled() is False

    window.selected = make_record()
    window._update_form_action_buttons()

    assert window.btn_save_edit.isEnabled() is True
    assert window.btn_delete.isEnabled() is True
    window.close()


def test_table_row_selection_populates_form(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    window.excel.path = "dummy.xlsx"
    window._set_enabled_all(True)
    window.records = [
        make_record(excel_row=2, oficio_processo="PROC-2"),
        make_record(excel_row=3, oficio_processo="PROC-3"),
    ]
    window.apply_filter()

    window.table.selectRow(1)
    get_app().processEvents()

    assert window.selected is not None
    assert window.selected.excel_row == 3
    assert window.in_oficio.text() == "PROC-3"
    assert window.btn_save_edit.isEnabled() is True
    assert window.btn_delete.isEnabled() is True
    window.close()


def test_get_record_by_excel_row_rebuilds_index_from_records(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    window.records = [
        make_record(excel_row=2, oficio_processo="PROC-2"),
        make_record(excel_row=3, oficio_processo="PROC-3"),
    ]
    window.records_by_excel_row = {}

    found = window._get_record_by_excel_row(3)

    assert found is not None
    assert found.oficio_processo == "PROC-3"
    assert 3 in window.records_by_excel_row
    window.close()


def test_search_on_map_by_address_persists_detected_microbacia(monkeypatch):
    get_app()
    window = MainWindow()
    saved = []

    monkeypatch.setattr(window, "geocode_address", lambda address: (-22.01, -47.89))
    monkeypatch.setattr(window, "gis", SimpleNamespace(find_microbacia=lambda lat, lng: "Gregorio"))
    monkeypatch.setattr(window, "_highlight_microbacia", lambda micro: None)
    monkeypatch.setattr(window.excel, "save_edit", lambda record: saved.append(record))

    record = make_record(endereco="Rua Teste")
    window.selected = record
    window.in_end.setText("Rua Teste")

    window.search_on_map_by_address()

    assert record.latitude == "-22.01"
    assert record.longitude == "-47.89"
    assert record.microbacia == "Gregorio"
    assert saved and saved[0].microbacia == "Gregorio"
    assert window.in_micro.currentText() == "Gregorio"
    window.close()


def test_apply_geocode_result_surfaces_save_failures_without_mutating_selected(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    record = make_record(microbacia="")
    errors = []

    monkeypatch.setattr(window, "_set_map_marker", lambda *args, **kwargs: None)
    monkeypatch.setattr(window, "_highlight_microbacia", lambda *args, **kwargs: None)
    monkeypatch.setattr(window, "_set_map_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(window, "gis", SimpleNamespace(find_microbacia=lambda lat, lng: "Gregorio"))
    monkeypatch.setattr(window.excel, "save_edit", lambda record: (_ for _ in ()).throw(RuntimeError("arquivo bloqueado")))
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *args, **kwargs: errors.append(args[2]))

    window.selected = record
    window.fill_form(record)

    micro = window._apply_geocode_result(-22.01, -47.89)

    assert micro == "Gregorio"
    assert window.selected.latitude == ""
    assert window.selected.longitude == ""
    assert window.selected.microbacia == ""
    assert window.in_micro.currentText() == ""
    assert errors and "arquivo bloqueado" in errors[0]
    window.close()


def test_load_last_excel_reports_failures_and_clears_setting(monkeypatch, tmp_path):
    get_app()
    real_load_last_excel = MainWindow._load_last_excel
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    warnings = []
    expected_path = tmp_path / "ultima.xlsx"
    expected_path.write_text("stub", encoding="utf-8")
    state = {"last_excel_path": str(expected_path)}
    window.settings = SimpleNamespace(
        value=lambda key, default="": state.get(key, default),
        remove=lambda key: state.pop(key, None),
        setValue=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(window, "_load_excel_records", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("planilha corrompida")))
    monkeypatch.setattr(main_window_module.QTimer, "singleShot", lambda _delay, func: func())
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    real_load_last_excel(window)

    assert warnings and "planilha corrompida" in warnings[0]
    assert "last_excel_path" not in state
    window.close()


def test_restore_window_preferences_uses_saved_geometry_and_tab(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    state = {"window_geometry": b"geom", "active_tab_index": 1}
    restored = []
    window.settings = SimpleNamespace(
        value=lambda key, default=None: state.get(key, default),
        setValue=lambda *args, **kwargs: None,
        remove=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(window, "restoreGeometry", lambda geometry: restored.append(geometry) or True)

    window.tabs.setCurrentIndex(0)
    window._restore_window_preferences()

    assert restored == [b"geom"]
    assert window.tabs.currentIndex() == 1
    window.close()


def test_close_event_persists_geometry_and_active_tab(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    saved = {}
    window.settings = SimpleNamespace(
        value=lambda key, default=None: saved.get(key, default),
        setValue=lambda key, value: saved.__setitem__(key, value),
        remove=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(window, "saveGeometry", lambda: b"geom")
    monkeypatch.setattr(window.main_splitter, "saveState", lambda: b"split-main")
    monkeypatch.setattr(window.dash_splitter, "saveState", lambda: b"split-dash")

    window.tabs.setCurrentIndex(1)
    window.close()

    assert saved["window_geometry"] == b"geom"
    assert saved["active_tab_index"] == 1


def test_run_batch_geocode_cancel_stops_worker(monkeypatch):
    get_app()
    window = MainWindow()

    class FakeSignal:
        def __init__(self):
            self._slots = []

        def connect(self, slot):
            self._slots.append(slot)

        def emit(self, *args, **kwargs):
            for slot in list(self._slots):
                slot(*args, **kwargs)

    class FakeProgressDialog:
        def __init__(self, *args, **kwargs):
            self.canceled = FakeSignal()
            self.value = None
            self.label = None

        def setWindowTitle(self, title):
            self.title = title

        def setMinimumDuration(self, duration):
            self.duration = duration

        def setValue(self, value):
            self.value = value

        def setLabelText(self, label):
            self.label = label

        def close(self):
            self.closed = True

    class FakeWorker:
        def __init__(self, records):
            self.records = records
            self.progress_update = FakeSignal()
            self.finished_process = FakeSignal()
            self.stop_called = False
            self.started = False

        def start(self):
            self.started = True

        def stop(self):
            self.stop_called = True

    monkeypatch.setattr(main_window_module, "QProgressDialog", FakeProgressDialog)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *args, **kwargs: QtWidgets.QMessageBox.Yes)
    monkeypatch.setattr(main_window_module, "GeocodeWorker", FakeWorker)

    window.excel.path = "dummy.xlsx"
    window.records = [make_record(endereco="Rua X", latitude="", longitude="", microbacia="")]

    window.run_batch_geocode()
    window.progress.canceled.emit()

    assert window.geo_worker.started is True
    assert window.geo_worker.stop_called is True
    assert window.progress.label == "Cancelando..."
    window.close()


def test_map_js_calls_are_guarded_when_loading_layers(monkeypatch, tmp_path):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    scripts = []
    fake_page = SimpleNamespace(runJavaScript=lambda script: scripts.append(script))
    fake_web = SimpleNamespace(page=lambda: fake_page)

    class FakeGis:
        def to_geojson_obj(self):
            return {"type": "FeatureCollection", "features": []}

    window = MainWindow()
    window.web = fake_web
    window.gis = None

    monkeypatch.setattr(main_window_module, "MICROB_DIR", str(tmp_path))
    monkeypatch.setattr(main_window_module.os.path, "isdir", lambda path: True)
    monkeypatch.setattr(main_window_module, "GisService", lambda *args, **kwargs: FakeGis())

    window._load_microbacias_layer()
    window.gis = object()
    monkeypatch.setattr(window, "_get_current_heatmap_points", lambda: [[-22.0, -47.0, 1.0]])
    window.toggle_heatmap()

    assert scripts[0].startswith("if(window.setMicrobacias)")
    assert scripts[1].startswith("if(window.setHeatmap)")
    window.close()


def test_heatmap_adds_centroid_fallback_even_with_precise_points(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    window.chk_heatmap.setChecked(True)
    window.combo_heatmap_type.setCurrentText("Pendentes")
    window.filtered_records = [
        make_record(
            compensacao="10",
            microbacia="Gregorio",
            compensado="",
            latitude="-22.01",
            longitude="-47.89",
        ),
        make_record(
            excel_row=3,
            compensacao="5",
            microbacia="Medeiros",
            compensado="",
            latitude="",
            longitude="",
        ),
    ]
    calls = []
    window.gis = SimpleNamespace(
        get_microbacia_centroid=lambda micro: calls.append(micro) or (-22.02, -47.88)
    )

    points = window._get_current_heatmap_points()

    assert len(points) == 2
    assert [-22.01, -47.89, 1.0] in points
    assert [-22.02, -47.88, 1.0] in points
    assert calls == ["Medeiros"]
    window.close()


def test_heatmap_points_are_cached_until_dirty(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    window.chk_heatmap.setChecked(True)
    window.combo_heatmap_type.setCurrentText("Pendentes")
    window.filtered_records = [
        make_record(compensacao="5", microbacia="Gregorio", compensado="", latitude="", longitude="")
    ]
    calls = []
    window.gis = SimpleNamespace(
        get_microbacia_centroid=lambda micro: calls.append(micro) or (-22.02, -47.88)
    )

    first = window._get_current_heatmap_points()
    second = window._get_current_heatmap_points()
    window._mark_heatmap_dirty()
    third = window._get_current_heatmap_points()

    assert first == second == third
    assert calls == ["Gregorio", "Gregorio"]
    window.close()


def test_run_map_js_reports_failures_without_raising(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    logs = []
    window = MainWindow()
    fake_page = SimpleNamespace(runJavaScript=lambda script: (_ for _ in ()).throw(RuntimeError("web indisponivel")))
    window.web = SimpleNamespace(page=lambda: fake_page)

    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: logs.append(" ".join(str(arg) for arg in args)))

    ok = window._run_map_js("window.setStatus('x');", "status")

    assert ok is False
    assert logs and "MAP JS" in logs[0]
    assert "status" in logs[0]
    window.close()


def test_save_edit_blocks_invalid_payload(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    saved = []
    warnings = []

    monkeypatch.setattr(window.excel, "save_edit", lambda record: saved.append(record))
    monkeypatch.setattr(window, "reload", lambda: None)
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    window.excel.path = "dummy.xlsx"
    window.selected = make_record()
    window.fill_form(window.selected)
    window.in_comp.setText("")

    window.save_edit()

    assert saved == []
    assert warnings and warnings[0] == "Preencha Compensa\u00e7\u00e3o."
    window.close()



def test_save_edit_blocks_non_numeric_compensacao(monkeypatch):
    get_app()
    monkeypatch.setattr(MainWindow, "_setup_leaflet_map", lambda self: None)
    monkeypatch.setattr(MainWindow, "_load_last_excel", lambda self: None)

    window = MainWindow()
    saved = []
    warnings = []

    monkeypatch.setattr(window.excel, "save_edit", lambda record: saved.append(record))
    monkeypatch.setattr(window, "reload", lambda: None)
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    window.excel.path = "dummy.xlsx"
    window.selected = make_record()
    window.fill_form(window.selected)
    window.in_comp.setText("abc")

    window.save_edit()

    assert saved == []
    assert warnings and warnings[0] == "Compensa\u00e7\u00e3o deve ser num\u00e9rica."
    window.close()
