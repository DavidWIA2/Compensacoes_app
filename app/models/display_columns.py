from typing import Dict, Tuple


DISPLAY_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("Ofício/ Processo", "oficio_processo"),
    ("Tipo", "eletronico"),
    ("Caixa", "caixa"),
    ("Av. Tec.", "av_tec"),
    ("Compensação", "compensacao"),
    ("Endereço", "endereco"),
    ("Microbacia", "microbacia"),
    ("Compensado", "compensado"),
    ("Endereço do Plantio", "endereco_plantio"),
)

DISPLAY_COLUMN_LABELS: Tuple[str, ...] = tuple(label for label, _attr in DISPLAY_COLUMNS)
DISPLAY_COLUMN_ATTRS: Tuple[str, ...] = tuple(attr for _label, attr in DISPLAY_COLUMNS)
DISPLAY_COLUMN_LABEL_BY_ATTR: Dict[str, str] = {
    attr: label for label, attr in DISPLAY_COLUMNS
}


def display_column_label(attr: str) -> str:
    return DISPLAY_COLUMN_LABEL_BY_ATTR.get(attr, attr)


def display_column_index(attr: str) -> int:
    try:
        return DISPLAY_COLUMN_ATTRS.index(attr)
    except ValueError as exc:
        raise KeyError(f"Unknown display column attribute: {attr}") from exc
