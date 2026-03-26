from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _safe_upper(value: object) -> str:
    return _clean_text(value).upper()


def parse_numeric_value(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)

    text = _clean_text(value).replace(" ", "")
    if not text:
        raise ValueError("empty")

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    return float(text)


def format_numeric_value(value: float) -> str:
    return f"{value:g}"


def clone_plantios(plantios: Iterable[PlantioItem]) -> List[PlantioItem]:
    return [
        PlantioItem(
            sequence=int(getattr(item, "sequence", index)),
            endereco=_clean_text(getattr(item, "endereco", "")),
            qtd_mudas=_clean_text(getattr(item, "qtd_mudas", "")),
            latitude=_clean_text(getattr(item, "latitude", "")),
            longitude=_clean_text(getattr(item, "longitude", "")),
        )
        for index, item in enumerate(plantios or [], start=1)
    ]


def normalize_plantios(plantios: Iterable[PlantioItem]) -> List[PlantioItem]:
    normalized: List[PlantioItem] = []
    for item in clone_plantios(plantios):
        if not any(
            [
                _clean_text(item.endereco),
                _clean_text(item.qtd_mudas),
                _clean_text(item.latitude),
                _clean_text(item.longitude),
            ]
        ):
            continue
        item.sequence = len(normalized) + 1
        normalized.append(item)
    return normalized


def build_plantios_from_rows(
    rows: Iterable[Tuple[object, object]],
    previous_plantios: Sequence[PlantioItem] | None = None,
) -> List[PlantioItem]:
    previous = normalize_plantios(previous_plantios or [])
    result: List[PlantioItem] = []

    for index, row in enumerate(rows, start=1):
        endereco = _clean_text(row[0] if len(row) > 0 else "")
        qtd_mudas = _clean_text(row[1] if len(row) > 1 else "")
        if not endereco and not qtd_mudas:
            continue

        existing = previous[index - 1] if index - 1 < len(previous) else None
        same_address = existing is not None and _clean_text(existing.endereco) == endereco
        result.append(
            PlantioItem(
                sequence=index,
                endereco=endereco,
                qtd_mudas=qtd_mudas,
                latitude=_clean_text(existing.latitude) if same_address else "",
                longitude=_clean_text(existing.longitude) if same_address else "",
            )
        )

    return result


def serialize_plantios_state(plantios: Iterable[PlantioItem]) -> Tuple[Tuple[int, str, str, str, str], ...]:
    normalized = normalize_plantios(plantios)
    return tuple(
        (
            int(item.sequence),
            _clean_text(item.endereco),
            _clean_text(item.qtd_mudas),
            _clean_text(item.latitude),
            _clean_text(item.longitude),
        )
        for item in normalized
    )


def deserialize_plantios_state(state: Iterable[Tuple[int, str, str, str, str]]) -> List[PlantioItem]:
    return normalize_plantios(
        PlantioItem(
            sequence=int(item[0]),
            endereco=item[1],
            qtd_mudas=item[2],
            latitude=item[3],
            longitude=item[4],
        )
        for item in (state or [])
    )


def plantios_total_qtd(plantios: Sequence[PlantioItem]) -> float:
    total = 0.0
    for item in normalize_plantios(plantios):
        try:
            total += parse_numeric_value(item.qtd_mudas)
        except ValueError:
            continue
    return total


def summarize_plantios(plantios: Sequence[PlantioItem]) -> str:
    normalized = normalize_plantios(plantios)
    if not normalized:
        return ""
    if len(normalized) == 1:
        return _clean_text(normalized[0].endereco)
    return f"{len(normalized)} áreas / {format_numeric_value(plantios_total_qtd(normalized))} mudas"


def plantio_choice_label(item: PlantioItem, index: int) -> str:
    qtd = _clean_text(item.qtd_mudas)
    if qtd:
        return f"Plantio {index}: {item.endereco} ({qtd} mudas)"
    return f"Plantio {index}: {item.endereco}"


def record_plantio_addresses(record: Compensacao) -> List[str]:
    addresses = []
    for item in normalize_plantios(getattr(record, "plantios", [])):
        if item.endereco:
            addresses.append(item.endereco)
    if not addresses and _clean_text(getattr(record, "endereco_plantio", "")):
        addresses.append(_clean_text(record.endereco_plantio))
    return addresses


def record_plantio_items(record: Compensacao) -> List[PlantioItem]:
    items = normalize_plantios(getattr(record, "plantios", []))
    if items:
        return items
    return legacy_plantios_from_record(record)


def legacy_plantios_from_record(record: Compensacao) -> List[PlantioItem]:
    endereco = _clean_text(getattr(record, "endereco_plantio", ""))
    if not endereco:
        return []

    compensacao = _clean_text(getattr(record, "compensacao", ""))
    return [
        PlantioItem(
            sequence=1,
            endereco=endereco,
            qtd_mudas=compensacao,
            latitude=_clean_text(getattr(record, "latitude_plantio", "")),
            longitude=_clean_text(getattr(record, "longitude_plantio", "")),
        )
    ]


def sync_legacy_plantio_fields(record: Compensacao) -> Compensacao:
    normalized = record_plantio_items(record)
    record.plantios = clone_plantios(normalized)
    record.endereco_plantio = summarize_plantios(normalized)
    if normalized:
        record.latitude_plantio = _clean_text(normalized[0].latitude)
        record.longitude_plantio = _clean_text(normalized[0].longitude)
    else:
        record.latitude_plantio = ""
        record.longitude_plantio = ""
    return record


def validate_record_plantios(record: Compensacao) -> str:
    normalized = record_plantio_items(record)
    is_compensado = _safe_upper(getattr(record, "compensado", "")) == "SIM"

    if is_compensado and not normalized:
        return "Preencha Endereco Plantio para salvar um registro compensado."

    for index, item in enumerate(normalized, start=1):
        if not _clean_text(item.endereco):
            return f"Preencha o endereco do Plantio {index}."
        if not _clean_text(item.qtd_mudas):
            return f"Preencha a quantidade de mudas do Plantio {index}."
        try:
            qtd = parse_numeric_value(item.qtd_mudas)
        except ValueError:
            return f"A quantidade de mudas do Plantio {index} deve ser numerica."
        if qtd <= 0:
            return f"A quantidade de mudas do Plantio {index} deve ser maior que zero."

    if not normalized:
        return ""

    compensacao_raw = _clean_text(getattr(record, "compensacao", ""))
    if not compensacao_raw:
        return ""

    try:
        compensacao_total = parse_numeric_value(compensacao_raw)
    except ValueError:
        return ""

    plantios_total = plantios_total_qtd(normalized)
    if abs(plantios_total - compensacao_total) > 1e-6:
        return (
            "A soma das mudas dos plantios deve ser igual ao valor informado em Compensacao."
        )

    return ""
