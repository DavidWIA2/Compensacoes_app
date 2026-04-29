from pathlib import Path

from app.config import (
    GEOCODER_FALLBACK_PROVIDER,
    GEOCODER_PROVIDER,
    GEOCODER_RATE_LIMIT_SECONDS,
    MAP_DEFAULT_BASE_LAYER,
    MAP_ENGINE,
    MAP_FALLBACK_ENGINE,
    MAP_PROVIDER,
)
from app.services.map_engine import normalize_map_engine, resolve_map_engine_resource


def test_map_provider_configuration_defaults_to_free_stack():
    assert MAP_ENGINE == "maplibre"
    assert MAP_FALLBACK_ENGINE == "leaflet"
    assert MAP_DEFAULT_BASE_LAYER == "satellite"
    assert MAP_PROVIDER == "osm_esri"
    assert GEOCODER_PROVIDER == "nominatim"
    assert GEOCODER_FALLBACK_PROVIDER == "arcgis"
    assert GEOCODER_RATE_LIMIT_SECONDS == 1.0


def test_resolve_map_engine_resource_prefers_maplibre_with_leaflet_fallback():
    resource = resolve_map_engine_resource("maplibre", "leaflet")

    assert resource.engine == "maplibre"
    assert resource.fallback_engine == "leaflet"
    assert resource.html_path.endswith("map_maplibre.html")
    assert resource.fallback_html_path.endswith("map_leaflet.html")
    assert Path(resource.html_path).exists()
    assert Path(resource.fallback_html_path).exists()


def test_normalize_map_engine_falls_back_to_leaflet():
    assert normalize_map_engine("unknown") == "leaflet"
    assert normalize_map_engine("MAPLIBRE") == "maplibre"
