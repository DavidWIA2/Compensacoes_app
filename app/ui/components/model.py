from typing import List

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from app.models.compensacao import Compensacao
from app.models.display_columns import DISPLAY_COLUMN_ATTRS, DISPLAY_COLUMN_LABELS
from app.services.coordinates import format_coordinate_pair


class CompensacoesTableModel(QAbstractTableModel):
    def __init__(self, records: List[Compensacao] = None):
        super().__init__()
        self.records = records or []
        self._is_dark = False

    def set_dark_mode(self, is_dark: bool):
        self._is_dark = is_dark
        self.layoutChanged.emit()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.records)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(DISPLAY_COLUMN_LABELS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None

        if orientation == Qt.Horizontal:
            return DISPLAY_COLUMN_LABELS[section]

        if orientation == Qt.Vertical:
            return str(section + 1)

        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.records)):
            return None

        record = self.records[index.row()]
        attr = DISPLAY_COLUMN_ATTRS[index.column()]

        if role == Qt.DisplayRole:
            value = getattr(record, attr)
            if attr == "compensacao":
                return str(value) if value is not None else ""
            if attr == "compensado" and str(value).strip().upper() == "SIM":
                return "SIM"
            return value

        if role == Qt.TextAlignmentRole:
            if attr == "compensacao":
                return Qt.AlignRight | Qt.AlignVCenter
            if attr == "compensado":
                return Qt.AlignCenter | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        if role == Qt.BackgroundRole and attr == "compensado":
            if str(record.compensado).strip().upper() == "SIM":
                return QColor("#1f6f3a") if self._is_dark else QColor("#c6efce")
            return QColor("#3a3f4c") if self._is_dark else QColor("#e9edf3")

        if role == Qt.ForegroundRole and attr == "compensado":
            if str(record.compensado).strip().upper() == "SIM":
                return QColor("#eafff1") if self._is_dark else QColor("#1d4b2a")
            return QColor("#e9e9ea") if self._is_dark else QColor("#1f2328")

        if role == Qt.ToolTipRole:
            coords = format_coordinate_pair(record.latitude, record.longitude)
            if coords:
                return f"Lat/Lon: {coords}"

        if role == Qt.UserRole:
            if attr == "compensacao":
                try:
                    return float(record.compensacao)
                except Exception:
                    return 0.0
            if attr == "oficio_processo":
                return record.excel_row
            return self.data(index, Qt.DisplayRole)

        return None

    def update_data(self, new_records: List[Compensacao]):
        self.beginResetModel()
        self.records = new_records
        self.endResetModel()
