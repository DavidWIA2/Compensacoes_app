import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTableWidget

from app.application.use_cases.plantios_dialog_presenter import PlantioRowView, PlantiosDialogPresenter
from app.ui.components.plantios_dialog_support import (
    append_plantio_row,
    apply_plantio_row_view,
    build_plantios_row_action_state,
    read_plantio_rows_from_table,
    resolve_plantio_next_row_after_removal,
    resolve_plantio_selected_row,
    update_plantios_total_label,
)


def get_app():
    return QApplication.instance() or QApplication([])


def test_plantios_dialog_support_reads_writes_and_summarizes_rows():
    get_app()
    table = QTableWidget(0, 2)

    row = append_plantio_row(table, "Rua A", "3")
    append_plantio_row(table, "Rua B", "7")
    apply_plantio_row_view(table, row, PlantioRowView(endereco="Rua A, 10", qtd_mudas="4"))

    rows = read_plantio_rows_from_table(table)
    total_text = update_plantios_total_label(PlantiosDialogPresenter(), table, compensacao_total="11")

    assert rows == [
        PlantioRowView(endereco="Rua A, 10", qtd_mudas="4"),
        PlantioRowView(endereco="Rua B", qtd_mudas="7"),
    ]
    assert total_text == "Soma dos plantios: 11 mudas | Compensacao: 11"


def test_plantios_dialog_support_resolves_selected_and_next_rows():
    get_app()
    table = QTableWidget(0, 2)
    append_plantio_row(table, "Rua A", "3")
    append_plantio_row(table, "Rua B", "7")

    table.setCurrentCell(1, 0)
    state = build_plantios_row_action_state(table)

    assert state.has_rows is True
    assert resolve_plantio_selected_row(table) == 1
    assert resolve_plantio_next_row_after_removal(1, 1) == 0
