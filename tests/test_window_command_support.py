from app.ui.controllers.window_command_support import build_window_command_binding_map


def test_window_command_binding_map_resolves_latest_controller_methods(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    calls = []
    bindings = build_window_command_binding_map()

    monkeypatch.setattr(window.data_controller, "open_session", lambda: calls.append("open_session"))
    monkeypatch.setattr(window.support_controller, "show_about_dialog", lambda: calls.append("about"))

    bindings["open_session"].resolve(window)()
    bindings["show_about_dialog"].resolve(window)()

    assert calls == ["open_session", "about"]
    window.close()
