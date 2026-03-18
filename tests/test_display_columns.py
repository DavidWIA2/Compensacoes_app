from PySide6.QtCore import Qt

from app.models.display_columns import (
    DISPLAY_COLUMNS,
    DISPLAY_COLUMN_ATTRS,
    DISPLAY_COLUMN_LABELS,
    display_column_index,
)
from app.services.excel_service import EXPECTED_HEADERS
from app.services.report_service import ALL_COLUMNS
from app.ui.components.model import CompensacoesTableModel


def test_display_columns_stay_in_sync_across_ui_export_and_excel():
    assert ALL_COLUMNS == DISPLAY_COLUMNS
    assert tuple(EXPECTED_HEADERS[attr] for attr in DISPLAY_COLUMN_ATTRS) == DISPLAY_COLUMN_LABELS

    model = CompensacoesTableModel([])
    headers = tuple(
        model.headerData(index, Qt.Horizontal, Qt.DisplayRole)
        for index in range(model.columnCount())
    )

    assert headers == DISPLAY_COLUMN_LABELS
    assert display_column_index("endereco_plantio") == len(DISPLAY_COLUMN_ATTRS) - 1
