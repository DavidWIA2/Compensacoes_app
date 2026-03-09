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
