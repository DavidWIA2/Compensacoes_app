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
