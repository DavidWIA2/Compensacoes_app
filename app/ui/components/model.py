from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QColor

from app.models.compensacao import Compensacao
from app.models.display_columns import DISPLAY_COLUMN_ATTRS, DISPLAY_COLUMN_LABELS
from app.services.coordinates import format_coordinate_pair
from app.services.records_service import display_tipo_value


class CompensacoesTableModel(QAbstractTableModel):
    def __init__(self, records: list[Compensacao] | None = None):
        super().__init__()
        self.records = records or []
        self._is_dark = False

    def set_dark_mode(self, is_dark: bool):
        self._is_dark = is_dark
        self.layoutChanged.emit()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.records)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(DISPLAY_COLUMN_LABELS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> Any:
        if role != int(Qt.ItemDataRole.DisplayRole):
            return None

        if orientation == Qt.Orientation.Horizontal:
            return DISPLAY_COLUMN_LABELS[section]

        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)

        return None

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self.records)):
            return None

        record = self.records[index.row()]
        attr = DISPLAY_COLUMN_ATTRS[index.column()]

        if role == int(Qt.ItemDataRole.DisplayRole):
            value = getattr(record, attr)
            if attr == "compensacao":
                return str(value) if value is not None else ""
            if attr == "eletronico":
                return display_tipo_value(value)
            if attr == "compensado" and str(value).strip().upper() == "SIM":
                return "SIM"
            return value

        if role == int(Qt.ItemDataRole.TextAlignmentRole):
            if attr == "compensacao":
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if attr == "compensado":
                return int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if role == int(Qt.ItemDataRole.BackgroundRole) and attr == "compensado":
            if str(record.compensado).strip().upper() == "SIM":
                return QColor("#1f6f3a") if self._is_dark else QColor("#c6efce")
            return QColor("#3a3f4c") if self._is_dark else QColor("#e9edf3")

        if role == int(Qt.ItemDataRole.ForegroundRole) and attr == "compensado":
            if str(record.compensado).strip().upper() == "SIM":
                return QColor("#eafff1") if self._is_dark else QColor("#1d4b2a")
            return QColor("#e9e9ea") if self._is_dark else QColor("#1f2328")

        if role == int(Qt.ItemDataRole.ToolTipRole):
            coords = format_coordinate_pair(record.latitude, record.longitude)
            if coords:
                return f"Lat/Lon: {coords}"

        if role == int(Qt.ItemDataRole.UserRole):
            if attr == "compensacao":
                try:
                    value = getattr(record, "compensacao", "")
                    return float(str(value).replace(",", ".")) if str(value).strip() else 0.0
                except Exception:
                    return 0.0
            if attr == "oficio_processo":
                return record.excel_row
            return self.data(index, int(Qt.ItemDataRole.DisplayRole))

        return None

    def update_data(self, new_records: list[Compensacao]) -> None:
        self.beginResetModel()
        self.records = new_records
        self.endResetModel()
