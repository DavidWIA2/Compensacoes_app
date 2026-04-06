from app.models.compensacao import Compensacao
from app.services.records_service import display_tipo_value
from app.ui.tabs.data_tab_support import (
    build_column_texts_for_records,
    build_micro_rows,
    build_totals_rows,
    compute_crud_buttons_minimum_width,
    compute_preferred_left_panel_width,
    compute_preferred_right_panel_width,
    compute_splitter_anchor_left_width,
    compute_splitter_sizes,
    compute_target_column_width,
    resolve_column_width_bounds,
    resolve_splitter_anchor_character_index,
)


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
        "latitude": "",
        "longitude": "",
        "uid": "u-1",
    }
    payload.update(overrides)
    return Compensacao(**payload)


def test_data_tab_support_builds_column_texts_and_bounds():
    bounds = resolve_column_width_bounds(
        "endereco",
        scale_factor=1.25,
        rules={"endereco": {"min": 220, "max": 420}},
    )
    assert bounds.min_width == 275
    assert bounds.max_width == 525

    texts = build_column_texts_for_records(
        "eletronico",
        [make_record(eletronico="SIM"), make_record(eletronico="NAO", uid="u-2")],
        static_texts={"eletronico": ("Nulo",)},
        display_tipo_value=display_tipo_value,
    )
    assert texts[0] == "Nulo"
    assert texts[-2:] == [display_tipo_value("SIM"), display_tipo_value("NAO")]

    compensado_texts = build_column_texts_for_records(
        "compensado",
        [make_record(compensado="SIM"), make_record(compensado="", uid="u-3")],
        static_texts={},
        display_tipo_value=display_tipo_value,
    )
    assert compensado_texts == ["SIM", ""]


def test_data_tab_support_computes_layout_sizes():
    assert compute_target_column_width([90, 120, 140], padding=28, min_width=100, max_width=150) == 150
    assert compute_crud_buttons_minimum_width([100, 120, 80], spacing=8) == 316
    assert compute_preferred_left_panel_width(
        visible_columns_width=700,
        table_chrome_width=32,
        totals_min_width=420,
        export_min_width=380,
        panel_gap=10,
    ) == 742
    assert compute_preferred_right_panel_width(
        scale_factor=1.0,
        map_group_width=500,
        crud_buttons_width=640,
    ) == 640

    anchor_index = resolve_splitter_anchor_character_index("Tabela Tela Cheia")
    assert anchor_index == 9
    anchor_left = compute_splitter_anchor_left_width(
        splitter_x=20,
        button_x=100,
        text_origin_x=12,
        prefix_width=56,
        target_char_width=8,
        handle_width=8,
        nudge=4,
    )
    assert anchor_left == 152
    assert compute_splitter_sizes(
        total_width=1200,
        right_min_width=420,
        preferred_left_width=820,
        anchor_left_width=760,
    ) == (760, 440)


def test_data_tab_support_builds_totals_and_micro_rows():
    metrics = {
        "total_geral": 120.0,
        "total_pendente": 75.0,
        "total_compensado": 45.0,
        "pend_micro_sorted": [("Gregorio", 50.0), ("Monjolinho", 25.0)],
    }
    assert build_totals_rows(metrics) == [
        ("Total Mudas", "120"),
        ("Pendente", "75"),
        ("Compensado", "45"),
    ]
    assert build_micro_rows(metrics) == [("Gregorio", "50"), ("Monjolinho", "25")]
