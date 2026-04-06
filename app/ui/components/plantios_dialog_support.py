from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem

from app.application.use_cases.plantios_dialog_presenter import PlantioRowView, PlantiosDialogPresenter


@dataclass(frozen=True)
class PlantiosRowActionState:
    has_rows: bool


def append_plantio_row(table: QTableWidget, endereco: str = "", qtd_mudas: str = "") -> int:
    row = table.rowCount()
    table.insertRow(row)
    table.setItem(row, 0, QTableWidgetItem(str(endereco or "")))
    table.setItem(row, 1, QTableWidgetItem(str(qtd_mudas or "")))
    return row


def build_plantios_row_action_state(table: QTableWidget) -> PlantiosRowActionState:
    return PlantiosRowActionState(has_rows=table.rowCount() > 0)


def resolve_plantio_selected_row(table: QTableWidget) -> int:
    row = table.currentRow()
    if row >= 0:
        return row
    return table.rowCount() - 1


def resolve_plantio_next_row_after_removal(removed_row: int, remaining_rows: int) -> int:
    if remaining_rows <= 0:
        return -1
    return min(max(removed_row, 0), remaining_rows - 1)


def read_plantio_rows_from_table(table: QTableWidget) -> list[PlantioRowView]:
    rows: list[PlantioRowView] = []
    for row in range(table.rowCount()):
        endereco_item = table.item(row, 0)
        qtd_item = table.item(row, 1)
        rows.append(
            PlantioRowView(
                endereco=endereco_item.text().strip() if endereco_item else "",
                qtd_mudas=qtd_item.text().strip() if qtd_item else "",
            )
        )
    return rows


def update_plantios_total_label(
    presenter: PlantiosDialogPresenter,
    table: QTableWidget,
    *,
    compensacao_total: str,
) -> str:
    return presenter.total_text(read_plantio_rows_from_table(table), compensacao_total)


def apply_plantio_row_view(table: QTableWidget, row: int, row_view: PlantioRowView) -> None:
    endereco_item = table.item(row, 0)
    qtd_item = table.item(row, 1)
    if endereco_item is None:
        endereco_item = QTableWidgetItem("")
        table.setItem(row, 0, endereco_item)
    if qtd_item is None:
        qtd_item = QTableWidgetItem("")
        table.setItem(row, 1, qtd_item)
    endereco_item.setText(row_view.endereco)
    qtd_item.setText(row_view.qtd_mudas)
