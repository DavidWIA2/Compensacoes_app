from pathlib import Path

from app.services import mapbox_config


def test_resolve_mapbox_access_token_prefers_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("MAPBOX_ACCESS_TOKEN", "pk.env-token")
    monkeypatch.setenv("COMP_MAPBOX_TOKEN_FILE", str(tmp_path / "mapbox_token.txt"))
    (tmp_path / "mapbox_token.txt").write_text("pk.file-token\n", encoding="utf-8")

    assert mapbox_config.resolve_mapbox_access_token() == "pk.env-token"


def test_mapbox_access_token_can_be_saved_and_removed(monkeypatch, tmp_path):
    token_path = tmp_path / "mapbox_token.txt"
    monkeypatch.delenv("MAPBOX_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("COMP_MAPBOX_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("COMP_MAPBOX_TOKEN_FILE", str(token_path))

    saved_path = mapbox_config.save_mapbox_access_token(" pk.saved-token \n")

    assert saved_path == Path(token_path)
    assert mapbox_config.resolve_mapbox_access_token() == "pk.saved-token"

    mapbox_config.save_mapbox_access_token("")

    assert not token_path.exists()
    assert mapbox_config.resolve_mapbox_access_token() == ""


def test_mapbox_usage_counts_monthly_and_caps_at_limit(monkeypatch, tmp_path):
    usage_path = tmp_path / "mapbox_usage.json"
    monkeypatch.setattr(mapbox_config, "resolve_mapbox_usage_file_path", lambda: usage_path)
    monkeypatch.delenv("COMP_MAPBOX_TILE_LIMIT", raising=False)

    mapbox_config.save_mapbox_monthly_tile_limit(5)
    usage = mapbox_config.record_mapbox_tile_requests(3, month="2026-04")
    usage = mapbox_config.record_mapbox_tile_requests(10, month="2026-04")

    assert usage.month == "2026-04"
    assert usage.tiles_used == 5
    assert usage.monthly_limit == 5
    assert usage.limit_reached is True
    assert mapbox_config.read_mapbox_usage(month="2026-05").tiles_used == 0


def test_mapbox_tile_limit_defaults_to_safe_pilot_size(monkeypatch, tmp_path):
    monkeypatch.setattr(mapbox_config, "resolve_mapbox_usage_file_path", lambda: tmp_path / "usage.json")
    monkeypatch.delenv("COMP_MAPBOX_TILE_LIMIT", raising=False)

    assert mapbox_config.resolve_mapbox_monthly_tile_limit() == 5000
