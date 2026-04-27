from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHeaderView, QTableView

from app.application.use_cases.table_fullscreen_filters import TableFullscreenFilterState, TableFullscreenFiltersUseCases
from app.application.use_cases.table_fullscreen_layout import TableHeaderLayoutSnapshot
from app.ui.components.widgets import CheckableComboBox


def resolve_fullscreen_primary_table(content_widget: Any) -> QTableView | None:
    tables = content_widget.findChildren(QTableView)
    if not tables:
        return None
    return max(tables, key=lambda table: table.model().columnCount() if table.model() else 0)


def combo_items(combo: QComboBox) -> List[str]:
    return [combo.itemText(index) for index in range(combo.count())]


def checkable_items(combo: CheckableComboBox) -> List[str]:
    model = combo.model()
    item_getter = getattr(model, "item", None)
    if not callable(item_getter):
        return []
    return [
        item.text()
        for index in range(1, model.rowCount())
        if (item := item_getter(index)) is not None
    ]


def build_fullscreen_filter_state_from_main(window: Any, filter_use_cases: TableFullscreenFiltersUseCases) -> TableFullscreenFilterState:
    return filter_use_cases.build_state(
        search_text=window.search.text(),
        status_options=combo_items(window.data_tab.filter_status),
        status_current_text=window.data_tab.filter_status.currentText(),
        year_options=combo_items(window.data_tab.filter_year),
        year_current_text=window.data_tab.filter_year.currentText(),
        micro_items=checkable_items(window.data_tab.filter_micro),
        micro_checked_items=window.data_tab.filter_micro.checked_items(),
        micro_all_selected=window.data_tab.filter_micro.is_all_selected(),
        eletronico_items=checkable_items(window.data_tab.filter_eletronico),
        eletronico_checked_items=window.data_tab.filter_eletronico.checked_items(),
        eletronico_all_selected=window.data_tab.filter_eletronico.is_all_selected(),
        caixa_items=checkable_items(window.data_tab.filter_caixa),
        caixa_checked_items=window.data_tab.filter_caixa.checked_items(),
        caixa_all_selected=window.data_tab.filter_caixa.is_all_selected(),
    )


def build_fullscreen_filter_state_from_dialog(dialog: Any, filter_use_cases: TableFullscreenFiltersUseCases) -> TableFullscreenFilterState:
    return filter_use_cases.build_state(
        search_text=dialog.search_fs.text(),
        status_options=combo_items(dialog.filter_status_fs),
        status_current_text=dialog.filter_status_fs.currentText(),
        year_options=combo_items(dialog.filter_year_fs),
        year_current_text=dialog.filter_year_fs.currentText(),
        micro_items=checkable_items(dialog.filter_micro_fs),
        micro_checked_items=dialog.filter_micro_fs.checked_items(),
        micro_all_selected=dialog.filter_micro_fs.is_all_selected(),
        eletronico_items=checkable_items(dialog.filter_eletronico_fs),
        eletronico_checked_items=dialog.filter_eletronico_fs.checked_items(),
        eletronico_all_selected=dialog.filter_eletronico_fs.is_all_selected(),
        caixa_items=checkable_items(dialog.filter_caixa_fs),
        caixa_checked_items=dialog.filter_caixa_fs.checked_items(),
        caixa_all_selected=dialog.filter_caixa_fs.is_all_selected(),
    )


def apply_fullscreen_filter_state_to_dialog(dialog: Any, state: TableFullscreenFilterState) -> None:
    dialog.search_fs.setText(state.search_text)
    dialog.filter_status_fs.clear()
    dialog.filter_status_fs.addItems(list(state.status.options))
    dialog.filter_status_fs.setCurrentText(state.status.current_text)
    dialog.filter_year_fs.clear()
    dialog.filter_year_fs.addItems(list(state.year.options))
    dialog.filter_year_fs.setCurrentText(state.year.current_text)
    dialog.filter_micro_fs.set_items(list(state.micro.items))
    dialog.filter_micro_fs.set_checked_items(
        list(state.micro.checked_items),
        all_selected=state.micro.all_selected,
    )
    dialog.filter_eletronico_fs.set_items(list(state.eletronico.items))
    dialog.filter_eletronico_fs.set_checked_items(
        list(state.eletronico.checked_items),
        all_selected=state.eletronico.all_selected,
    )
    dialog.filter_caixa_fs.set_items(list(state.caixa.items))
    dialog.filter_caixa_fs.set_checked_items(
        list(state.caixa.checked_items),
        all_selected=state.caixa.all_selected,
    )


def apply_fullscreen_filter_state_to_main(window: Any, state: TableFullscreenFilterState) -> None:
    window.search.setText(state.search_text)
    window.data_tab.filter_status.setCurrentText(state.status.current_text)
    window.data_tab.filter_year.setCurrentText(state.year.current_text)
    window.data_tab.filter_micro.set_checked_items(
        list(state.micro.checked_items),
        all_selected=state.micro.all_selected,
    )
    window.data_tab.filter_eletronico.set_checked_items(
        list(state.eletronico.checked_items),
        all_selected=state.eletronico.all_selected,
    )
    window.data_tab.filter_caixa.set_checked_items(
        list(state.caixa.checked_items),
        all_selected=state.caixa.all_selected,
    )


def capture_fullscreen_table_layout(table: QTableView, snapshot_builder: Any) -> TableHeaderLayoutSnapshot:
    header = table.horizontalHeader()
    return snapshot_builder(
        stretch_last_section=header.stretchLastSection(),
        resize_modes=[header.sectionResizeMode(i) for i in range(header.count())],
        section_sizes=[header.sectionSize(i) for i in range(header.count())],
    )


def resolve_fullscreen_visible_columns(table: QTableView, visible_columns_builder: Any) -> list[int]:
    hidden_columns = [
        table.isColumnHidden(index)
        for index in range(table.horizontalHeader().count())
    ]
    return visible_columns_builder(hidden_columns)


def build_fullscreen_header_widths(table: QTableView, visible_columns: list[int]) -> Dict[int, int]:
    header = table.horizontalHeader()
    model = table.model()
    return {
        index: header.fontMetrics().horizontalAdvance(
            str(
                model.headerData(
                    index,
                    Qt.Orientation.Horizontal,
                    Qt.ItemDataRole.DisplayRole,
                )
                or ""
            )
        )
        for index in visible_columns
    }


def apply_fullscreen_preferred_widths(table: QTableView, preferred_widths: Optional[Dict[int, int]]) -> None:
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    if not preferred_widths:
        for index in range(header.count()):
            header.setSectionResizeMode(index, QHeaderView.Stretch)
        return
    for index in range(header.count()):
        header.setSectionResizeMode(index, QHeaderView.Interactive)
    for index, width in preferred_widths.items():
        header.resizeSection(index, width)


def restore_fullscreen_table_layout(table: QTableView, snapshot: TableHeaderLayoutSnapshot) -> None:
    header = table.horizontalHeader()
    interactive_mode = int(getattr(QHeaderView.Interactive, "value", QHeaderView.Interactive))
    header.setStretchLastSection(snapshot.stretch_last_section)
    for index, mode in enumerate(snapshot.resize_modes):
        header.setSectionResizeMode(index, QHeaderView.ResizeMode(mode))
    for index, size in enumerate(snapshot.section_sizes):
        if snapshot.resize_modes[index] == interactive_mode:
            header.resizeSection(index, size)


@contextmanager
def blocked_qt_signals(*objects: Any):
    for obj in objects:
        obj.blockSignals(True)
    try:
        yield
    finally:
        for obj in objects:
            obj.blockSignals(False)
