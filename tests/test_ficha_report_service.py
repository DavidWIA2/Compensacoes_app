from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem
from app.services.ficha_report_service import (
    _build_ficha_rows,
    _build_plantios_rows,
    _resolve_signature_label,
    _resolve_ficha_logo_path,
    export_individual_pdf,
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

    assert rows[0] == ["Ofício/Processo:", "123/2026", "Tipo:", "Eletrônico"]
    assert ["Observações:", "Linha 1\nLinha 2", "", ""] in rows


def test_ficha_logo_prefers_prefeitura_asset():
    logo_path = _resolve_ficha_logo_path().replace("\\", "/")

    assert logo_path.endswith("assets/logo_prefeitura.png")


def test_resolve_signature_label_prefers_logged_user_name():
    assert _resolve_signature_label("David Wiliam Pinheiro de Oliveira") == "David Wiliam Pinheiro de Oliveira"
    assert _resolve_signature_label("") == "Assinatura do T\u00e9cnico Respons\u00e1vel"


def test_export_individual_pdf_generates_file_with_header_observation_and_footer(tmp_path, monkeypatch):
    path = tmp_path / "ficha.pdf"
    footer_calls = []

    monkeypatch.setattr(
        "app.services.ficha_report_service.draw_pdf_page_frame",
        lambda canvas, doc, *, title, generated_label, emitted_by="": footer_calls.append(
            {
                "title": title,
                "generated_label": generated_label,
                "emitted_by": emitted_by,
            }
        ),
    )

    export_individual_pdf(
        str(path),
        make_record(),
        "Observacao de teste",
        emitted_by="david.oliveira",
        signature_name="David Wiliam Pinheiro de Oliveira",
    )

    assert path.exists()
    assert path.stat().st_size > 0
    assert len(footer_calls) == 1
    assert footer_calls[0]["title"] == "Ficha de Compensa\u00e7\u00e3o Ambiental"
    assert footer_calls[0]["generated_label"]
    assert footer_calls[0]["emitted_by"] == "david.oliveira"


def test_build_plantios_rows_lists_all_registered_plantios():
    rows = _build_plantios_rows(
        make_record(
            plantios=[
                PlantioItem(sequence=1, endereco="Rua Plantio A", qtd_mudas="3", latitude="-22.01", longitude="-47.89"),
                PlantioItem(sequence=2, endereco="Rua Plantio B", qtd_mudas="7", latitude="-22.02", longitude="-47.90"),
            ]
        )
    )

    assert rows == [
        ["1", "Rua Plantio A", "3", "-22.01, -47.89"],
        ["2", "Rua Plantio B", "7", "-22.02, -47.90"],
    ]
