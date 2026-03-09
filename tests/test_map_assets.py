from pathlib import Path


def test_map_uses_local_leaflet_assets_and_heatmap_fallback():
    html = Path(r"E:/Compensacoes_app/app/ui/map_leaflet.html").read_text(encoding="utf-8")

    assert 'vendor/leaflet/leaflet.css' in html
    assert 'vendor/leaflet/leaflet.js' in html
    assert 'typeof L.heatLayer !== "function"' in html
