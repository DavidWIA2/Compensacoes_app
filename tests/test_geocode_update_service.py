from app.models.compensacao import Compensacao
from app.services.geocode_update_service import (
    apply_geocode_to_record,
    build_cached_microbacia_finder,
    find_record_by_excel_row,
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
        "microbacia": "",
        "compensado": "",
        "latitude": "",
        "longitude": "",
    }
    base.update(overrides)
    return Compensacao(**base)


def test_find_record_by_excel_row_returns_matching_record():
    records = [make_record(excel_row=2), make_record(excel_row=5)]

    found = find_record_by_excel_row(records, 5)

    assert found is not None
    assert found.excel_row == 5


def test_find_record_by_excel_row_returns_none_when_missing():
    records = [make_record(excel_row=2)]

    assert find_record_by_excel_row(records, 99) is None


def test_apply_geocode_to_record_sets_coordinates_and_microbacia():
    record = make_record()

    micro = apply_geocode_to_record(record, -22.01, -47.89, lambda lat, lon: "Gregorio")

    assert micro == "Gregorio"
    assert record.latitude == "-22.01"
    assert record.longitude == "-47.89"
    assert record.microbacia == "Gregorio"


def test_apply_geocode_to_record_ignores_microbacia_on_finder_error():
    record = make_record(microbacia="Anterior")

    def failing_finder(lat, lon):
        raise RuntimeError("boom")

    micro = apply_geocode_to_record(record, -22.01, -47.89, failing_finder)

    assert micro == ""
    assert record.latitude == "-22.01"
    assert record.longitude == "-47.89"
    assert record.microbacia == "Anterior"


def test_build_cached_microbacia_finder_reuses_previous_lookup():
    calls = []

    def finder(lat, lon):
        calls.append((lat, lon))
        return "Gregorio"

    cached = build_cached_microbacia_finder(finder)

    assert cached(-22.0100001, -47.8900001) == "Gregorio"
    assert cached(-22.0100002, -47.8900002) == "Gregorio"
    assert len(calls) == 1
