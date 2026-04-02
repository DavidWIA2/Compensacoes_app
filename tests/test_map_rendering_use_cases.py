from app.application.use_cases.map_rendering import MapRenderingUseCases
from app.models.compensacao import Compensacao


def make_record(**overrides) -> Compensacao:
    payload = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "Gregorio",
        "compensado": "",
        "endereco_plantio": "",
        "latitude": "-22.01",
        "longitude": "-47.89",
        "uid": "map-render-1",
    }
    payload.update(overrides)
    return Compensacao(**payload)


def test_map_rendering_builds_heatmap_points_and_commands():
    use_cases = MapRenderingUseCases()
    records = [
        make_record(latitude="-22.01", longitude="-47.89"),
        make_record(excel_row=3, uid="map-render-2", latitude="-22.02", longitude="-47.90"),
    ]

    enabled_points = use_cases.build_heatmap_points(records, "Pendentes", enabled=True)
    disabled_points = use_cases.build_heatmap_points(records, "Pendentes", enabled=False)
    marker = use_cases.build_marker_command(-22.01, -47.89)
    status = use_cases.build_status_command("Mapa sincronizado")
    heatmap = use_cases.build_heatmap_command([[-22.01, -47.89]])

    assert enabled_points == [[-22.01, -47.89], [-22.02, -47.9]]
    assert disabled_points == []
    assert "window.setMarker(-22.01, -47.89)" in marker.script
    assert '"Mapa sincronizado"' in status.script
    assert "window.setHeatmap([[-22.01, -47.89]])" in heatmap.script


def test_map_rendering_builds_initial_sync_commands_and_custom_layer_script():
    use_cases = MapRenderingUseCases()

    commands = use_cases.build_initial_sync_commands(
        theme="dark",
        geojson_data={"type": "FeatureCollection", "features": []},
        current_layer="OpenStreetMap",
        marker_coords=(-22.01, -47.89),
        heatmap_points=[[-22.05, -47.95]],
    )
    custom_layer = use_cases.build_custom_layer_command({"type": "FeatureCollection", "features": []})
    highlight = use_cases.build_highlight_command("Nome_Do_Arquivo", "Gregorio")

    assert [command.context for command in commands] == ["theme", "micro", "layer", "marker", "heat"]
    assert "window.setTheme(\"dark\")" in commands[0].script
    assert "window.setMicrobacias" in commands[1].script
    assert "window.setBaseLayer(\"OpenStreetMap\")" in commands[2].script
    assert "window.setMarker(-22.01, -47.89)" in commands[3].script
    assert "window.setHeatmap([[-22.05, -47.95]])" in commands[4].script
    assert "window.customLayer = L.geoJSON" in custom_layer.script
    assert "window.highlightGeoJsonByName(\"Nome_Do_Arquivo\", \"Gregorio\")" in highlight.script
