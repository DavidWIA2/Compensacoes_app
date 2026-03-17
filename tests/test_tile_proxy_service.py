from pathlib import Path

from app.services.tile_proxy_service import TileProxyService


def test_disk_cache_path_uses_safe_filename_and_roundtrips(tmp_path):
    service = TileProxyService()
    service._disk_cache_dir = str(tmp_path)

    key = "https://tile.openstreetmap.org/1/2/3.png"
    path = Path(service._get_disk_cache_path(key))

    service._write_to_disk(key, b"tile-bytes", "image/png")

    assert ":" not in path.name
    assert path.exists()
    assert service._read_from_disk(key) == (b"tile-bytes", "image/png")
