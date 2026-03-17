from typing import List, Optional, Tuple
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor
from app.models.compensacao import Compensacao
from app.ui.components.themes import COLS

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
        return len(COLS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
            
        if orientation == Qt.Horizontal:
            return COLS[section]
            
        if orientation == Qt.Vertical:
            # Retorna o número da linha (1, 2, 3...)
            return str(section + 1)
            
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.records)):
            return None

        record = self.records[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            mapping = {
                0: record.oficio_processo,
                1: record.eletronico,
                2: record.caixa,
                3: record.av_tec,
                4: str(record.compensacao) if record.compensacao is not None else "",
                5: record.endereco,
                6: record.microbacia,
                7: "SIM" if str(record.compensado).strip().upper() == "SIM" else record.compensado,
                8: record.endereco_plantio
            }
            return mapping.get(col, "")

        if role == Qt.TextAlignmentRole:
            if col == 4: return Qt.AlignRight | Qt.AlignVCenter
            if col == 7: return Qt.AlignCenter | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        if role == Qt.BackgroundRole and col == 7:
            if str(record.compensado).strip().upper() == "SIM":
                return QColor("#1f6f3a") if self._is_dark else QColor("#c6efce")
            return QColor("#3a3f4c") if self._is_dark else QColor("#e9edf3")

        if role == Qt.ForegroundRole and col == 7:
            if str(record.compensado).strip().upper() == "SIM":
                return QColor("#eafff1") if self._is_dark else QColor("#1d4b2a")
            return QColor("#e9e9ea") if self._is_dark else QColor("#1f2328")

        if role == Qt.ToolTipRole:
            lat = getattr(record, "latitude", "")
            lon = getattr(record, "longitude", "")
            if str(lat).strip() and str(lon).strip():
                return f"Lat/Lon: {lat}, {lon}"

        if role == Qt.UserRole: # Usado para ordenação numérica na coluna de compensação
            if col == 4:
                try: return float(record.compensacao)
                except: return 0.0
            if col == 0: return record.excel_row
            return self.data(index, Qt.DisplayRole)

        return None

    def update_data(self, new_records: List[Compensacao]):
        self.beginResetModel()
        self.records = new_records
        self.endResetModel()
