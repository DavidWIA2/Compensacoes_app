from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FullscreenHeatmapSyncView:
    points: list[list[float]]
    script: str
    context: str


def build_fullscreen_heatmap_sync_view(*, use_cases: Any, records: list[Any], mode: str, enabled: bool) -> FullscreenHeatmapSyncView:
    result = use_cases.build_heatmap_sync_result(
        records=records,
        mode=mode,
        enabled=enabled,
    )
    return FullscreenHeatmapSyncView(
        points=[list(point) for point in result.points],
        script=result.command.script,
        context=result.command.context,
    )


def build_fullscreen_current_points(*, use_cases: Any, records: list[Any], mode: str, enabled: bool) -> list[list[float]]:
    return build_fullscreen_heatmap_sync_view(
        use_cases=use_cases,
        records=records,
        mode=mode,
        enabled=enabled,
    ).points


def run_fullscreen_map_script(page: Any, *, script: str, context: str, logger: Any) -> None:
    try:
        page.runJavaScript(script)
    except Exception as exc:
        if logger is not None:
            logger.error("[FS MAP JS] Falha em %s: %s", context, exc)
