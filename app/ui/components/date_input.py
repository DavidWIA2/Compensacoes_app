from __future__ import annotations

from PySide6.QtCore import QPoint, QDate, QTimer, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QCalendarWidget, QFrame, QLineEdit, QStyle, QVBoxLayout, QWidget


def format_date_input_text(raw_text: str) -> str:
    digits = "".join(character for character in raw_text if character.isdigit())[:8]
    if not digits:
        return ""
    if len(digits) <= 2:
        return digits
    if len(digits) <= 4:
        return f"{digits[:2]}/{digits[2:]}"
    return f"{digits[:2]}/{digits[2:4]}/{digits[4:]}"


def _parse_qdate_from_text(text: str) -> QDate | None:
    normalized = format_date_input_text(text)
    parts = normalized.split("/")
    if len(parts) != 3 or any(not part for part in parts):
        return None
    try:
        day = int(parts[0])
        month = int(parts[1])
        year = int(parts[2])
    except ValueError:
        return None
    qdate = QDate(year, month, day)
    return qdate if qdate.isValid() else None


class _CalendarPopup(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("dateCalendarPopup")

        self.calendar = QCalendarWidget(self)
        self.calendar.setGridVisible(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.calendar)

    def open_below(self, anchor: QWidget) -> None:
        self.adjustSize()
        position = anchor.mapToGlobal(QPoint(0, anchor.height()))
        screen = anchor.screen()
        if screen is not None:
            geometry = screen.availableGeometry()
            x = min(max(position.x(), geometry.left()), geometry.right() - self.width() + 1)
            y = position.y()
            if y + self.height() > geometry.bottom():
                y = anchor.mapToGlobal(QPoint(0, 0)).y() - self.height()
            y = max(y, geometry.top())
            position = QPoint(x, y)
        self.move(position)
        self.show()
        self.raise_()
        self.activateWindow()


class DatePickerLineEdit(QLineEdit):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setPlaceholderText("dd/mm/aaaa")
        self.setMaxLength(10)
        self.setClearButtonEnabled(True)
        self.setToolTip("Clique para abrir o calendário ou digite a data. As barras são inseridas automaticamente.")

        self._normalizing = False
        self._popup_pending = False
        self._popup: _CalendarPopup | None = None
        self._popup_timer = QTimer(self)
        self._popup_timer.setSingleShot(True)
        self._popup_timer.setInterval(180)
        self._popup_timer.timeout.connect(self._open_pending_popup)

        action = self.addAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        action.triggered.connect(self.open_calendar_popup)
        self.textEdited.connect(self._normalize_edited_text)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.isEnabled()
            and not self.isReadOnly()
        ):
            self._popup_pending = True
            self._popup_timer.start()
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._popup_timer.isActive():
            self._popup_timer.stop()
            self._popup_pending = False
        if self._popup is not None and self._popup.isVisible() and (
            event.text() or event.key() in {Qt.Key.Key_Backspace, Qt.Key.Key_Delete}
        ):
            self._popup.hide()
        if event.key() == Qt.Key.Key_F4 or (
            event.key() == Qt.Key.Key_Down and event.modifiers() & Qt.KeyboardModifier.AltModifier
        ):
            self.open_calendar_popup()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # type: ignore[override]
        if self._popup_timer.isActive():
            self._popup_timer.stop()
            self._popup_pending = False
        super().focusOutEvent(event)

    def setText(self, text: str) -> None:
        self._apply_text(format_date_input_text(text))

    def open_calendar_popup(self) -> None:
        if not self.isEnabled() or self.isReadOnly():
            return
        if self._popup_timer.isActive():
            self._popup_timer.stop()
        self._popup_pending = False
        popup = self._ensure_popup()
        selected = _parse_qdate_from_text(super().text()) or QDate.currentDate()
        popup.calendar.setSelectedDate(selected)
        popup.open_below(self)

    def _ensure_popup(self) -> _CalendarPopup:
        if self._popup is None:
            self._popup = _CalendarPopup(self)
            self._popup.calendar.clicked.connect(self._apply_calendar_date)
            self._popup.calendar.activated.connect(self._apply_calendar_date)
        return self._popup

    def _open_pending_popup(self) -> None:
        if self._popup_pending:
            self.open_calendar_popup()

    def _normalize_edited_text(self, _text: str) -> None:
        if self._normalizing:
            return
        self._apply_text(format_date_input_text(super().text()))
        self.setCursorPosition(len(super().text()))

    def _apply_text(self, normalized_text: str) -> None:
        if normalized_text == super().text():
            return
        self._normalizing = True
        try:
            super().setText(normalized_text)
        finally:
            self._normalizing = False

    def _apply_calendar_date(self, qdate: QDate) -> None:
        self._apply_text(qdate.toString("dd/MM/yyyy"))
        if self._popup is not None:
            self._popup.hide()
        self.setFocus(Qt.FocusReason.PopupFocusReason)
        self.end(False)
