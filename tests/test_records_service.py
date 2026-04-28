from app.models.compensacao import Compensacao
from app.services.records_service import (
    build_record_search_index,
    compute_metrics,
    display_tipo_value,
    extract_year,
    filter_records,
    storage_tipo_value,
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


def test_extract_year_prioritizes_year_after_slash_with_origin_suffix():
    assert extract_year("3529/2024 - SAAE") == "2024"
    assert extract_year("3529/2024-SAAE") == "2024"


def test_tipo_helpers_normalize_legacy_values():
    assert display_tipo_value("SIM") == "Eletrônico"
    assert display_tipo_value("NAO") == "Físico"
    assert display_tipo_value("") == "Nulo"
    assert storage_tipo_value("Nulo") == ""


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


def test_filter_records_treats_microbacia_filter_as_accent_insensitive():
    records = [
        make_record(oficio_processo="ABC-1", microbacia="Gregorio", compensado=""),
        make_record(excel_row=3, oficio_processo="XYZ-2", microbacia="Medeiros", compensado=""),
    ]

    filtered = filter_records(
        records,
        text="",
        status="Todos",
        selected_micros=["Gregório"],
        selected_eletronicos=[],
        micro_all_selected=False,
        eletronico_all_selected=True,
    )

    assert [record.oficio_processo for record in filtered] == ["ABC-1"]


def test_filter_records_uses_precomputed_search_index_for_endereco_plantio():
    records = [
        make_record(oficio_processo="ABC-1", endereco="", endereco_plantio="Rua do Plantio", uid="u-1"),
    ]

    filtered = filter_records(
        records,
        text="plantio",
        status="Todos",
        selected_micros=[],
        selected_eletronicos=[],
        micro_all_selected=True,
        eletronico_all_selected=True,
        search_index=build_record_search_index(records),
    )

    assert filtered == records


def test_filter_records_accepts_display_tipo_filter_for_legacy_values():
    records = [
        make_record(eletronico="SIM", uid="u-1"),
        make_record(excel_row=3, eletronico="NAO", uid="u-2", av_tec="AT-2"),
    ]

    filtered = filter_records(
        records,
        text="",
        status="Todos",
        selected_micros=[],
        selected_eletronicos=["Eletrônico"],
        micro_all_selected=True,
        eletronico_all_selected=False,
    )

    assert [record.uid for record in filtered] == ["u-1"]


def test_filter_records_applies_caixa_filter():
    records = [
        make_record(caixa="Arquivado", uid="u-1"),
        make_record(excel_row=3, caixa="CX-3", uid="u-2", av_tec="AT-2"),
    ]

    filtered = filter_records(
        records,
        text="",
        status="Todos",
        selected_micros=[],
        selected_eletronicos=[],
        micro_all_selected=True,
        eletronico_all_selected=True,
        selected_caixas=["Arquivado"],
        caixa_all_selected=False,
    )

    assert [record.uid for record in filtered] == ["u-1"]
