from app.models.compensacao import Compensacao
from app.services.report_service import ALL_COLUMNS, _build_individual_pdf_rows


def test_report_service_uses_readable_column_labels():
    headers = [label for label, _attr in ALL_COLUMNS]

    assert "Of\u00edcio/ Processo" in headers
    assert "Eletr\u00f4nico" in headers
    assert "Compensa\u00e7\u00e3o" in headers
    assert "Endere\u00e7o" in headers
    assert "Endere\u00e7o do Plantio" in headers


def test_individual_pdf_rows_include_plantio_coordinates_when_present():
    record = Compensacao(
        excel_row=2,
        oficio_processo="123/2026",
        eletronico="SIM",
        caixa="CX-1",
        av_tec="AT-1",
        compensacao="10",
        endereco="Rua A",
        microbacia="Gregorio",
        compensado="SIM",
        endereco_plantio="Rua Plantio",
        latitude="",
        longitude="",
        latitude_plantio="-22.05",
        longitude_plantio="-47.95",
        uid="u-1",
    )

    rows = _build_individual_pdf_rows(record)

    assert ["Coord. Plantio:", "-22.05, -47.95", "", ""] in rows
    assert not any(row[0] == "Coordenadas:" and row[1] == "" for row in rows)
