import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication

from app.ui.components.access_dialog import AccessDialog
from tests.test_access_dialog import _FakeAccessService, _FakeAdminUsersService, _MemorySettings


def _app():
    return QApplication.instance() or QApplication([])


def test_access_dialog_keeps_compact_layout_while_window_is_maximized():
    app = _app()
    dialog = AccessDialog(
        settings=_MemorySettings(),
        access_service=_FakeAccessService(),
        admin_users_service=_FakeAdminUsersService(),
    )
    dialog.show()
    dialog.resize(1600, 900)
    app.processEvents()

    dialog.setWindowState(dialog.windowState() | Qt.WindowState.WindowMaximized)
    app.processEvents()
    dialog._apply_responsive_layout()

    assert dialog.visual_panel.isVisible() is False
    assert dialog.production_button.text() == "Entrar"
    assert dialog.cancel_button.text() == "Fechar"


def test_access_dialog_restores_saved_geometry_after_expanded_state(monkeypatch):
    _app()
    dialog = AccessDialog(
        settings=_MemorySettings(),
        access_service=_FakeAccessService(),
        admin_users_service=_FakeAdminUsersService(),
    )
    dialog.show()
    dialog._saved_normal_geometry = QRect(120, 140, 980, 640)
    captured = {}

    monkeypatch.setattr(
        dialog,
        "setGeometry",
        lambda rect: captured.setdefault("geometry", QRect(rect)),
    )
    dialog._restore_saved_normal_geometry()

    assert captured["geometry"] == QRect(120, 140, 980, 640)


def test_access_dialog_prefers_qt_normal_geometry_when_capturing_from_expanded_state(monkeypatch):
    _app()
    dialog = AccessDialog(
        settings=_MemorySettings(),
        access_service=_FakeAccessService(),
        admin_users_service=_FakeAdminUsersService(),
    )
    dialog.show()

    monkeypatch.setattr(dialog, "normalGeometry", lambda: QRect(90, 110, 980, 640))
    monkeypatch.setattr(dialog, "geometry", lambda: QRect(0, 0, 1920, 1080))

    dialog._capture_normal_geometry(force=True, prefer_normal_geometry=True)

    assert dialog._saved_normal_geometry == QRect(90, 110, 980, 640)
