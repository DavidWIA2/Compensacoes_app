from app.models.compensacao import Compensacao
from app.services.records_service import (
    compute_metrics,
    filter_records,
    to_float,
    unique_non_empty,
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
        "latitude": "",
        "longitude": "",
    }
    base.update(overrides)
    return Compensacao(**base)


def test_unique_non_empty_deduplicates_case_insensitive():
    values = ["Gregorio", "gregorio", "", "  ", "Monjolinho"]

    assert unique_non_empty(values) == ["Gregorio", "Monjolinho"]


def test_to_float_handles_comma_and_invalid_values():
    assert to_float("2,5") == 2.5
    assert to_float("abc") == 0.0


def test_compute_metrics_matches_expected_totals():
    records = [
        make_record(compensacao="10", compensado=""),
        make_record(excel_row=3, compensacao="5.5", compensado="SIM", microbacia="Monjolinho"),
    ]

    metrics = compute_metrics(records)

    assert metrics["total_geral"] == 15.5
    assert metrics["total_pendente"] == 10.0
    assert metrics["total_compensado"] == 5.5


def test_filter_records_applies_text_status_and_micro_filters():
    records = [
        make_record(oficio_processo="ABC-1", microbacia="Gregorio", compensado=""),
        make_record(excel_row=3, oficio_processo="XYZ-2", microbacia="Monjolinho", compensado="SIM"),
    ]

    filtered = filter_records(
        records,
        text="abc",
        status="Pendentes",
        selected_micros=["Gregorio"],
        selected_eletronicos=[],
        micro_all_selected=False,
        eletronico_all_selected=True,
    )

    assert len(filtered) == 1
    assert filtered[0].oficio_processo == "ABC-1"
