from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from app.services.records_service import display_tipo_value


@dataclass(frozen=True)
class ComboFilterState:
    options: tuple[str, ...]
    current_text: str


@dataclass(frozen=True)
class CheckableFilterState:
    items: tuple[str, ...]
    checked_items: tuple[str, ...]
    all_selected: bool


@dataclass(frozen=True)
class TableFullscreenFilterState:
    search_text: str
    status: ComboFilterState
    year: ComboFilterState
    micro: CheckableFilterState
    eletronico: CheckableFilterState


class TableFullscreenFiltersUseCases:
    @staticmethod
    def build_combo_state(options: Sequence[str], current_text: str) -> ComboFilterState:
        normalized_options = tuple(str(option or "") for option in options)
        return ComboFilterState(
            options=normalized_options,
            current_text=str(current_text or ""),
        )

    @staticmethod
    def build_checkable_state(
        items: Sequence[str],
        checked_items: Sequence[str],
        *,
        all_selected: bool,
        item_normalizer: Callable[[str], str] | None = None,
    ) -> CheckableFilterState:
        def normalize(value: str) -> str:
            text = str(value or "")
            return item_normalizer(text) if item_normalizer is not None else text

        normalized_items_list: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized_item = normalize(str(item or "")).strip()
            if not normalized_item:
                continue
            lookup_key = normalized_item.upper()
            if lookup_key in seen:
                continue
            seen.add(lookup_key)
            normalized_items_list.append(normalized_item)

        normalized_items = tuple(normalized_items_list)
        selected = {
            normalize(str(item or "")).strip().upper()
            for item in checked_items
            if str(item or "").strip()
        }
        normalized_checked = tuple(
            item for item in normalized_items if item.strip().upper() in selected
        )
        return CheckableFilterState(
            items=normalized_items,
            checked_items=normalized_checked,
            all_selected=bool(all_selected),
        )

    def build_state(
        self,
        *,
        search_text: str,
        status_options: Sequence[str],
        status_current_text: str,
        year_options: Sequence[str],
        year_current_text: str,
        micro_items: Sequence[str],
        micro_checked_items: Sequence[str],
        micro_all_selected: bool,
        eletronico_items: Sequence[str],
        eletronico_checked_items: Sequence[str],
        eletronico_all_selected: bool,
    ) -> TableFullscreenFilterState:
        return TableFullscreenFilterState(
            search_text=str(search_text or ""),
            status=self.build_combo_state(status_options, status_current_text),
            year=self.build_combo_state(year_options, year_current_text),
            micro=self.build_checkable_state(
                micro_items,
                micro_checked_items,
                all_selected=micro_all_selected,
            ),
            eletronico=self.build_checkable_state(
                eletronico_items,
                eletronico_checked_items,
                all_selected=eletronico_all_selected,
                item_normalizer=display_tipo_value,
            ),
        )

    @staticmethod
    def build_cleared_state(state: TableFullscreenFilterState) -> TableFullscreenFilterState:
        return TableFullscreenFilterState(
            search_text="",
            status=ComboFilterState(
                options=state.status.options,
                current_text=state.status.options[0] if state.status.options else "",
            ),
            year=ComboFilterState(
                options=state.year.options,
                current_text=state.year.options[0] if state.year.options else "",
            ),
            micro=CheckableFilterState(
                items=state.micro.items,
                checked_items=(),
                all_selected=True,
            ),
            eletronico=CheckableFilterState(
                items=state.eletronico.items,
                checked_items=(),
                all_selected=True,
            ),
        )
