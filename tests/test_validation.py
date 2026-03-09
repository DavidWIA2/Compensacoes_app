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
