from app.application.use_cases.map_layer_operations import MapLayerOperationsUseCases


def test_map_layer_operations_builds_loading_message_and_presentation():
    use_cases = MapLayerOperationsUseCases()

    presentation = use_cases.load_custom_layer(
        "C:/tmp/camada.geojson",
        geojson_loader=lambda path: {"type": "FeatureCollection", "features": [{"path": path}]},
    )

    assert presentation.filename == "camada.geojson"
    assert presentation.loading_message == "Carregando camada: camada.geojson..."
    assert presentation.success_title == "Sucesso"
    assert presentation.success_message == "Camada carregada com sucesso."
    assert "window.customLayer = L.geoJSON" in presentation.command.script
    assert '"path": "C:/tmp/camada.geojson"' in presentation.command.script
