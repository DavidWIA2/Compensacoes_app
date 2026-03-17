from datetime import date

from app.models.compensacao import Compensacao
from app.services.validation import validate_compensacao


MSG_OFICIO = "Preencha Of\u00edcio/Processo."
MSG_COMPENSACAO = "Preencha Compensa\u00e7\u00e3o."


def make_compensacao(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "A1",
        "av_tec": "AV-10",
        "compensacao": "5",
        "endereco": "Rua Teste",
        "microbacia": "Gregorio",
        "compensado": "",
        "latitude": "",
        "longitude": "",
    }
    base.update(overrides)
    return Compensacao(**base)


def test_validate_compensacao_requires_oficio():
    item = make_compensacao(oficio_processo=" ")

    assert validate_compensacao(item) == MSG_OFICIO


def test_validate_compensacao_requires_av_tec():
    item = make_compensacao(av_tec="")

    assert validate_compensacao(item) == "Preencha Av. Tec."


def test_validate_compensacao_requires_compensacao():
    item = make_compensacao(compensacao="")

    assert validate_compensacao(item) == MSG_COMPENSACAO


def test_validate_compensacao_accepts_complete_record():
    item = make_compensacao()

    assert validate_compensacao(item) == ""


def test_validate_compensacao_rejects_future_oficio_year():
    next_year = date.today().year + 1
    item = make_compensacao(oficio_processo=f"123/{next_year}")

    assert validate_compensacao(item) == f"O ano de Ofício/Processo não pode ser maior que {date.today().year}."


def test_validate_compensacao_accepts_current_oficio_year():
    current_year = date.today().year
    item = make_compensacao(oficio_processo=f"123/{current_year}")

    assert validate_compensacao(item) == ""


def test_validate_compensacao_requires_compensacao_when_none():
    item = make_compensacao(compensacao=None)

    assert validate_compensacao(item) == MSG_COMPENSACAO


def test_validate_compensacao_requires_numeric_value():
    item = make_compensacao(compensacao="abc")

    assert validate_compensacao(item) == "Compensa\u00e7\u00e3o deve ser num\u00e9rica."


def test_validate_compensacao_requires_positive_value():
    item = make_compensacao(compensacao="0")

    assert validate_compensacao(item) == "Compensa\u00e7\u00e3o deve ser maior que zero."


def test_validate_compensacao_accepts_brazilian_number_format():
    item = make_compensacao(compensacao="1.234,56")

    assert validate_compensacao(item) == ""


def test_validate_compensacao_requires_lat_lon_together():
    item = make_compensacao(latitude="-22.0", longitude="")

    assert validate_compensacao(item) == "Preencha latitude e longitude juntas."


def test_validate_compensacao_rejects_invalid_lat_lon_values():
    item = make_compensacao(latitude="abc", longitude="-47")

    assert validate_compensacao(item) == "Latitude/Longitude invalidas."


def test_validate_compensacao_rejects_out_of_range_coordinates():
    item = make_compensacao(latitude="-91", longitude="-47")

    assert validate_compensacao(item) == "Latitude deve estar entre -90 e 90."
