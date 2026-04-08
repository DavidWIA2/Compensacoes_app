from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

from app.models.compensacao import Compensacao


@dataclass(frozen=True)
class ColumnWidthBounds:
    min_width: int
    max_width: int


def resolve_column_width_bounds(
    attr: str,
    *,
    scale_factor: float,
    rules: Mapping[str, Mapping[str, int]],
    default_min: int = 96,
    default_max: int = 280,
) -> ColumnWidthBounds:
    rule = rules.get(attr, {"min": default_min, "max": default_max})
    scale = max(float(scale_factor), 1.0)
    min_width = max(int(int(rule.get("min", default_min)) * scale), 72)
    max_width = max(int(int(rule.get("max", default_max)) * scale), min_width)
    return ColumnWidthBounds(min_width=min_width, max_width=max_width)


def build_column_texts_for_records(
    attr: str,
    records: Sequence[Compensacao],
    *,
    static_texts: Mapping[str, Sequence[str]],
    display_tipo_value: Callable[[object], str],
) -> list[str]:
    texts = list(static_texts.get(attr, ()))
    for record in records:
        value = getattr(record, attr, "")
        if attr == "eletronico":
            texts.append(display_tipo_value(value))
        elif attr == "compensado":
            texts.append("SIM" if str(value).strip().upper() == "SIM" else "")
        elif attr == "compensacao":
            texts.append("" if value is None else str(value))
        else:
            texts.append(str(value or ""))
    return texts


def compute_target_column_width(
    measured_widths: Iterable[int],
    *,
    padding: int,
    min_width: int | None = None,
    max_width: int | None = None,
) -> int:
    target_width = max((int(width) for width in measured_widths), default=0) + int(padding)
    if min_width is not None:
        target_width = max(target_width, int(min_width))
    if max_width is not None:
        target_width = min(target_width, int(max_width))
    return target_width


def compute_preferred_left_panel_width(
    *,
    visible_columns_width: int,
    table_chrome_width: int,
    totals_min_width: int,
    export_min_width: int,
    panel_gap: int,
) -> int:
    return max(
        int(visible_columns_width) + int(table_chrome_width) + int(panel_gap),
        int(totals_min_width) + int(panel_gap),
        int(export_min_width) + int(panel_gap),
    )


def compute_crud_buttons_minimum_width(button_widths: Sequence[int], *, spacing: int) -> int:
    if not button_widths:
        return 0
    return sum(int(width) for width in button_widths) + (max(len(button_widths) - 1, 0) * int(spacing))


def compute_preferred_right_panel_width(
    *,
    scale_factor: float,
    map_group_width: int | None = None,
    crud_buttons_width: int | None = None,
) -> int:
    responsive_scale = max(float(scale_factor), 0.82)
    widths = [max(int(620 * responsive_scale), 500)]
    if map_group_width is not None:
        widths.append(int(map_group_width))
    if crud_buttons_width is not None:
        widths.append(int(crud_buttons_width))
    return max(widths)


def resolve_splitter_anchor_character_index(
    button_text: str,
    *,
    anchor_word: str = "Tela",
    char_offset: int = 2,
) -> int | None:
    text = str(button_text or "")
    anchor_index = text.find(anchor_word)
    if anchor_index < 0:
        return None
    target_index = anchor_index + int(char_offset)
    if target_index >= len(text):
        return None
    return target_index


def compute_splitter_anchor_left_width(
    *,
    splitter_x: int,
    button_x: int,
    text_origin_x: int,
    prefix_width: int,
    target_char_width: int,
    handle_width: int,
    nudge: int,
) -> int:
    anchor_x = (
        int(button_x)
        + int(text_origin_x)
        + int(prefix_width)
        + max(int(target_char_width) // 2, 1)
        + int(nudge)
    )
    handle_center = max(int(handle_width) // 2, 0)
    return max(anchor_x - int(splitter_x) - handle_center, 0)


def compute_splitter_sizes(
    *,
    total_width: int,
    right_min_width: int,
    preferred_left_width: int,
    anchor_left_width: int | None = None,
) -> tuple[int, int] | None:
    total_width = int(total_width)
    if total_width <= 0:
        return None
    right_min_width = max(int(right_min_width), 0)
    preferred_left_width = max(int(preferred_left_width), 0)
    target_left_width = min(preferred_left_width, max(total_width - right_min_width, 0))
    if anchor_left_width is not None:
        target_left_width = min(target_left_width, max(int(anchor_left_width), 0))
    if target_left_width <= 0:
        return None
    return target_left_width, max(total_width - target_left_width, 0)


def build_totals_rows(metrics: Mapping[str, object]) -> list[tuple[str, str]]:
    return [
        ("Total Mudas", f"{float(metrics.get('total_geral', 0) or 0):g}"),
        ("Pendente", f"{float(metrics.get('total_pendente', 0) or 0):g}"),
        ("Compensado", f"{float(metrics.get('total_compensado', 0) or 0):g}"),
    ]


def build_micro_rows(metrics: Mapping[str, object]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for micro, value in metrics.get("pend_micro_sorted", ()) or ():
        rows.append((str(micro), f"{float(value or 0):g}"))
    return rows
