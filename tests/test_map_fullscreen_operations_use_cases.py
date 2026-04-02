from app.application.use_cases.map_fullscreen_operations import MapFullscreenOperationsUseCases
from app.models.compensacao import Compensacao


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 3,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "Gregorio",
        "compensado": "",
        "uid": "uid-1",
        "latitude": "-22.01",
        "longitude": "-47.89",
        "latitude_plantio": "",
        "longitude_plantio": "",
    }
    base.update(overrides)
    return Compensacao(**base)


def test_build_heatmap_sync_result_respects_mode_and_enabled_state():
    use_cases = MapFullscreenOperationsUseCases()
    record = make_record(
        compensado="SIM",
        latitude_plantio="-22.05",
        longitude_plantio="-47.95",
    )

    enabled = use_cases.build_heatmap_sync_result(
        records=[record],
        mode="Realizadas",
        enabled=True,
    )
    disabled = use_cases.build_heatmap_sync_result(
        records=[record],
        mode="Realizadas",
        enabled=False,
    )

    assert enabled.points == ((-22.05, -47.95),)
    assert "window.setHeatmap" in enabled.command.script
    assert disabled.points == ()


def test_build_click_result_formats_status_and_marker_command():
    use_cases = MapFullscreenOperationsUseCases()

    result = use_cases.build_click_result(-22.01234, -47.98765)

    assert result.marker_coords == (-22.01234, -47.98765)
    assert result.status_message == "Ponto: -22.01234, -47.98765"
    assert "window.setMarker" in result.command.script


def test_search_address_returns_success_and_failure_presentations():
    use_cases = MapFullscreenOperationsUseCases()

    success = use_cases.search_address(
        address="Rua Teste",
        geocode_address=lambda _address: (-22.01, -47.89),
    )
    failure = use_cases.search_address(
        address="Rua Inexistente",
        geocode_address=lambda _address: None,
    )

    assert success.found is True
    assert success.marker_coords == (-22.01, -47.89)
    assert success.command is not None
    assert success.status_message == "Localizado (fora de microbacia)"

    assert failure.found is False
    assert failure.marker_coords is None
    assert failure.command is None
    assert failure.status_message
