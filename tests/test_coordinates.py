from app.models.compensacao import Compensacao
from app.services.coordinates import (
    build_heatmap_point,
    format_coordinate_pair,
    get_record_coordinates,
)


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "Gregorio",
        "compensado": "",
        "endereco_plantio": "Rua Plantio",
        "latitude": "-22.01",
        "longitude": "-47.89",
        "latitude_plantio": "-22.05",
        "longitude_plantio": "-47.95",
        "uid": "test-uid-123",
    }
    base.update(overrides)
    return Compensacao(**base)


def test_format_coordinate_pair_requires_complete_pair():
    assert format_coordinate_pair("-22.01", "-47.89") == "-22.01, -47.89"
    assert format_coordinate_pair("-22.01", "") == ""


def test_get_record_coordinates_supports_main_and_plantio_sources():
    record = make_record()

    assert get_record_coordinates(record, "main") == (-22.01, -47.89)
    assert get_record_coordinates(record, "plantio") == (-22.05, -47.95)


def test_build_heatmap_point_uses_plantio_coordinates_for_realizadas():
    record = make_record(compensado="SIM")

    assert build_heatmap_point(record, "Realizadas") == [-22.05, -47.95]
    assert build_heatmap_point(record, "Pendentes") is None
