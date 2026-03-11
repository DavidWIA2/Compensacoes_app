from app.services.report_service import ALL_COLUMNS


def test_report_service_uses_readable_column_labels():
    headers = [label for label, _attr in ALL_COLUMNS]

    assert "Ofício/ Processo" in headers
    assert "Eletrônico" in headers
    assert "Compensação" in headers
    assert "Endereço" in headers
