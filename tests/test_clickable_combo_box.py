import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionComboBox

from app.ui.components.widgets import CheckableComboBox, ClickableComboBox


def get_app():
    return QApplication.instance() or QApplication([])


def process_events():
    app = get_app()
    app.processEvents()
    QTest.qWait(1)
    app.processEvents()


def expected_combo_width(combo, text):
    font = combo.lineEdit().font() if combo.lineEdit() is not None else combo.font()
    font_metrics = QFontMetrics(font)
    option = QStyleOptionComboBox()
    combo.initStyleOption(option)
    option.currentText = text
    text_size = font_metrics.size(Qt.TextSingleLine, text)
    return combo.style().sizeFromContents(QStyle.CT_ComboBox, option, text_size, combo).width()


class TrackingClickableComboBox(ClickableComboBox):
    def __init__(self):
        super().__init__()
        self.popup_requests = 0

    def showPopup(self):
        self.popup_requests += 1
        super().showPopup()


class TrackingCheckableComboBox(CheckableComboBox):
    def __init__(self, all_label: str):
        super().__init__(all_label)
        self.popup_requests = 0

    def showPopup(self):
        self.popup_requests += 1
        super().showPopup()


def test_clickable_combo_box_opens_popup_on_mouse_release():
    get_app()
    combo = TrackingClickableComboBox()
    combo.addItems(["Todos", "Ativos", "Arquivados"])
    combo.resize(180, 32)
    combo.show()
    process_events()

    center = combo.rect().center()
    QTest.mousePress(combo, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    process_events()
    assert combo.popup_requests == 0
    assert not combo.view().isVisible()

    QTest.mouseRelease(combo, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    process_events()
    assert combo.popup_requests == 1
    assert combo.view().isVisible()


def test_clickable_combo_box_allows_selection_after_clicking_center():
    get_app()
    combo = TrackingClickableComboBox()
    combo.addItems(["Todos", "Ativos", "Arquivados"])
    combo.resize(180, 32)
    combo.show()
    process_events()

    QTest.mouseClick(combo, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, combo.rect().center())
    process_events()

    view = combo.view()
    row_rect = view.visualRect(combo.model().index(1, 0))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, row_rect.center())
    process_events()

    assert combo.currentText() == "Ativos"


def test_clickable_combo_box_closes_popup_on_second_click():
    get_app()
    combo = TrackingClickableComboBox()
    combo.addItems(["Todos", "Ativos", "Arquivados"])
    combo.resize(180, 32)
    combo.show()
    process_events()

    center = combo.rect().center()
    QTest.mouseClick(combo, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    process_events()
    assert combo.view().isVisible()

    QTest.mouseClick(combo, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    process_events()
    assert not combo.view().isVisible()


def test_checkable_combo_box_opens_popup_on_line_edit_release():
    get_app()
    combo = TrackingCheckableComboBox("Todos os Tipos")
    combo.set_items(["Eletronico", "Fisico"])
    combo.resize(220, 32)
    combo.show()
    process_events()

    line_edit = combo.lineEdit()
    center_point = QPoint(max(line_edit.width() // 2, 1), max(line_edit.height() // 2, 1))
    QTest.mousePress(line_edit, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_point)
    process_events()
    assert combo.popup_requests == 0
    assert not combo.view().isVisible()

    QTest.mouseRelease(line_edit, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_point)
    process_events()
    assert combo.popup_requests == 1
    assert combo.view().isVisible()


def test_checkable_combo_box_keeps_popup_open_while_toggling_item():
    get_app()
    combo = TrackingCheckableComboBox("Todos os Tipos")
    combo.set_items(["Eletronico", "Fisico"])
    combo.resize(220, 32)
    combo.show()
    process_events()

    line_edit = combo.lineEdit()
    center_point = QPoint(max(line_edit.width() // 2, 1), max(line_edit.height() // 2, 1))
    QTest.mouseClick(line_edit, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_point)
    process_events()

    view = combo.view()
    row_rect = view.visualRect(combo.model().index(1, 0))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, row_rect.center())
    process_events()

    assert combo.checked_items() == ["Eletronico"]
    assert combo.view().isVisible()


def test_checkable_combo_box_closes_popup_on_second_click():
    get_app()
    combo = TrackingCheckableComboBox("Todos os Tipos")
    combo.set_items(["Eletronico", "Fisico"])
    combo.resize(220, 32)
    combo.show()
    process_events()

    line_edit = combo.lineEdit()
    center_point = QPoint(max(line_edit.width() // 2, 1), max(line_edit.height() // 2, 1))
    QTest.mouseClick(line_edit, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_point)
    process_events()
    assert combo.view().isVisible()

    QTest.mouseClick(line_edit, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_point)
    process_events()
    assert not combo.view().isVisible()


def test_checkable_combo_box_positions_popup_below_combo_when_space_available():
    get_app()
    combo = TrackingCheckableComboBox("Todas as Microbacias")
    combo.set_items(["Microbacia Norte", "Microbacia Sul"])
    combo.resize(260, 32)
    combo.show()
    process_events()

    combo.showPopup()
    process_events()

    popup_top = combo.view().window().frameGeometry().top()
    combo_bottom = combo.mapToGlobal(combo.rect().bottomLeft()).y()

    assert popup_top >= combo_bottom + 1


def test_checkable_combo_box_keeps_displayed_label_aligned_from_start():
    get_app()
    combo = TrackingCheckableComboBox("Todas as Microbacias")
    combo.set_items(["Microbacia Norte", "Microbacia Sul"])
    combo.resize(220, 32)
    combo.show()
    process_events()

    line_edit = combo.lineEdit()

    assert line_edit.text() == "Todas as Microbacias"
    assert line_edit.cursorPosition() == 0


def test_checkable_combo_box_resets_display_cursor_after_selection_changes():
    get_app()
    combo = TrackingCheckableComboBox("Todas as Microbacias")
    combo.set_items(["Microbacia Norte", "Microbacia Sul"])
    combo.resize(220, 32)
    combo.show()
    process_events()

    combo.set_checked_items(["Microbacia Norte"])
    process_events()

    line_edit = combo.lineEdit()

    assert line_edit.text() == "Microbacia Norte"
    assert line_edit.cursorPosition() == 0


def test_checkable_combo_box_uses_frameless_zero_padding_line_edit():
    get_app()
    combo = TrackingCheckableComboBox("Todas as Microbacias")
    combo.set_items(["Microbacia Norte", "Microbacia Sul"])
    process_events()

    line_edit = combo.lineEdit()
    margins = line_edit.textMargins()

    assert not line_edit.hasFrame()
    assert margins.left() == 0
    assert margins.right() == 0
    assert "padding: 0px" in line_edit.styleSheet()


def test_clickable_combo_box_expands_minimum_width_to_fit_longest_item():
    get_app()
    combo = TrackingClickableComboBox()
    combo.setMinimumWidth(90)
    combo.addItems(["Todos", "Compensados", "Pendentes"])
    process_events()

    assert combo.minimumWidth() >= expected_combo_width(combo, "Compensados")


def test_checkable_combo_box_expands_minimum_width_to_fit_all_label():
    get_app()
    combo = TrackingCheckableComboBox("Todas as Microbacias")
    combo.setMinimumWidth(120)
    combo.set_items(["Microbacia Norte", "Microbacia Sul"])
    process_events()

    assert combo.minimumWidth() >= expected_combo_width(combo, "Todas as Microbacias")


def test_checkable_combo_box_keeps_visible_text_area_wider_than_label():
    get_app()
    combo = TrackingCheckableComboBox("Todas as Microbacias")
    combo.set_items(["Microbacia Norte", "Microbacia Sul"])
    combo.show()
    process_events()

    line_edit = combo.lineEdit()
    font_metrics = QFontMetrics(line_edit.font())

    assert line_edit.width() >= font_metrics.horizontalAdvance("Todas as Microbacias") + 8
