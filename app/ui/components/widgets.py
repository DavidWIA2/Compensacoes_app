from typing import List, Dict
from PySide6.QtCore import Qt, QSortFilterProxyModel, QObject, Slot
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QComboBox, QFrame, QVBoxLayout, QLabel, QLineEdit, QCheckBox,
    QHBoxLayout, QPushButton, QDialog, QDialogButtonBox
)
from PySide6.QtWebEngineCore import QWebEnginePage

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
    def __init__(self, all_label: str):
        super().__init__()
        self._all_label = all_label
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText(all_label)
        self.view().pressed.connect(self._on_pressed)
        self.set_items([])

    def set_items(self, items: List[str]):
        m = QStandardItemModel()
        all_item = QStandardItem(self._all_label)
        all_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        all_item.setData(Qt.Checked, Qt.CheckStateRole)
        m.appendRow(all_item)
        for it in items:
            if not it or not str(it).strip(): continue
            row = QStandardItem(it)
            row.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            row.setData(Qt.Unchecked, Qt.CheckStateRole)
            m.appendRow(row)
        self.setModel(m)
        self._refresh_text()

    def checked_items(self) -> List[str]:
        m = self.model()
        return [m.item(i).text() for i in range(1, m.rowCount()) if m.item(i).data(Qt.CheckStateRole) == Qt.Checked]

    def is_all_selected(self) -> bool:
        m = self.model()
        if m.rowCount() == 0: return True
        return m.item(0).data(Qt.CheckStateRole) == Qt.Checked

    def select_all(self):
        m = self.model()
        if m.rowCount() == 0: return
        m.item(0).setData(Qt.Checked, Qt.CheckStateRole)
        for i in range(1, m.rowCount()): m.item(i).setData(Qt.Unchecked, Qt.CheckStateRole)
        self._refresh_text()

    def set_checked_items(self, items: List[str], *, all_selected: bool = False):
        m = self.model()
        if m.rowCount() == 0:
            return

        if all_selected:
            self.select_all()
            return

        selected = {str(item).strip().upper() for item in items if str(item).strip()}
        m.item(0).setData(Qt.Unchecked, Qt.CheckStateRole)
        for i in range(1, m.rowCount()):
            row = m.item(i)
            state = Qt.Checked if row.text().strip().upper() in selected else Qt.Unchecked
            row.setData(state, Qt.CheckStateRole)
        self._refresh_text()

    def _on_pressed(self, index):
        item = self.model().itemFromIndex(index)
        new_state = Qt.Unchecked if item.data(Qt.CheckStateRole) == Qt.Checked else Qt.Checked
        item.setData(new_state, Qt.CheckStateRole)
        if index.row() == 0 and new_state == Qt.Checked:
            for i in range(1, self.model().rowCount()): self.model().item(i).setData(Qt.Unchecked, Qt.CheckStateRole)
        elif new_state == Qt.Checked:
            self.model().item(0).setData(Qt.Unchecked, Qt.CheckStateRole)
        self._refresh_text()
        self.currentTextChanged.emit(self.currentText())

    def _refresh_text(self):
        checked = self.checked_items()
        self.lineEdit().setText(self._all_label if not checked else ", ".join(checked))


class NumericSortProxy(QSortFilterProxyModel):
    def lessThan(self, left, right):
        if left.column() == 4:
            l, r = self.sourceModel().data(left, Qt.UserRole), self.sourceModel().data(right, Qt.UserRole)
            try: return float(l) < float(r)
            except: return str(l) < str(r)
        return super().lessThan(left, right)


class KPICard(QFrame):
    def __init__(self, title: str, value: str, color: str):
        super().__init__()
        self.color = color
        self.sf = 1.0
        # Tenta herdar o scale factor da MainWindow global
        from PySide6.QtWidgets import QApplication
        mw = next((w for w in QApplication.topLevelWidgets() if hasattr(w, "scale_factor")), None)
        if mw:
            self.sf = mw.scale_factor
            
        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(10*self.sf), int(10*self.sf), int(10*self.sf), int(10*self.sf))
        self.lbl_title = QLabel(title.upper())
        self.lbl_value = QLabel(value)
        self.lbl_title.setObjectName("Titulo")
        self.lbl_value.setObjectName("Valor")
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)
        layout.addStretch(1)

    def update_style(self, theme: dict):
        font_val = int(20 * self.sf)
        font_tit = int(10 * self.sf)
        radius = int(10 * self.sf)
        self.setStyleSheet(f"""
            KPICard {{ background-color: {theme['kpi_bg']}; border-radius: {radius}px; border: 1px solid {theme['kpi_border']}; border-left: {int(6*self.sf)}px solid {self.color}; }}
            QLabel#Valor {{ font-size: {font_val}px; font-weight: 800; color: {theme['text']}; border: none; }}
            QLabel#Titulo {{ font-size: {font_tit}px; font-weight: 800; color: {theme['muted']}; border: none; }}
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
