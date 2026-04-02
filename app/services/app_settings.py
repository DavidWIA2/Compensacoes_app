import json
from typing import List, Optional, Tuple

from PySide6.QtCore import QSettings

from app.config import APP_SETTINGS_NAME, APP_SETTINGS_ORG, DEFAULT_MAP_LAYER, DEFAULT_THEME_DARK_MODE


class AppSettings:
    def __init__(self, settings: Optional[QSettings] = None):
        self._settings = settings or QSettings(APP_SETTINGS_ORG, APP_SETTINGS_NAME)

    def value(self, key: str, default=None):
        return self._settings.value(key, default)

    def setValue(self, key: str, value):
        self._settings.setValue(key, value)

    def remove(self, key: str):
        self._settings.remove(key)

    def is_dark_mode(self) -> bool:
        return str(self.value("dark_mode", str(DEFAULT_THEME_DARK_MODE).lower())).lower() == "true"

    def set_dark_mode(self, enabled: bool):
        self.setValue("dark_mode", str(bool(enabled)).lower())

    def active_tab_index(self) -> int:
        return int(self.value("active_tab_index", 0))

    def set_active_tab_index(self, index: int):
        self.setValue("active_tab_index", int(index))

    def recent_files(self) -> List[str]:
        recents = self.value("recent_files")
        if not recents:
            return []
        if isinstance(recents, str):
            try:
                return list(json.loads(recents))
            except Exception:
                return []
        if isinstance(recents, list):
            return list(recents)
        return []

    def set_recent_files(self, paths: List[str]):
        self.setValue("recent_files", list(paths))

    def last_excel_path(self) -> str:
        return str(self.value("last_excel_path", "") or "")

    def set_last_excel_path(self, path: str):
        self.setValue("last_excel_path", path)

    def clear_last_excel_path(self):
        self.remove("last_excel_path")

    def last_export_dir(self) -> str:
        return str(self.value("last_export_dir", "") or "")

    def set_last_export_dir(self, path: str):
        self.setValue("last_export_dir", path)

    def map_layer(self) -> str:
        return str(self.value("map_layer", DEFAULT_MAP_LAYER) or DEFAULT_MAP_LAYER)

    def set_map_layer(self, layer_name: str):
        self.setValue("map_layer", layer_name)

    def sort_state(self) -> Tuple[int, int]:
        return int(self.value("sort_column", -1)), int(self.value("sort_order", 0))

    def set_sort_state(self, column: int, order: int):
        self.setValue("sort_column", int(column))
        self.setValue("sort_order", int(order))

    def clear_sort_state(self):
        self.setValue("sort_column", -1)
        self.setValue("sort_order", 0)

    def window_geometry(self):
        return self.value("window_geometry")

    def set_window_geometry(self, geometry):
        self.setValue("window_geometry", geometry)

    def operation_history_filter_state(self) -> dict:
        state = self.value("operation_history_filter_state", {})
        if isinstance(state, dict):
            return dict(state)
        return {}

    def set_operation_history_filter_state(self, state: dict):
        self.setValue("operation_history_filter_state", dict(state or {}))
