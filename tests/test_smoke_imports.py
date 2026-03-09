import os


def test_core_modules_import_cleanly():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    import app.main  # noqa: F401
    import app.services.excel_service  # noqa: F401
    import app.services.gis_service  # noqa: F401
    import app.services.report_service  # noqa: F401
    import app.ui.main_window  # noqa: F401


def test_main_window_can_close_cleanly():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.close()
    app.processEvents()
