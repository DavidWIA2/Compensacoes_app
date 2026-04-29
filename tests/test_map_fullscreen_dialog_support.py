from types import SimpleNamespace

from PySide6.QtCore import QUrlQuery

from app.ui.components.dialogs import MapFullScreenDialog
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


def test_map_fullscreen_dialog_uses_http_tile_proxy_when_available():
    proxy = SimpleNamespace(start=lambda: "http://127.0.0.1:8123")

    url = MapFullScreenDialog._build_map_url("C:/tmp/map_leaflet.html", proxy)
    query = QUrlQuery(url)

    assert query.queryItemValue("mapEngine") == "leaflet"
    assert query.queryItemValue("tileProxy") == "http://127.0.0.1:8123"
    assert query.queryItemValue("tileScheme") == ""


def test_map_fullscreen_dialog_does_not_include_mapbox_token(monkeypatch):
    monkeypatch.setenv("MAPBOX_ACCESS_TOKEN", "pk.test-token")
    proxy = SimpleNamespace(start=lambda: "http://127.0.0.1:8123")

    url = MapFullScreenDialog._build_map_url("C:/tmp/map_leaflet.html", proxy)
    query = QUrlQuery(url)

    assert query.queryItemValue("tileProxy") == "http://127.0.0.1:8123"
    assert query.queryItemValue("mapboxToken") == ""


def test_map_fullscreen_dialog_falls_back_to_compmap_when_proxy_fails():
    proxy = SimpleNamespace(start=lambda: (_ for _ in ()).throw(RuntimeError("offline")))

    url = MapFullScreenDialog._build_map_url("C:/tmp/map_leaflet.html", proxy)
    query = QUrlQuery(url)

    assert query.queryItemValue("tileProxy") == ""
    assert query.queryItemValue("tileScheme") == "compmap"


def test_map_fullscreen_dialog_builds_maplibre_url_with_leaflet_fallback():
    proxy = SimpleNamespace(start=lambda: "http://127.0.0.1:8123")

    url = MapFullScreenDialog._build_map_url(
        "C:/tmp/map_maplibre.html",
        proxy,
        engine="maplibre",
        fallback_html_path="C:/tmp/map_leaflet.html",
    )
    query = QUrlQuery(url)

    assert query.queryItemValue("mapEngine") == "maplibre"
    assert query.queryItemValue("tileProxy") == "http://127.0.0.1:8123"
    assert query.queryItemValue("tileScheme") == ""
    assert query.queryItemValue("fallbackUrl").endswith("map_leaflet.html")
