from PySide6.QtCore import Qt

from app.ui.controllers.settings_support import ensure_window_fits_available_geometry


class FakeGeometry:
    def __init__(self, left: int, top: int, width: int, height: int):
        self._left = left
        self._top = top
        self._width = width
        self._height = height

    def left(self):
        return self._left

    def top(self):
        return self._top

    def width(self):
        return self._width

    def height(self):
        return self._height

    def right(self):
        return self._left + self._width - 1

    def bottom(self):
        return self._top + self._height - 1


class FakeSize:
    def __init__(self, width: int, height: int):
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


class FakeScreen:
    def __init__(self, available_geometry: FakeGeometry):
        self._available_geometry = available_geometry

    def availableGeometry(self):
        return self._available_geometry

    def geometry(self):
        return self._available_geometry


class FakeWindow:
    def __init__(
        self,
        *,
        state,
        frame_geometry: FakeGeometry,
        screen: FakeScreen,
        minimum_size: FakeSize | None = None,
        minimum_size_hint: FakeSize | None = None,
    ):
        self._state = state
        self._frame_geometry = frame_geometry
        self._geometry = frame_geometry
        self._screen = screen
        self._minimum_size = minimum_size or FakeSize(0, 0)
        self._minimum_size_hint = minimum_size_hint or FakeSize(0, 0)
        self.applied_states = []
        self.resize_calls = []
        self.move_calls = []
        self.minimum_size_calls = []

    def windowState(self):
        return self._state

    def setWindowState(self, state):
        self._state = state
        self.applied_states.append(state)

    def frameGeometry(self):
        return self._frame_geometry

    def geometry(self):
        return self._geometry

    def screen(self):
        return self._screen

    def minimumSize(self):
        return self._minimum_size

    def minimumSizeHint(self):
        return self._minimum_size_hint

    def setMinimumSize(self, width, height):
        self.minimum_size_calls.append((width, height))
        self._minimum_size = FakeSize(width, height)

    def resize(self, width, height):
        self.resize_calls.append((width, height))
        self._geometry = FakeGeometry(self._geometry.left(), self._geometry.top(), width, height)
        self._frame_geometry = FakeGeometry(self._frame_geometry.left(), self._frame_geometry.top(), width, height)

    def move(self, x, y):
        self.move_calls.append((x, y))
        self._geometry = FakeGeometry(x, y, self._geometry.width(), self._geometry.height())
        self._frame_geometry = FakeGeometry(x, y, self._frame_geometry.width(), self._frame_geometry.height())


def test_ensure_window_fits_available_geometry_maximizes_oversized_window():
    window = FakeWindow(
        state=Qt.WindowNoState,
        frame_geometry=FakeGeometry(0, 0, 1800, 1100),
        screen=FakeScreen(FakeGeometry(0, 0, 1600, 900)),
    )

    changed = ensure_window_fits_available_geometry(window)

    assert changed is True
    assert window.applied_states
    assert window.windowState() & Qt.WindowMaximized


def test_ensure_window_fits_available_geometry_keeps_window_when_it_already_fits():
    window = FakeWindow(
        state=Qt.WindowNoState,
        frame_geometry=FakeGeometry(10, 10, 1200, 700),
        screen=FakeScreen(FakeGeometry(0, 0, 1600, 900)),
    )

    changed = ensure_window_fits_available_geometry(window)

    assert changed is False
    assert window.applied_states == []


def test_ensure_window_fits_available_geometry_ignores_already_maximized_window():
    window = FakeWindow(
        state=Qt.WindowMaximized,
        frame_geometry=FakeGeometry(0, 0, 1600, 900),
        screen=FakeScreen(FakeGeometry(0, 0, 1600, 900)),
    )

    changed = ensure_window_fits_available_geometry(window)

    assert changed is False
    assert window.applied_states == []


def test_ensure_window_fits_available_geometry_remaximizes_overflowing_maximized_window():
    window = FakeWindow(
        state=Qt.WindowMaximized,
        frame_geometry=FakeGeometry(0, -8, 1600, 940),
        screen=FakeScreen(FakeGeometry(0, 0, 1600, 900)),
    )

    changed = ensure_window_fits_available_geometry(window)

    assert changed is True
    assert len(window.applied_states) == 2
    assert not (window.applied_states[0] & Qt.WindowMaximized)
    assert window.windowState() & Qt.WindowMaximized


def test_ensure_window_fits_available_geometry_keeps_nearly_fullscreen_window_when_it_fits():
    window = FakeWindow(
        state=Qt.WindowNoState,
        frame_geometry=FakeGeometry(0, 0, 1590, 890),
        screen=FakeScreen(FakeGeometry(0, 0, 1600, 900)),
    )

    changed = ensure_window_fits_available_geometry(window)

    assert changed is False
    assert window.applied_states == []


def test_ensure_window_fits_available_geometry_trims_small_bottom_overlap():
    window = FakeWindow(
        state=Qt.WindowNoState,
        frame_geometry=FakeGeometry(0, 0, 1580, 908),
        screen=FakeScreen(FakeGeometry(0, 0, 1600, 900)),
    )

    changed = ensure_window_fits_available_geometry(window)

    assert changed is True
    assert window.applied_states == []
    assert window.resize_calls


def test_ensure_window_fits_available_geometry_clamps_excessive_minimum_size_hint_even_when_geometry_fits():
    window = FakeWindow(
        state=Qt.WindowMaximized,
        frame_geometry=FakeGeometry(0, 0, 1600, 900),
        screen=FakeScreen(FakeGeometry(0, 0, 1600, 900)),
        minimum_size_hint=FakeSize(934, 1210),
    )

    changed = ensure_window_fits_available_geometry(window)

    assert changed is True
    assert window.applied_states == []
    assert window.minimum_size_calls == [(0, 891)]


def test_ensure_window_fits_available_geometry_restores_original_minimum_size_after_clamp():
    window = FakeWindow(
        state=Qt.WindowMaximized,
        frame_geometry=FakeGeometry(0, 0, 1600, 900),
        screen=FakeScreen(FakeGeometry(0, 0, 1600, 900)),
        minimum_size=FakeSize(120, 80),
        minimum_size_hint=FakeSize(934, 1210),
    )

    first_changed = ensure_window_fits_available_geometry(window)

    window._minimum_size_hint = FakeSize(934, 716)
    second_changed = ensure_window_fits_available_geometry(window)

    assert first_changed is True
    assert second_changed is True
    assert window.minimum_size_calls == [(120, 891), (120, 80)]
