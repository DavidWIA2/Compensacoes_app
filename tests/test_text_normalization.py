from app.utils.text_normalization import (
    looks_like_mojibake,
    repair_mojibake_object,
    repair_mojibake_text,
)


def test_repair_mojibake_text_decodes_utf8_latin1_corruption():
    assert repair_mojibake_text("Parque EcolÃ³gico") == "Parque Ecológico"
    assert repair_mojibake_text("autorizaÃ§Ã£o") == "autorização"


def test_repair_mojibake_text_preserves_clean_text():
    assert repair_mojibake_text("Parque Ecológico") == "Parque Ecológico"
    assert looks_like_mojibake("Parque Ecológico") is False


def test_repair_mojibake_object_recurses_through_nested_structures():
    payload = {
        "summary": "RelatÃ³rio",
        "nested": [{"local": "VarjÃ£o"}],
    }

    assert repair_mojibake_object(payload) == {
        "summary": "Relatório",
        "nested": [{"local": "Varjão"}],
    }
