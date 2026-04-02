from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence, SupportsInt, cast


@dataclass(frozen=True)
class TableHeaderLayoutSnapshot:
    stretch_last_section: bool
    resize_modes: tuple[int, ...]
    section_sizes: tuple[int, ...]


@dataclass(frozen=True)
class TableFullscreenWidthPlan:
    widths: dict[int, int]
    use_stretch_fallback: bool = False


class TableFullscreenLayoutUseCases:
    @staticmethod
    def _normalize_mode(mode: object) -> int:
        raw_mode = getattr(mode, "value", mode)
        if isinstance(raw_mode, int):
            return raw_mode
        return int(cast(SupportsInt, raw_mode))

    @staticmethod
    def capture_header_layout(
        *,
        stretch_last_section: bool,
        resize_modes: Sequence[object],
        section_sizes: Sequence[int],
    ) -> TableHeaderLayoutSnapshot:
        return TableHeaderLayoutSnapshot(
            stretch_last_section=bool(stretch_last_section),
            resize_modes=tuple(TableFullscreenLayoutUseCases._normalize_mode(mode) for mode in resize_modes),
            section_sizes=tuple(int(size) for size in section_sizes),
        )

    @staticmethod
    def visible_columns(hidden_columns: Sequence[bool]) -> list[int]:
        return [index for index, is_hidden in enumerate(hidden_columns) if not is_hidden]

    def build_width_plan(
        self,
        *,
        visible_columns: Sequence[int],
        header_widths: Mapping[int, int],
        available_width: int,
        scale_factor: float = 1.0,
        base_widths: Mapping[int, int] | None = None,
        extra_weights: Mapping[int, float] | None = None,
        default_base_width: int = 140,
        default_weight: float = 0.5,
        minimum_padding: int = 28,
    ) -> TableFullscreenWidthPlan:
        if not visible_columns or available_width <= 0:
            return TableFullscreenWidthPlan(widths={}, use_stretch_fallback=True)

        base_widths = dict(base_widths or {})
        extra_weights = dict(extra_weights or {})
        padding = max(int(minimum_padding * float(scale_factor or 1.0)), minimum_padding)

        minimum_widths: dict[int, int] = {}
        weights: dict[int, float] = {}

        for index in visible_columns:
            header_width = int(header_widths.get(index, 0)) + padding
            base_width = int(base_widths.get(index, default_base_width) * float(scale_factor or 1.0))
            minimum_widths[index] = max(base_width, header_width)
            weights[index] = float(extra_weights.get(index, default_weight))

        total_minimum_width = sum(minimum_widths.values())
        if total_minimum_width >= available_width:
            return TableFullscreenWidthPlan(widths=minimum_widths, use_stretch_fallback=False)

        extra_width = available_width - total_minimum_width
        total_weight = sum(weights.values()) or 1.0
        widths = {
            index: int(minimum_widths[index] + (extra_width * (weights[index] / total_weight)))
            for index in visible_columns
        }
        return TableFullscreenWidthPlan(widths=widths, use_stretch_fallback=False)
