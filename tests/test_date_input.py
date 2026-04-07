import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.ui.components.date_input import DatePickerLineEdit, format_date_input_text


def get_app():
    return QApplication.instance() or QApplication([])


def test_format_date_input_text_inserts_slashes_progressively():
    assert format_date_input_text("") == ""
    assert format_date_input_text("0") == "0"
    assert format_date_input_text("010") == "01/0"
    assert format_date_input_text("0104") == "01/04"
    assert format_date_input_text("01042026") == "01/04/2026"
    assert format_date_input_text("01/04/2026") == "01/04/2026"


def test_date_picker_line_edit_formats_manual_typing():
    get_app()
    widget = DatePickerLineEdit()
    widget.show()
    widget.setFocus()

    QTest.keyClicks(widget, "01042026")

    assert widget.text() == "01/04/2026"


def test_date_picker_line_edit_opens_popup_on_click_and_applies_selected_date():
    get_app()
    widget = DatePickerLineEdit()
    widget.resize(180, 32)
    widget.show()
    widget.activateWindow()
    widget.setFocus()

    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    QTest.qWait(240)

    assert widget._popup is not None
    assert widget._popup.isVisible() is True

    selected = QDate(2026, 4, 7)
    widget._popup.calendar.clicked.emit(selected)
    QTest.qWait(20)

    assert widget.text() == "07/04/2026"
    assert widget._popup.isVisible() is False
