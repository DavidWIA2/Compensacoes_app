from types import SimpleNamespace

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
