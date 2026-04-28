from pathlib import Path


def test_map_uses_local_leaflet_assets_and_heatmap_fallback():
    # Caminho relativo a raiz do projeto (onde o pytest costuma rodar)
    # ou relativo ao proprio arquivo de teste
    base_dir = Path(__file__).resolve().parent.parent
    html_path = base_dir / "app" / "ui" / "map_leaflet.html"

    html = html_path.read_text(encoding="utf-8")

    assert 'vendor/leaflet/leaflet.css' in html
    assert 'vendor/leaflet/leaflet.js' in html
    assert 'typeof L.heatLayer !== "function"' in html
    assert '"Offline (grade)"' in html
    assert "BASE_FALLBACK_ORDER" in html
    assert "World_Transportation" in html
    assert "World_Boundaries_and_Places" in html
    assert "esri_transportation" in html
    assert "esri_places" in html
    assert "syncSatelliteLabels" in html
    assert "window.setSatelliteLabels" in html
    assert "let satelliteLabelsEnabled = false" in html
    assert "mapboxToken" in html
    assert "mapboxTileLimit" in html
    assert "onMapboxTilesRequested" in html
    assert "MapboxLimitedTileLayer" in html
    assert "Cota Mapbox atingida" in html
    assert "satellite-streets-v12" in html
    assert "Mapbox Satelite" in html
    assert "tileSize:512" in html
    assert "zoomOffset:-1" in html
    assert "Rótulos do satélite" in html
    assert 'map.on("overlayadd"' in html
    assert 'map.on("movestart zoomstart"' in html
    assert "updateWhenZooming:false" in html
    assert "updateWhenIdle:true" in html
    assert 'pane:"satellite-labels"' in html
    assert "minZoom:13" in html


def test_maplibre_asset_supports_free_satellite_stack_and_current_bridge():
    base_dir = Path(__file__).resolve().parent.parent
    html_path = base_dir / "app" / "ui" / "map_maplibre.html"

    html = html_path.read_text(encoding="utf-8")

    assert "maplibre-gl" in html
    assert "World_Imagery" in html
    assert "tile.openstreetmap.org" in html
    assert "World_Transportation" in html
    assert "World_Boundaries_and_Places" in html
    assert "Esri, Maxar, Earthstar Geographics" in html
    assert "OpenStreetMap contributors" in html
    assert "new maplibregl.AttributionControl" in html
    assert "cluster: true" in html
    assert "window.setBaseLayer" in html
    assert "window.setMarker" in html
    assert "window.setMarkers" in html
    assert "window.setPlantioMarkers" in html
    assert "window.setMicrobacias" in html
    assert "fallbackToLeaflet" in html
    assert "TODO" not in html
