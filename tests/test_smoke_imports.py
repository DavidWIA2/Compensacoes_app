import os


def test_core_modules_import_cleanly():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    import app.main  # noqa: F401
    import app.services.excel_service  # noqa: F401
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

    qss = get_app_qss(THEME_DARK, 1.0)

    assert "QCheckBox::indicator:checked" in qss
    assert "QRadioButton::indicator:checked" in qss
    assert THEME_DARK["btn_primary_hover"] in qss
    assert "assets/toggle_on.svg" in qss.replace("\\", "/")
