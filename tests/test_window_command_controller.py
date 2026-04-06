import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_command_controller_executes_latest_bindings_and_ignores_signal_args(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    calls = []

    monkeypatch.setattr(window.data_controller, "open_session", lambda: calls.append("open_session"))
    monkeypatch.setattr(window.form_controller, "clear_form", lambda force=False: calls.append(("clear_form", force)))

    window.command_controller.execute("open_session")
    window.command_controller.build_handler("clear_form", force=True)(False)

    assert "open_session" in window.command_controller.list_commands()
    assert "new_session" in window.command_controller.list_commands()
    assert "undo" in window.command_controller.list_commands()
    assert calls == ["open_session", ("clear_form", True)]

    with pytest.raises(KeyError):
        window.command_controller.execute("comando_inexistente")

    window.close()


def test_main_window_command_wrappers_delegate_to_command_controller(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    calls = []

    monkeypatch.setattr(window.command_controller, "toggle_theme", lambda: calls.append("toggle_theme"))
    monkeypatch.setattr(
        window.command_controller,
        "show_operation_history",
        lambda: calls.append("show_operation_history"),
    )

    window.toggle_theme()
    window.show_operation_history()

    assert calls == ["toggle_theme", "show_operation_history"]
    window.close()


def test_window_shell_actions_route_through_command_handlers(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    calls = {
        "reload": 0,
        "history": 0,
        "rollback": 0,
        "refresh": 0,
        "backup": 0,
        "updates": 0,
    }

    monkeypatch.setattr(
        window.data_controller,
        "reload",
        lambda confirm_discard=True: calls.__setitem__("reload", calls["reload"] + 1),
    )
    monkeypatch.setattr(
        window.data_controller,
        "show_operation_history",
        lambda: calls.__setitem__("history", calls["history"] + 1),
    )
    monkeypatch.setattr(
        window.data_controller,
        "show_rollback_dialog",
        lambda: calls.__setitem__("rollback", calls["rollback"] + 1),
    )
    monkeypatch.setattr(
        window.operations_controller,
        "refresh_overview",
        lambda *args, **kwargs: calls.__setitem__("refresh", calls["refresh"] + 1),
    )
    monkeypatch.setattr(
        window.operations_controller,
        "open_selected_backup",
        lambda: calls.__setitem__("backup", calls["backup"] + 1),
    )
    monkeypatch.setattr(
        window.support_controller,
        "check_for_updates",
        lambda: calls.__setitem__("updates", calls["updates"] + 1),
    )

    window.action_reload.trigger()
    window.action_operation_history.trigger()
    window.action_rollback.trigger()
    window.tabs.setCurrentWidget(window.operations_tab)
    window.operations_tab.btn_refresh.click()
    window.operations_tab.btn_open_backup.setEnabled(True)
    window.operations_tab.btn_open_backup.click()
    window.action_check_updates.trigger()

    assert calls == {
        "reload": 1,
        "history": 1,
        "rollback": 1,
        "refresh": 2,
        "backup": 1,
        "updates": 1,
    }
    window.close()


def test_command_controller_exposes_session_first_aliases(ui_window_factory, monkeypatch):
    window = ui_window_factory()
    calls = []

    monkeypatch.setattr(window.data_controller, "open_session", lambda: calls.append("open_session"))
    monkeypatch.setattr(window.data_controller, "new_session", lambda: calls.append("new_session"))

    window.command_controller.execute("open_session_source")
    window.command_controller.execute("new_session")

    assert "open_session_source" in window.command_controller.list_commands()
    assert "new_session" in window.command_controller.list_commands()
    assert "import_external_data" not in window.command_controller.list_commands()
    assert calls == ["open_session", "new_session"]
    window.close()
