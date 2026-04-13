from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class LoadedWindowSettingsState:
    is_dark_mode: bool
    geometry_restored: bool
    active_tab_index: int
    recent_files: tuple[str, ...]


def is_named_session_path(path: str) -> bool:
    return str(path or "").strip().lower().startswith("session://")


def normalize_session_path(path: str) -> str:
    clean = str(path or "").strip()
    if not clean:
        return ""
    if is_named_session_path(clean):
        return clean
    return os.path.abspath(clean)


def coerce_recent_files(raw_value) -> list[str]:
    if not raw_value:
        return []
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if str(item).strip()]
    if isinstance(raw_value, str):
        try:
            decoded = json.loads(raw_value)
        except Exception:
            return []
        if isinstance(decoded, list):
            return [str(item) for item in decoded if str(item).strip()]
    return []


def collapse_recent_files_for_single_database_mode(recent_files: Sequence[str]) -> list[str]:
    del recent_files
    return []


def build_loaded_window_settings_state(
    *,
    is_dark_mode: bool,
    geometry,
    restore_geometry,
    active_tab_index: int,
    tabs_count: int,
    recent_files: Iterable[str],
) -> LoadedWindowSettingsState:
    geometry_restored = bool(geometry and restore_geometry(geometry))
    resolved_tab_index = int(active_tab_index)
    if not 0 <= resolved_tab_index < tabs_count:
        resolved_tab_index = 0
    return LoadedWindowSettingsState(
        is_dark_mode=bool(is_dark_mode),
        geometry_restored=geometry_restored,
        active_tab_index=resolved_tab_index,
        recent_files=tuple(str(path) for path in recent_files if str(path).strip()),
    )


def _size_dimension(size, accessor_name: str) -> int:
    if size is None:
        return 0
    accessor = getattr(size, accessor_name, None)
    if callable(accessor):
        try:
            return max(int(accessor() or 0), 0)
        except Exception:
            return 0
    try:
        return max(int(getattr(size, accessor_name, 0) or 0), 0)
    except Exception:
        return 0


def _restore_clamped_window_minimum_size(window) -> bool:
    saved_minimum = getattr(window, "_fit_original_minimum_size", None)
    if saved_minimum is None:
        return False

    try:
        current_minimum = window.minimumSize()
    except Exception:
        current_minimum = None

    current_width = _size_dimension(current_minimum, "width")
    current_height = _size_dimension(current_minimum, "height")
    original_width, original_height = (
        max(int(saved_minimum[0]), 0),
        max(int(saved_minimum[1]), 0),
    )

    if current_width == original_width and current_height == original_height:
        setattr(window, "_fit_original_minimum_size", None)
        return False

    try:
        window.setMinimumSize(original_width, original_height)
    except Exception:
        return False

    setattr(window, "_fit_original_minimum_size", None)
    return True


def _clamp_window_minimum_size_to_available_geometry(window, available, frame_geometry, content_geometry) -> bool:
    if window is None or available is None:
        return False

    try:
        minimum_size = window.minimumSize()
    except Exception:
        minimum_size = None
    try:
        minimum_size_hint = window.minimumSizeHint()
    except Exception:
        minimum_size_hint = None

    explicit_minimum_width = _size_dimension(minimum_size, "width")
    explicit_minimum_height = _size_dimension(minimum_size, "height")
    hinted_minimum_width = _size_dimension(minimum_size_hint, "width")
    hinted_minimum_height = _size_dimension(minimum_size_hint, "height")

    reference_frame = frame_geometry or content_geometry
    reference_content = content_geometry or reference_frame
    frame_width_delta = max(
        _size_dimension(reference_frame, "width") - _size_dimension(reference_content, "width"),
        0,
    )
    frame_height_delta = max(
        _size_dimension(reference_frame, "height") - _size_dimension(reference_content, "height"),
        0,
    )
    height_margin = max(int(available.height() * 0.02), 16)
    safety_inset = max(min(height_margin // 2, 12), 6)
    max_content_width = max(available.width() - frame_width_delta, 640)
    max_content_height = max(available.height() - frame_height_delta - safety_inset, 320)

    needs_width_clamp = max(explicit_minimum_width, hinted_minimum_width) > max_content_width
    needs_height_clamp = max(explicit_minimum_height, hinted_minimum_height) > max_content_height

    if not needs_width_clamp and not needs_height_clamp:
        return _restore_clamped_window_minimum_size(window)

    if getattr(window, "_fit_original_minimum_size", None) is None:
        setattr(
            window,
            "_fit_original_minimum_size",
            (explicit_minimum_width, explicit_minimum_height),
        )

    target_minimum_width = max_content_width if needs_width_clamp else explicit_minimum_width
    target_minimum_height = max_content_height if needs_height_clamp else explicit_minimum_height

    if (
        explicit_minimum_width == target_minimum_width
        and explicit_minimum_height == target_minimum_height
    ):
        return False

    try:
        window.setMinimumSize(target_minimum_width, target_minimum_height)
    except Exception:
        return False
    return True


def ensure_window_fits_available_geometry(window) -> bool:
    if window is None:
        return False

    try:
        state = window.windowState()
    except Exception:
        return False

    is_maximized = bool(state & Qt.WindowMaximized)
    is_fullscreen = bool(state & Qt.WindowFullScreen)
    if is_fullscreen:
        return False

    screen = None
    try:
        screen = window.screen()
    except Exception:
        screen = None
    if screen is None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return False

    available = screen.availableGeometry() if hasattr(screen, "availableGeometry") else screen.geometry()
    geometry = window.frameGeometry()
    content_geometry = None
    try:
        content_geometry = window.geometry()
    except Exception:
        content_geometry = None
    minimum_size_adjusted = _clamp_window_minimum_size_to_available_geometry(
        window,
        available,
        geometry,
        content_geometry,
    )
    if is_maximized:
        exceeds_maximized_bounds = (
            geometry.left() < available.left()
            or geometry.top() < available.top()
            or geometry.right() > available.right()
            or geometry.bottom() > available.bottom()
        )
        if not exceeds_maximized_bounds:
            return minimum_size_adjusted
        normalized_state = state & ~(Qt.WindowMinimized | Qt.WindowFullScreen | Qt.WindowMaximized)
        window.setWindowState(normalized_state)
        window.setWindowState(normalized_state | Qt.WindowMaximized)
        return True

    height_margin = max(int(available.height() * 0.02), 16)
    bottom_overlap = geometry.bottom() - available.bottom()
    exceeds_bounds = (
        geometry.width() > available.width()
        or geometry.height() > available.height()
        or geometry.left() < available.left()
        or geometry.top() < available.top()
        or geometry.right() > available.right()
        or geometry.bottom() > available.bottom()
    )
    slight_bottom_cut = (
        bottom_overlap >= 0
        and bottom_overlap <= max(height_margin, 24)
        and geometry.left() >= available.left()
        and geometry.right() <= available.right()
        and content_geometry is not None
    )

    if slight_bottom_cut and content_geometry is not None:
        frame_height_delta = max(geometry.height() - content_geometry.height(), 0)
        frame_width_delta = max(geometry.width() - content_geometry.width(), 0)
        safety_inset = max(min(height_margin // 2, 12), 6)
        target_content_height = max(available.height() - frame_height_delta - safety_inset, 320)
        target_content_width = min(
            content_geometry.width(),
            max(available.width() - frame_width_delta, 640),
        )
        if content_geometry.height() > target_content_height or content_geometry.width() > target_content_width:
            try:
                window.resize(target_content_width, target_content_height)
            except Exception:
                pass
        try:
            target_x = max(content_geometry.left(), available.left())
            target_y = max(available.top(), content_geometry.top())
            window.move(target_x, target_y)
        except Exception:
            pass
        return True

    if not exceeds_bounds:
        return minimum_size_adjusted

    normalized_state = state & ~(Qt.WindowMinimized | Qt.WindowFullScreen)
    window.setWindowState(normalized_state | Qt.WindowMaximized)
    return True


def resolve_preferred_directory(*candidates: str) -> str:
    for candidate in candidates:
        normalized = normalize_session_path(candidate)
        if not normalized or is_named_session_path(normalized):
            continue
        if os.path.isdir(normalized):
            return normalized
        parent = os.path.dirname(normalized)
        if parent and os.path.isdir(parent):
            return parent
    return ""
