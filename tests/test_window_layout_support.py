from types import SimpleNamespace

import app.ui.controllers.window_layout_support as layout_module


class _FakeTabs:
    def __init__(self, widget):
        self._widget = widget

    def currentWidget(self):
        return self._widget


def test_apply_window_responsive_layout_updates_shell_and_active_tab():
    calls = []
    active_tab = SimpleNamespace(
        _apply_responsive_layout=lambda: calls.append("tab-apply"),
        _finalize_responsive_layout=lambda: calls.append("tab-finalize"),
    )
    window = SimpleNamespace(
        shell_controller=SimpleNamespace(apply_responsive_layout=lambda: calls.append("shell-apply")),
        tabs=_FakeTabs(active_tab),
    )

    changed = layout_module.apply_window_responsive_layout(window)

    assert changed is True
    assert calls == ["shell-apply", "tab-apply", "tab-finalize"]


def test_fit_window_to_available_geometry_tolerates_missing_layout_methods(monkeypatch):
    calls = []
    window = SimpleNamespace(tabs=_FakeTabs(SimpleNamespace()))

    monkeypatch.setattr(
        layout_module,
        "ensure_window_fits_available_geometry",
        lambda target: calls.append(target) or True,
    )

    changed = layout_module.fit_window_to_available_geometry(window)

    assert changed is True
    assert calls == [window]


def test_schedule_window_fit_uses_requested_delays(monkeypatch):
    calls = []
    delays = []
    window = SimpleNamespace(
        shell_controller=SimpleNamespace(apply_responsive_layout=lambda: calls.append("shell-apply")),
        tabs=_FakeTabs(SimpleNamespace(_apply_responsive_layout=lambda: calls.append("tab-apply"))),
    )

    monkeypatch.setattr(
        layout_module,
        "ensure_window_fits_available_geometry",
        lambda target: calls.append(("fit", target)) or True,
    )
    monkeypatch.setattr(
        layout_module,
        "schedule_owned_single_shot",
        lambda _owner, delay, fn: delays.append(delay) or fn(),
    )

    changed = layout_module.schedule_window_fit(window, delays=(0, 180))

    assert changed is True
    assert delays == [0, 180]
    assert calls == [
        "shell-apply",
        "tab-apply",
        ("fit", window),
        "shell-apply",
        "tab-apply",
        ("fit", window),
    ]
