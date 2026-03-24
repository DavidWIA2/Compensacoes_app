from app.models.compensacao import Compensacao
from app.services.ficha_report_service import _build_ficha_rows, _resolve_ficha_logo_path, export_individual_pdf


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
        "latitude": "-22.01",
        "longitude": "-47.89",
        "latitude_plantio": "-22.05",
        "longitude_plantio": "-47.95",
        "uid": "u-1",
    }
    base.update(overrides)
    return Compensacao(**base)


def test_build_ficha_rows_include_observation():
    rows = _build_ficha_rows(make_record(), "Linha 1\nLinha 2")

    assert ["Observações:", "Linha 1\nLinha 2", "", ""] in rows


def test_ficha_logo_prefers_prefeitura_asset():
    logo_path = _resolve_ficha_logo_path().replace("\\", "/")

    assert logo_path.endswith("assets/logo_prefeitura.png")


def test_export_individual_pdf_generates_file_with_header_and_observation(tmp_path):
    path = tmp_path / "ficha.pdf"

    export_individual_pdf(str(path), make_record(), "Observacao de teste")

    assert path.exists()
    assert path.stat().st_size > 0
