import os


def test_core_modules_import_cleanly():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    import app.main  # noqa: F401
    import app.services.excel_service  # noqa: F401
    import app.services.ficha_report_service  # noqa: F401
    import app.services.gis_service  # noqa: F401
    import app.services.report_service  # noqa: F401
    import app.ui.main_window  # noqa: F401

def test_main_window_can_close_cleanly(ui_window_factory, qt_app):
    window = ui_window_factory()
    window.close()
    qt_app.processEvents()


def test_main_window_close_stops_owned_timers(ui_window_factory, qt_app):
    window = ui_window_factory()

    assert window._startup_window_timer.parent() is window
    assert window._initial_map_sync_timer.parent() is window

    window._initial_map_sync_timer.start(500)
    window.close()
    qt_app.processEvents()

    assert window._initial_map_sync_timer.isActive() is False


def test_theme_qss_emphasizes_checked_checkboxes_and_radios():
    from app.ui.components.themes import THEME_DARK, get_app_qss

    qss = get_app_qss(THEME_DARK, 1.0).replace("\\", "/")

    assert "QCheckBox::indicator:checked" in qss
    assert "QRadioButton::indicator:checked" in qss
    assert THEME_DARK["btn_primary_hover"] in qss
    assert 'image: url("' in qss
    assert 'assets/toggle_on.svg")' in qss
    assert 'assets/radio_on.svg")' in qss
    assert "QTextEdit" in qss
    assert "QPlainTextEdit" in qss


def test_columns_dialog_buttons_work_without_name_errors(qt_app):
    from app.ui.components.widgets import ColumnsDialog

    dialog = ColumnsDialog(None, ["Ofício", "Microbacia"], {0: True, 1: False})

    dialog.btn_none.click()
    assert all(not check.isChecked() for check in dialog.checks)

    dialog.btn_all.click()
    assert all(check.isChecked() for check in dialog.checks)

    dialog.close()


def test_msg_confirm_uses_yes_as_default_and_no_as_escape(monkeypatch, qt_app):
    from PySide6.QtWidgets import QMessageBox
    from app.ui.components.ui_utils import msg_confirm

    captured = {}

    def fake_exec(self):
        captured["default_text"] = self.defaultButton().text()
        captured["escape_text"] = self.escapeButton().text()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self.defaultButton())

    result = msg_confirm(None, "Confirmação", "Deseja continuar?")

    assert result is True
    assert captured["default_text"] == "Sim"
    assert captured["escape_text"] == "Não"
