from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import MAP_ENGINE, MAP_FALLBACK_ENGINE
from app.ui.components.ui_utils import resource_path


MAP_ENGINE_HTML = {
    "maplibre": "map_maplibre.html",
    "leaflet": "map_leaflet.html",
}


@dataclass(frozen=True)
class MapEngineResource:
    engine: str
    html_path: str
    fallback_engine: str
    fallback_html_path: str


def normalize_map_engine(engine: str | None, *, default: str = "leaflet") -> str:
    normalized = str(engine or "").strip().lower()
    return normalized if normalized in MAP_ENGINE_HTML else default


def resolve_map_engine_resource(engine: str | None = None, fallback_engine: str | None = None) -> MapEngineResource:
    selected_engine = normalize_map_engine(engine or MAP_ENGINE, default="maplibre")
    selected_fallback = normalize_map_engine(fallback_engine or MAP_FALLBACK_ENGINE, default="leaflet")
    html_path = resource_path("app", "ui", MAP_ENGINE_HTML[selected_engine])
    fallback_html_path = resource_path("app", "ui", MAP_ENGINE_HTML[selected_fallback])

    if not Path(html_path).exists() and Path(fallback_html_path).exists():
        selected_engine = selected_fallback
        html_path = fallback_html_path

    return MapEngineResource(
        engine=selected_engine,
        html_path=html_path,
        fallback_engine=selected_fallback,
        fallback_html_path=fallback_html_path,
    )
