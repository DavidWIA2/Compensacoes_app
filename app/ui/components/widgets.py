from typing import List, Dict
from PySide6.QtCore import Qt, QSortFilterProxyModel, QObject, Slot, Signal, QEvent, QPoint
from PySide6.QtGui import QStandardItemModel, QStandardItem, QFontMetrics, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QFrame, QVBoxLayout, QLabel, QLineEdit, QCheckBox,
    QHBoxLayout, QPushButton, QDialog, QDialogButtonBox, QSizePolicy, QSplitter, QSplitterHandle,
    QStyle, QStyleOptionComboBox,
)

from app.services.records_service import remove_accents

_QWEBENGINE_PAGE_CLS = None
_DEBUG_PAGE_CLS = None


def _ensure_webengine_page_cls():
    global _QWEBENGINE_PAGE_CLS
    if _QWEBENGINE_PAGE_CLS is None:
        from PySide6.QtWebEngineCore import QWebEnginePage as _QWebEnginePage

        _QWEBENGINE_PAGE_CLS = _QWebEnginePage
    return _QWEBENGINE_PAGE_CLS


def _selection_key(value: object) -> str:
    return remove_accents(str(value or "").strip()).upper()


class MapBridge(QObject):
    def __init__(
        self,
        on_clicked_callback,
        on_layer_changed_callback=None,
        on_mapbox_tiles_requested_callback=None,
    ):
        super().__init__()
        self._on_clicked = on_clicked_callback
        self._on_layer_changed = on_layer_changed_callback
        self._on_mapbox_tiles_requested = on_mapbox_tiles_requested_callback

    @Slot(float, float)
    def onMapClicked(self, lat: float, lng: float):
        if self._on_clicked:
            self._on_clicked(lat, lng)

    @Slot(str)
    def onLayerChanged(self, layer_name: str):
        if self._on_layer_changed:
            self._on_layer_changed(layer_name)

    @Slot(int)
    def onMapboxTilesRequested(self, count: int):
        if self._on_mapbox_tiles_requested:
            self._on_mapbox_tiles_requested(count)


def DebugPage(parent=None):
    global _DEBUG_PAGE_CLS
    if _DEBUG_PAGE_CLS is None:
        webengine_page_cls = _ensure_webengine_page_cls()

        class _DebugPage(webengine_page_cls):
            def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
                pass

        _DEBUG_PAGE_CLS = _DebugPage
    return _DEBUG_PAGE_CLS(parent)


class ClickableComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracked_line_edit = None
        self._open_popup_on_release = False
        self._close_popup_on_release = False
        self._open_popup_on_line_edit_release = False
        self._close_popup_on_line_edit_release = False
        self._requested_minimum_width = 0
        self._bind_clickable_line_edit()

    def _bind_clickable_line_edit(self):
        line_edit = self.lineEdit()
        if self._tracked_line_edit is line_edit:
            return
        if self._tracked_line_edit is not None:
            self._tracked_line_edit.removeEventFilter(self)
        self._tracked_line_edit = line_edit
        if self._tracked_line_edit is not None:
            self._tracked_line_edit.installEventFilter(self)

    def setEditable(self, editable: bool):
        super().setEditable(editable)
        self._bind_clickable_line_edit()
        self._refresh_content_minimum_width()

    def setMinimumWidth(self, minw: int):
        self._requested_minimum_width = max(int(minw), 0)
        super().setMinimumWidth(self._requested_minimum_width)
        self._refresh_content_minimum_width()

    def addItem(self, *args):
        super().addItem(*args)
        self._refresh_content_minimum_width()

    def addItems(self, texts):
        super().addItems(texts)
        self._refresh_content_minimum_width()

    def insertItem(self, index, *args):
        super().insertItem(index, *args)
        self._refresh_content_minimum_width()

    def insertItems(self, index, texts):
        super().insertItems(index, texts)
        self._refresh_content_minimum_width()

    def clear(self):
        super().clear()
        self._refresh_content_minimum_width()

    def setModel(self, model):
        super().setModel(model)
        self._refresh_content_minimum_width()

    def _open_popup_from_click(self) -> None:
        if self.view().isVisible():
            return
        self.showPopup()

    def _close_popup_from_click(self) -> None:
        if not self.view().isVisible():
            return
        self.hidePopup()

    @staticmethod
    def _is_left_click(event) -> bool:
        return getattr(event, "button", lambda: None)() == Qt.LeftButton

    def mousePressEvent(self, event):
        if self._is_left_click(event):
            if self.view().isVisible():
                self._close_popup_on_release = True
                self._open_popup_on_release = False
            else:
                self._open_popup_on_release = True
                self._close_popup_on_release = False
            event.accept()
            return
        self._open_popup_on_release = False
        self._close_popup_on_release = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_left_click(event):
            if self._close_popup_on_release:
                self._close_popup_on_release = False
                self._open_popup_on_release = False
                self._close_popup_from_click()
                event.accept()
                return
            if self._open_popup_on_release:
                self._open_popup_on_release = False
                self._close_popup_on_release = False
                self._open_popup_from_click()
                event.accept()
                return
        self._open_popup_on_release = False
        self._close_popup_on_release = False
        super().mouseReleaseEvent(event)

    def eventFilter(self, widget, event):
        if widget is self._tracked_line_edit:
            if event.type() == QEvent.MouseButtonPress:
                if self._is_left_click(event):
                    if self.view().isVisible():
                        self._close_popup_on_line_edit_release = True
                        self._open_popup_on_line_edit_release = False
                    else:
                        self._open_popup_on_line_edit_release = True
                        self._close_popup_on_line_edit_release = False
                    return True
                self._open_popup_on_line_edit_release = False
                self._close_popup_on_line_edit_release = False
            elif event.type() == QEvent.MouseButtonRelease:
                if self._is_left_click(event):
                    if self._close_popup_on_line_edit_release:
                        self._close_popup_on_line_edit_release = False
                        self._open_popup_on_line_edit_release = False
                        self._close_popup_from_click()
                        return True
                    if self._open_popup_on_line_edit_release:
                        self._open_popup_on_line_edit_release = False
                        self._close_popup_on_line_edit_release = False
                        self._open_popup_from_click()
                        return True
                self._open_popup_on_line_edit_release = False
                self._close_popup_on_line_edit_release = False
        return super().eventFilter(widget, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (
            QEvent.FontChange,
            QEvent.StyleChange,
            QEvent.PaletteChange,
            QEvent.ApplicationFontChange,
        ):
            self._refresh_content_minimum_width()

    def _content_width_candidates(self) -> List[str]:
        return [
            self.itemText(index)
            for index in range(self.count())
            if str(self.itemText(index) or "").strip()
        ]

    def _refresh_content_minimum_width(self):
        target_width = max(self._requested_minimum_width, self._content_minimum_width())
        super().setMinimumWidth(target_width)

    def _content_minimum_width(self) -> int:
        texts = self._content_width_candidates()
        if not texts:
            return 0
        font = self.lineEdit().font() if self.lineEdit() is not None else self.font()
        font_metrics = QFontMetrics(font)
        longest_text = max(texts, key=lambda text: font_metrics.horizontalAdvance(str(text)))
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = longest_text
        text_size = font_metrics.size(Qt.TextSingleLine, longest_text)
        base_width = self.style().sizeFromContents(QStyle.CT_ComboBox, option, text_size, self).width()
        safety_padding = max(font_metrics.averageCharWidth() * 2, 18)
        return base_width + safety_padding

    def showPopup(self):
        super().showPopup()
        self._reposition_popup_window()

    def _reposition_popup_window(self) -> None:
        popup = self.view().window()
        if popup is None or not popup.isVisible():
            return

        popup_geometry = popup.frameGeometry()
        popup_width = popup_geometry.width()
        popup_height = popup_geometry.height()
        if popup_width <= 0 or popup_height <= 0:
            return

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        gap = 2

        combo_top_left = self.mapToGlobal(self.rect().topLeft())
        combo_bottom_left = self.mapToGlobal(self.rect().bottomLeft())
        combo_bottom_y = combo_bottom_left.y() + 1

        target_x = min(
            max(combo_top_left.x(), available.left()),
            max(available.right() - popup_width + 1, available.left()),
        )

        preferred_below_y = combo_bottom_y + gap
        preferred_above_y = combo_top_left.y() - popup_height - gap

        if preferred_below_y + popup_height <= available.bottom() + 1:
            target_y = preferred_below_y
        elif preferred_above_y >= available.top():
            target_y = preferred_above_y
        else:
            target_y = min(
                max(preferred_below_y, available.top()),
                max(available.bottom() - popup_height + 1, available.top()),
            )

        popup.move(QPoint(target_x, target_y))


class CheckableComboBox(ClickableComboBox):
    selectionChanged = Signal()

    def __init__(self, all_label: str, parent=None):
        super().__init__(parent)
        self._all_label = all_label
        self._block = False
        self.setEditable(True)
        self._configure_display_line_edit()
        self.lineEdit().setPlaceholderText(all_label)
        
        # O segredo para combos de multiseleção estáveis no Qt: eventFilter no viewport
        self.view().viewport().installEventFilter(self)
        self.set_items([])

    def eventFilter(self, widget, event):
        if widget == self.view().viewport() and event.type() == QEvent.MouseButtonRelease:
            mouse_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            index = self.view().indexAt(mouse_pos)
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
        self.setEditText(txt)
        self._reset_display_text_position()

    def _reset_display_text_position(self):
        line_edit = self.lineEdit()
        if line_edit is None:
            return
        line_edit.deselect()
        line_edit.setCursorPosition(0)

    def _content_width_candidates(self) -> List[str]:
        texts = [self._all_label] if str(self._all_label or "").strip() else []
        placeholder = self.lineEdit().placeholderText() if self.lineEdit() is not None else ""
        if str(placeholder or "").strip() and placeholder not in texts:
            texts.append(placeholder)
        return texts

    def _configure_display_line_edit(self):
        line_edit = self.lineEdit()
        if line_edit is None:
            return
        line_edit.setReadOnly(True)
        line_edit.setFrame(False)
        line_edit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        line_edit.setTextMargins(0, 0, 0, 0)
        line_edit.setContentsMargins(0, 0, 0, 0)
        line_edit.setStyleSheet(
            "QLineEdit { background: transparent; border: none; padding: 0px; margin: 0px; }"
        )


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
            layout.setContentsMargins(int(10 * self.sf), int(6 * self.sf), int(10 * self.sf), int(7 * self.sf))
            layout.setSpacing(max(int(2 * self.sf), 1))
        else:
            layout.setContentsMargins(int(10 * self.sf), int(10 * self.sf), int(10 * self.sf), int(10 * self.sf))
        self.lbl_title = QLabel(title)
        self.lbl_value = QLabel(value)
        self.lbl_title.setObjectName("Titulo")
        self.lbl_value.setObjectName("Valor")
        self.lbl_title.setWordWrap(True)
        self.lbl_value.setWordWrap(False)
        self.lbl_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if self.compact:
            self.lbl_value.setMinimumHeight(max(int(18 * self.sf), 18))
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)
        if not self.compact:
            layout.addStretch(1)

    def update_style(self, theme: dict):
        font_val = int((15 if self.compact else 20) * self.sf)
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
