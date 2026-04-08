from typing import List, Dict
from PySide6.QtCore import Qt, QSortFilterProxyModel, QObject, Slot, Signal, QEvent
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QComboBox, QFrame, QVBoxLayout, QLabel, QLineEdit, QCheckBox,
    QHBoxLayout, QPushButton, QDialog, QDialogButtonBox, QSizePolicy, QSplitter, QSplitterHandle
)
from PySide6.QtWebEngineCore import QWebEnginePage

from app.services.records_service import remove_accents


def _selection_key(value: object) -> str:
    return remove_accents(str(value or "").strip()).upper()


class MapBridge(QObject):
    def __init__(self, on_clicked_callback, on_layer_changed_callback=None):
        super().__init__()
        self._on_clicked = on_clicked_callback
        self._on_layer_changed = on_layer_changed_callback

    @Slot(float, float)
    def onMapClicked(self, lat: float, lng: float):
        if self._on_clicked:
            self._on_clicked(lat, lng)

    @Slot(str)
    def onLayerChanged(self, layer_name: str):
        if self._on_layer_changed:
            self._on_layer_changed(layer_name)


class DebugPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        pass


class CheckableComboBox(QComboBox):
    selectionChanged = Signal()

    def __init__(self, all_label: str):
        super().__init__()
        self._all_label = all_label
        self._block = False
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText(all_label)
        
        # O segredo para combos de multiseleção estáveis no Qt: eventFilter no viewport
        self.view().viewport().installEventFilter(self)
        self.set_items([])

    def eventFilter(self, widget, event):
        if widget == self.view().viewport() and event.type() == QEvent.MouseButtonRelease:
            index = self.view().indexAt(event.pos())
            if index.isValid():
                self._toggle_item(index)
                return True # Bloqueia o fechamento automático e o processamento padrão
        return super().eventFilter(widget, event)

    def _toggle_item(self, index):
        if self._block: return
        self._block = True
        
        m = self.model()
        item = m.itemFromIndex(index)
        row_idx = index.row()
        
        # Alterna o estado manualmente
        current_state = item.data(Qt.CheckStateRole)
        new_state = Qt.Checked if current_state == Qt.Unchecked else Qt.Unchecked
        item.setData(new_state, Qt.CheckStateRole)
        
        if row_idx == 0:
            if new_state == Qt.Checked:
                # Marcou "Todas": desmarca todo o resto
                for i in range(1, m.rowCount()):
                    m.item(i).setData(Qt.Unchecked, Qt.CheckStateRole)
            else:
                # Tentou desmarcar "Todas": se nada mais estiver marcado, força a volta do "Todas"
                if not self.checked_items():
                    item.setData(Qt.Checked, Qt.CheckStateRole)
        else:
            if new_state == Qt.Checked:
                # Marcou um item específico: desmarca o "Todas" obrigatoriamente
                m.item(0).setData(Qt.Unchecked, Qt.CheckStateRole)
            else:
                # Desmarcou um item: se não sobrou absolutamente nada, reativa o "Todas"
                if not self.checked_items():
                    m.item(0).setData(Qt.Checked, Qt.CheckStateRole)
        
        self._refresh_ui()
        self._block = False
        self.selectionChanged.emit()

    def set_items(self, items: List[str]):
        self._block = True
        m = QStandardItemModel()
        all_item = QStandardItem(self._all_label)
        all_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        all_item.setData(Qt.Checked, Qt.CheckStateRole)
        m.appendRow(all_item)
        for it in items:
            if not it or not str(it).strip(): continue
            row = QStandardItem(str(it))
            row.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            row.setData(Qt.Unchecked, Qt.CheckStateRole)
            m.appendRow(row)
        self.setModel(m)
        self._refresh_ui()
        self._block = False

    def checked_items(self) -> List[str]:
        m = self.model()
        if not m: return []
        return [m.item(i).text() for i in range(1, m.rowCount()) if m.item(i).data(Qt.CheckStateRole) == Qt.Checked]

    def is_all_selected(self) -> bool:
        m = self.model()
        if not m or m.rowCount() == 0: return True
        return m.item(0).data(Qt.CheckStateRole) == Qt.Checked

    def select_all(self):
        m = self.model()
        if not m or m.rowCount() == 0: return
        self._block = True
        m.item(0).setData(Qt.Checked, Qt.CheckStateRole)
        for i in range(1, m.rowCount()):
            m.item(i).setData(Qt.Unchecked, Qt.CheckStateRole)
        self._refresh_ui()
        self._block = False
        self.selectionChanged.emit()

    def set_checked_items(
        self,
        items: List[str],
        *,
        all_selected: bool = False,
        emit_selection_changed: bool = True,
    ):
        m = self.model()
        if not m or m.rowCount() == 0: return
        self._block = True
        if all_selected:
            m.item(0).setData(Qt.Checked, Qt.CheckStateRole)
            for i in range(1, m.rowCount()):
                m.item(i).setData(Qt.Unchecked, Qt.CheckStateRole)
        else:
            selected = {_selection_key(item) for item in items if str(item).strip()}
            m.item(0).setData(Qt.Unchecked, Qt.CheckStateRole)
            for i in range(1, m.rowCount()):
                st = Qt.Checked if _selection_key(m.item(i).text()) in selected else Qt.Unchecked
                m.item(i).setData(st, Qt.CheckStateRole)
        self._refresh_ui()
        self._block = False
        if emit_selection_changed:
            self.selectionChanged.emit()

    def _refresh_ui(self):
        checked = self.checked_items()
        txt = self._all_label if self.is_all_selected() or not checked else ", ".join(checked)
        self.lineEdit().setText(txt)
        self.setEditText(txt)


class NumericSortProxy(QSortFilterProxyModel):
    def lessThan(self, left, right):
        if left.column() == 4:
            l, r = self.sourceModel().data(left, Qt.UserRole), self.sourceModel().data(right, Qt.UserRole)
            try: return float(l) < float(r)
            except: return str(l) < str(r)
        return super().lessThan(left, right)


class LockedSplitterHandle(QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event):
        event.ignore()

    def mouseMoveEvent(self, event):
        event.ignore()

    def mouseReleaseEvent(self, event):
        event.ignore()

    def mouseDoubleClickEvent(self, event):
        event.ignore()


class LockedSplitter(QSplitter):
    def createHandle(self):
        return LockedSplitterHandle(self.orientation(), self)


class KPICard(QFrame):
    def __init__(self, title: str, value: str, color: str, *, compact: bool = False):
        super().__init__()
        self.setObjectName("KpiCard")
        self.color = color
        self.compact = bool(compact)
        self.sf = 1.0
        # Tenta herdar o scale factor da MainWindow global
        from PySide6.QtWidgets import QApplication
        mw = next((w for w in QApplication.topLevelWidgets() if hasattr(w, "scale_factor")), None)
        if mw:
            self.sf = mw.scale_factor
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        if self.compact:
            layout.setContentsMargins(int(10*self.sf), int(6*self.sf), int(10*self.sf), int(6*self.sf))
            layout.setSpacing(int(1 * self.sf))
        else:
            layout.setContentsMargins(int(10*self.sf), int(10*self.sf), int(10*self.sf), int(10*self.sf))
        self.lbl_title = QLabel(title)
        self.lbl_value = QLabel(value)
        self.lbl_title.setObjectName("Titulo")
        self.lbl_value.setObjectName("Valor")
        self.lbl_title.setWordWrap(True)
        self.lbl_value.setWordWrap(False)
        self.lbl_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)
        if not self.compact:
            layout.addStretch(1)

    def update_style(self, theme: dict):
        font_val = int((14 if self.compact else 20) * self.sf)
        font_tit = int((8 if self.compact else 10) * self.sf)
        radius = int((9 if self.compact else 10) * self.sf)
        border_left = int((4 if self.compact else 5) * self.sf)
        self.setStyleSheet(f"""
            KPICard {{
                background-color: {theme['kpi_bg']};
                border-radius: {radius}px;
                border: 1px solid {theme['kpi_border']};
                border-left: {border_left}px solid {self.color};
            }}
            QLabel#Valor {{
                font-size: {font_val}px;
                font-weight: 800;
                color: {theme['text']};
                border: none;
            }}
            QLabel#Titulo {{
                font-size: {font_tit}px;
                font-weight: 700;
                color: {theme['muted']};
                border: none;
            }}
        """)

    def update_value(self, new_value: str):
        self.lbl_value.setText(new_value)


class ColumnsDialog(QDialog):
    def __init__(self, parent, cols: List[str], visible_map: Dict[int, bool]):
        super().__init__(parent)
        self.setWindowTitle("Selecionar Colunas")
        self.setModal(True)
        layout = QVBoxLayout(self)
        self.in_busca = QLineEdit()
        self.in_busca.setPlaceholderText("Pesquisar coluna...")
        layout.addWidget(self.in_busca)
        self.checks = []
        for i, name in enumerate(cols):
            cb = QCheckBox(name)
            cb.setChecked(visible_map.get(i, True))
            self.checks.append(cb)
            layout.addWidget(cb)
        layout.addStretch(1)
        btn_layout = QHBoxLayout()
        self.btn_all = QPushButton("Marcar Todos")
        self.btn_none = QPushButton("Desmarcar Todos")
        btn_layout.addWidget(self.btn_all)
        btn_layout.addWidget(self.btn_none)
        layout.addLayout(btn_layout)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(self.button_box)
        self.btn_all.clicked.connect(lambda: [c.setChecked(True) for c in self.checks])
        self.btn_none.clicked.connect(lambda: [c.setChecked(False) for c in self.checks])
        self.in_busca.textChanged.connect(self._filter_checks)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def _filter_checks(self, text: str):
        query = (text or "").strip().lower()
        for check in self.checks:
            is_visible = not query or query in check.text().lower()
            check.setVisible(is_visible)

    def visible_map(self) -> Dict[int, bool]:
        return {index: check.isChecked() for index, check in enumerate(self.checks)}
