from types import SimpleNamespace

from app.ui.components.map_fullscreen_dialog_support import (
    build_fullscreen_current_points,
    build_fullscreen_heatmap_sync_view,
    run_fullscreen_map_script,
)


def test_map_fullscreen_dialog_support_builds_points_and_command():
    use_cases = SimpleNamespace(
        build_heatmap_sync_result=lambda **kwargs: SimpleNamespace(
            points=((-22.05, -47.95),),
            command=SimpleNamespace(script="renderHeatmap()", context="heatmap_sync"),
        )
    )

    sync_view = build_fullscreen_heatmap_sync_view(
        use_cases=use_cases,
        records=[object()],
        mode="Realizadas",
        enabled=True,
    )

    assert sync_view.points == [[-22.05, -47.95]]
    assert sync_view.script == "renderHeatmap()"
    assert build_fullscreen_current_points(
        use_cases=use_cases,
        records=[object()],
        mode="Realizadas",
        enabled=True,
    ) == [[-22.05, -47.95]]


def test_map_fullscreen_dialog_support_logs_script_failures():
    messages = []
    logger = SimpleNamespace(error=lambda message, *args: messages.append(message % args))
    page = SimpleNamespace(runJavaScript=lambda _script: (_ for _ in ()).throw(RuntimeError("boom")))

    run_fullscreen_map_script(page, script="render()", context="init", logger=logger)

    assert messages == ["[FS MAP JS] Falha em init: boom"]
