from types import SimpleNamespace

import app.ui.controllers.window_navigation_controller as nav_module
from app.ui.controllers.window_navigation_controller import WindowNavigationController


def test_window_navigation_controller_renders_tcra_overview_when_available():
    dashboard_calls = []
    tcra_calls = []

    dash_tab = SimpleNamespace(
        update_dashboard=lambda *args: dashboard_calls.append(args),
        update_tcra_overview=lambda overview, agenda: tcra_calls.append((overview, agenda)),
    )
    window = SimpleNamespace(
        dash_tab=dash_tab,
        is_dark_mode=False,
        shell_controller=SimpleNamespace(
            resolved_dashboard_record_overview=lambda: "local-overview",
        ),
        _dashboard_record_overview=None,
        _local_record_read_status="sqlite-read",
        _pending_dashboard_metrics={"pend_micro_sorted": [("Gregorio", 2)]},
        tcra_tab=SimpleNamespace(build_dashboard_payload=lambda: ("tcra-overview", ("agenda-1", "agenda-2"))),
    )

    controller = WindowNavigationController(window)

    controller._render_dashboard({"pend_micro_sorted": [("Gregorio", 2)]})

    assert dashboard_calls
    assert dashboard_calls[-1][0]["pend_micro_sorted"] == [("Gregorio", 2)]
    assert tcra_calls == [("tcra-overview", ("agenda-1", "agenda-2"))]


def test_window_navigation_controller_refreshes_official_cache_before_operations_tab(monkeypatch):
    sync_calls = []
    operations_calls = []

    monkeypatch.setattr(nav_module, "apply_window_responsive_layout", lambda *args, **kwargs: True)
    monkeypatch.setattr(nav_module, "schedule_window_fit", lambda *args, **kwargs: True)

    operations_tab = object()
    window = SimpleNamespace(
        tabs=SimpleNamespace(currentWidget=lambda: operations_tab),
        dash_tab=object(),
        operations_tab=operations_tab,
        tcra_tab=SimpleNamespace(handle_tab_activated=lambda: None),
        shell_controller=SimpleNamespace(sync_global_search_context=lambda: sync_calls.append("search")),
        data_controller=SimpleNamespace(refresh_production_snapshot_if_stale=lambda *, force=False: sync_calls.append(("refresh", force)) or True),
        operations_controller=SimpleNamespace(refresh_overview=lambda: operations_calls.append("operations")),
        _dashboard_dirty=False,
        _pending_dashboard_metrics=None,
    )

    controller = WindowNavigationController(window)
    controller.on_tab_changed(1)

    assert sync_calls == ["search", ("refresh", False)]
    assert operations_calls == []


def test_window_navigation_controller_keeps_regular_operations_refresh_when_cache_not_refreshed(monkeypatch):
    calls = []

    monkeypatch.setattr(nav_module, "apply_window_responsive_layout", lambda *args, **kwargs: True)
    monkeypatch.setattr(nav_module, "schedule_window_fit", lambda *args, **kwargs: True)

    operations_tab = object()
    window = SimpleNamespace(
        tabs=SimpleNamespace(currentWidget=lambda: operations_tab),
        dash_tab=object(),
        operations_tab=operations_tab,
        tcra_tab=SimpleNamespace(handle_tab_activated=lambda: None),
        shell_controller=SimpleNamespace(sync_global_search_context=lambda: calls.append("search")),
        data_controller=SimpleNamespace(refresh_production_snapshot_if_stale=lambda *, force=False: calls.append(("refresh", force)) or False),
        operations_controller=SimpleNamespace(refresh_overview=lambda: calls.append("operations")),
        _dashboard_dirty=False,
        _pending_dashboard_metrics=None,
    )

    controller = WindowNavigationController(window)
    controller.on_tab_changed(1)

    assert calls == ["search", ("refresh", False), "operations"]


def test_window_navigation_controller_refreshes_admin_tab_when_activated(monkeypatch):
    calls = []

    monkeypatch.setattr(nav_module, "apply_window_responsive_layout", lambda *args, **kwargs: True)
    monkeypatch.setattr(nav_module, "schedule_window_fit", lambda *args, **kwargs: True)

    admin_tab = SimpleNamespace(handle_tab_activated=lambda: calls.append("admin"))
    window = SimpleNamespace(
        tabs=SimpleNamespace(currentWidget=lambda: admin_tab),
        dash_tab=object(),
        operations_tab=object(),
        tcra_tab=SimpleNamespace(handle_tab_activated=lambda: calls.append("tcra")),
        admin_users_tab=admin_tab,
        shell_controller=SimpleNamespace(sync_global_search_context=lambda: calls.append("search")),
        data_controller=SimpleNamespace(refresh_production_snapshot_if_stale=lambda *, force=False: False),
        operations_controller=SimpleNamespace(refresh_overview=lambda: calls.append("operations")),
        _dashboard_dirty=False,
        _pending_dashboard_metrics=None,
    )

    controller = WindowNavigationController(window)
    controller.on_tab_changed(0)

    assert calls == ["search", "admin"]
