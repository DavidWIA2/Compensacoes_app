from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable, Sequence


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
