import openpyxl

from app.models.compensacao import Compensacao
from app.services.report_service import (
    ALL_COLUMNS,
    _build_footer_right_text,
    _build_individual_pdf_rows,
    export_excel_two_sheets,
)
from app.services.report_service_support import resolve_report_logo_path


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


def test_report_service_uses_readable_column_labels():
    headers = [label for label, _attr in ALL_COLUMNS]

    assert "Ofício/ Processo" in headers
    assert "Tipo" in headers
    assert "Compensação" in headers
    assert "Endereço" in headers
    assert "Endereço do Plantio" in headers


def test_individual_pdf_rows_include_plantio_coordinates_when_present():
    rows = _build_individual_pdf_rows(make_record())

    assert rows[0] == ["Ofício/Processo:", "123/2026", "Tipo:", "Eletrônico"]
    assert ["Coord. Plantio:", "-22.05, -47.95", "", ""] in rows
    assert not any(row[0] == "Coordenadas:" and row[1] == "" for row in rows)


def test_report_logo_prefers_prefeitura_asset():
    logo_path = resolve_report_logo_path().replace("\\", "/")

    assert logo_path.endswith("assets/logo_prefeitura.png")


def test_footer_right_text_includes_emitter_when_available():
    footer_text = _build_footer_right_text(
        generated_label="13/04/2026 15:55",
        page_number=2,
        emitted_by="david.oliveira",
    )

    assert footer_text == "Emitido em 13/04/2026 15:55 | por david.oliveira | Página 2"


def test_export_excel_two_sheets_applies_institutional_metadata(tmp_path):
    path = tmp_path / "relatorio.xlsx"

    export_excel_two_sheets(
        str(path),
        [make_record()],
        "Status: Todos",
        ["oficio_processo", "endereco", "compensacao"],
        [("Total de Registros", "1"), ("Total de Mudas", "10")],
        [("Gregorio", 10)],
        [("Eletrônico", 10)],
    )

    workbook = openpyxl.load_workbook(path)
    summary = workbook["Resumo Gerencial"]

    assert workbook.properties.title == "Relatório de Compensações"
    assert workbook.properties.subject == "Resumo gerencial de compensações"
    assert summary["A1"].value == "Relatório de Compensações"
    assert summary["A4"].value == "Sistema"
    assert summary["B4"].value == "Plataforma de Gestão Ambiental"
    assert summary["A10"].value == "INDICADORES GERAIS"
