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
    if is_maximized:
        exceeds_maximized_bounds = (
            geometry.left() < available.left()
            or geometry.top() < available.top()
            or geometry.right() > available.right()
            or geometry.bottom() > available.bottom()
        )
        if not exceeds_maximized_bounds:
            return False
        normalized_state = state & ~(Qt.WindowMinimized | Qt.WindowFullScreen | Qt.WindowMaximized)
        window.setWindowState(normalized_state)
        window.setWindowState(normalized_state | Qt.WindowMaximized)
        return True

    height_margin = max(int(available.height() * 0.02), 16)
    bottom_overlap = geometry.bottom() - available.bottom()
    content_geometry = None
    try:
        content_geometry = window.geometry()
    except Exception:
        content_geometry = None
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
        return False

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
