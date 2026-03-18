import os

from app.config import SEARCH_FILTER_DEBOUNCE_MS
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
    window.excel.path = "dummy.xlsx"
    window.records = [make_record()]
    window.filtered_records = list(window.records)
    monkeypatch.setattr(window, "_run_map_js", lambda *args, **kwargs: None)

    window._update_ui_after_load()

    index = window.data_tab.proxy.index(0, 0)
    window._on_table_clicked(index)

    saved = []
    reloaded = []
    monkeypatch.setattr(window.excel, "save_edit", lambda record: saved.append(record))
    monkeypatch.setattr(window, "reload", lambda: reloaded.append(True))

    window.data_tab.chk_compensado.setChecked(True)
    window.data_tab.in_end_plantio.setText("Rua Plantio Nova")

    window.save_edit()

    assert len(saved) == 1
    assert saved[0].endereco_plantio == "Rua Plantio Nova"
    assert saved[0].compensado == "SIM"
    assert reloaded == [True]


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


def test_schedule_apply_filter_uses_debounce_interval(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    started = []

    monkeypatch.setattr(window.data_controller.filter_timer, "start", lambda ms: started.append(ms))

    window.schedule_apply_filter()

    assert started == [SEARCH_FILTER_DEBOUNCE_MS]


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
