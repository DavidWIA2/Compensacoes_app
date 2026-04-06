from types import SimpleNamespace

from app.ui.controllers.window_lifecycle_support import (
    build_update_disconnect_callbacks,
    build_update_prompt_content,
    run_startup_sequence,
    stop_active_timer,
)


class FakeSignal:
    def __init__(self):
        self.connected = []
        self.disconnected = []

    def connect(self, handler):
        self.connected.append(handler)

    def disconnect(self, handler):
        self.disconnected.append(handler)


class FakeTimer:
    def __init__(self, active: bool):
        self._active = active
        self.stopped = False

    def isActive(self):
        return self._active

    def stop(self):
        self.stopped = True
        self._active = False


def test_window_lifecycle_support_builds_update_prompt():
    prompt = build_update_prompt_content("2.0.0", "Mais estabilidade")

    assert prompt.title == "Atualização Disponível"
    assert "2.0.0" in prompt.question_message
    assert "Mais estabilidade" in prompt.question_message
    assert "Baixando atualização" in prompt.accepted_status_message


def test_window_lifecycle_support_builds_disconnect_callbacks():
    updater = SimpleNamespace(update_ready=FakeSignal())
    window = SimpleNamespace(present_update_offer=lambda *args, **kwargs: None, _prompt_update=lambda *args, **kwargs: None)

    callbacks = build_update_disconnect_callbacks(window, updater)
    callbacks[0]()

    assert updater.update_ready.connected == [window.present_update_offer]
    assert updater.update_ready.disconnected == [window.present_update_offer]


def test_window_lifecycle_support_stops_only_active_timers():
    active_timer = FakeTimer(True)
    inactive_timer = FakeTimer(False)

    stop_active_timer(active_timer)
    stop_active_timer(inactive_timer)

    assert active_timer.stopped is True
    assert inactive_timer.stopped is False


def test_window_lifecycle_support_runs_startup_sequence_in_order():
    calls = []
    status_messages = []
    timer_starts = []
    window = SimpleNamespace(
        _setup_menus=lambda: calls.append("_setup_menus"),
        _load_settings=lambda: calls.append("_load_settings"),
        _connect_signals=lambda: calls.append("_connect_signals"),
        _setup_shortcuts=lambda: calls.append("_setup_shortcuts"),
        form_controller=SimpleNamespace(setup_form_state_ui=lambda: calls.append("setup_form_state_ui")),
        _startup_window_timer=SimpleNamespace(start=lambda delay: timer_starts.append(delay)),
        _load_last_session=lambda: calls.append("_load_last_session"),
        _apply_theme=lambda: calls.append("_apply_theme"),
        _update_form_action_buttons=lambda: calls.append("_update_form_action_buttons"),
        _update_address_search_enabled=lambda: calls.append("_update_address_search_enabled"),
        _refresh_window_chrome=lambda: calls.append("_refresh_window_chrome"),
        refresh_operations_overview=lambda: calls.append("refresh_operations_overview"),
        setWindowModified=lambda modified: calls.append(("setWindowModified", modified)),
        statusBar=lambda: SimpleNamespace(showMessage=lambda message: status_messages.append(message)),
    )

    run_startup_sequence(window)

    assert calls[:4] == ["_setup_menus", "_load_settings", "_connect_signals", "_setup_shortcuts"]
    assert "_load_last_session" in calls
    assert ("setWindowModified", False) in calls
    assert timer_starts == [0]
    assert status_messages == ["Pronto"]
