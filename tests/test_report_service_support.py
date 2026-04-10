from datetime import datetime

from app.models.compensacao import Compensacao
from app.services.report_service_support import (
    INSTITUTIONAL_APP_NAME,
    build_dashboard_chart_rows,
    build_department_header_html_lines,
    build_grid_pdf_layout,
    build_individual_report_rows,
    build_records_to_dict_list,
    build_report_metadata_rows,
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
        "compensado": "SIM",
        "endereco_plantio": "Rua Plantio",
        "latitude": "",
        "longitude": "",
        "latitude_plantio": "-22.05",
        "longitude_plantio": "-47.95",
        "uid": "u-1",
    }
    base.update(overrides)
    return Compensacao(**base)


def test_support_builds_individual_rows_with_observation():
    rows = build_individual_report_rows(make_record(), "Linha 1\nLinha 2")

    assert rows[0] == ["Ofício/Processo:", "123/2026", "Tipo:", "Eletrônico"]
    assert ["Coord. Plantio:", "-22.05, -47.95", "", ""] in rows
    assert ["Observações:", "Linha 1\nLinha 2", "", ""] in rows


def test_support_builds_record_dicts_with_readable_tipo():
    rows = build_records_to_dict_list(
        [make_record(eletronico="SIM")],
        ["oficio_processo", "eletronico"],
    )

    assert rows == [{"Ofício/ Processo": "123/2026", "Tipo": "Eletrônico"}]


def test_support_builds_grid_pdf_layout_with_wider_address_column():
    layout = build_grid_pdf_layout(
        ["oficio_processo", "endereco", "caixa"],
        page_width=900,
    )

    assert layout.headers == ("Ofício/ Processo", "Endereço", "Caixa")
    assert layout.column_widths[1] > layout.column_widths[0]
    assert layout.column_widths[1] > layout.column_widths[2]


def test_support_builds_dashboard_chart_rows():
    rows = build_dashboard_chart_rows(["pie.png", "bar.png", "line.png"])

    assert rows == (("pie.png", "bar.png"), ("line.png", ""))


def test_support_exposes_shared_department_header_lines():
    lines = build_department_header_html_lines()

    assert lines[0] == "PREFEITURA MUNICIPAL DE S&Atilde;O CARLOS"
    assert lines[-1] == "Se&ccedil;&atilde;o de Recupera&ccedil;&atilde;o Ambiental"


def test_support_builds_institutional_report_metadata_rows():
    rows = build_report_metadata_rows(
        "Status: Pendente",
        source_label="Painel executivo",
        generated_at=datetime(2026, 4, 9, 14, 33),
    )

    assert rows[0].label == "Sistema"
    assert rows[0].value == INSTITUTIONAL_APP_NAME
    assert rows[1].value == "Painel executivo"
    assert rows[2].value == "09/04/2026 14:33"
    assert rows[3].value == "Status: Pendente"
