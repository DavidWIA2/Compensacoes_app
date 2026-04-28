import sys
from pathlib import Path

from app.services.tile_proxy_service import TileProxyService
from app.services.tile_scheme_handler import TileSchemeHandler


def test_disk_cache_path_uses_safe_filename_and_roundtrips(tmp_path):
    service = TileProxyService()
    service._disk_cache_dir = str(tmp_path)

    key = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/1/3/2"
    path = Path(service._get_disk_cache_path(key))

    service._write_to_disk(key, b"tile-bytes", "image/png")

    assert ":" not in path.name
    assert path.exists()
    assert service._read_from_disk(key) == (b"tile-bytes", "image/png")


def test_tile_proxy_does_not_persist_official_osm_tiles_to_disk(tmp_path):
    service = TileProxyService()
    service._disk_cache_dir = str(tmp_path)
    key = "https://tile.openstreetmap.org/1/2/3.png"

    service._write_to_disk(key, b"tile-bytes", "image/png")

    assert not Path(service._get_disk_cache_path(key)).exists()
    assert service._read_from_disk(key) is None


def test_tile_proxy_service_uses_user_data_dir_when_frozen(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    service = TileProxyService()

    assert Path(service._disk_cache_dir) == (
        tmp_path / "CompensacoesApp" / "CompensacoesDesktop" / "data" / "tiles_cache"
    )


def test_satellite_labels_providers_are_available_in_proxy_and_scheme():
    expected_suffixes = {
        "esri_places": "World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        "esri_transportation": "World_Transportation/MapServer/tile/{z}/{y}/{x}",
    }
    for provider, suffix in expected_suffixes.items():
        assert TileProxyService._PROVIDERS[provider].endswith(suffix)
        assert TileSchemeHandler._PROVIDERS[provider].endswith(suffix)
