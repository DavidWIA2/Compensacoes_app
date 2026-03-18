import json
import os
from typing import List

from PySide6.QtCore import Qt


class SettingsController:
    def __init__(self, window):
        self.window = window

    def _value(self, key: str, default=None):
        return self.window.settings.value(key, default)

    def _set_value(self, key: str, value):
        self.window.settings.setValue(key, value)

    def _remove(self, key: str):
        if hasattr(self.window.settings, "remove"):
            self.window.settings.remove(key)

    def update_recent_files_menu(self):
        menu_recent = self.window.menu_recent
        menu_recent.clear()
        if not self.window.recent_files:
            action = menu_recent.addAction("Nenhum")
            action.setEnabled(False)
            return

        for path in self.window.recent_files:
            action = menu_recent.addAction(os.path.basename(path))
            action.setToolTip(path)
            action.triggered.connect(lambda checked=False, p=path: self.window._load_excel(p))

    def load_settings(self):
        if hasattr(self.window.settings, "is_dark_mode"):
            self.window.is_dark_mode = self.window.settings.is_dark_mode()
        else:
            self.window.is_dark_mode = str(self._value("dark_mode", "false")).lower() == "true"

        if hasattr(self.window.settings, "active_tab_index"):
            tab_index = self.window.settings.active_tab_index()
        else:
            tab_index = int(self._value("active_tab_index", 0))
        if 0 <= tab_index < self.window.tabs.count():
            self.window.tabs.setCurrentIndex(tab_index)

        if hasattr(self.window.settings, "recent_files"):
            self.window.recent_files = self.window.settings.recent_files()
        else:
            recents = self._value("recent_files")
            if isinstance(recents, str):
                try:
                    self.window.recent_files = list(json.loads(recents))
                except Exception:
                    self.window.recent_files = []
            elif isinstance(recents, list):
                self.window.recent_files = list(recents)
            else:
                self.window.recent_files = []
        self.update_recent_files_menu()

    def apply_startup_window_state(self):
        if self.window._startup_window_state_applied:
            return

        self.window._startup_window_state_applied = True
        self.window.setWindowState(self.window.windowState() & ~(Qt.WindowMinimized | Qt.WindowFullScreen))
        self.window.showNormal()
        self.window.showMaximized()
        self.window._startup_layout_pending = True

    def load_sort_settings(self):
        if hasattr(self.window.settings, "sort_state"):
            column, order_value = self.window.settings.sort_state()
        else:
            column = int(self._value("sort_column", -1))
            order_value = int(self._value("sort_order", 0))
        if column >= 0:
            order = Qt.SortOrder(order_value)
            self.window.data_tab.proxy.sort(column, order)
            self.window.data_tab.table.horizontalHeader().setSortIndicator(column, order)
        else:
            self.window.data_tab.proxy.sort(-1)

    def save_sort_settings(self):
        if hasattr(self.window.settings, "set_sort_state"):
            self.window.settings.set_sort_state(
                self.window.data_tab.proxy.sortColumn(),
                int(self.window.data_tab.proxy.sortOrder().value),
            )
        else:
            self._set_value("sort_column", self.window.data_tab.proxy.sortColumn())
            self._set_value("sort_order", int(self.window.data_tab.proxy.sortOrder().value))

    def reset_sorting(self):
        self.window.data_tab.proxy.sort(-1)
        if hasattr(self.window.settings, "clear_sort_state"):
            self.window.settings.clear_sort_state()
        else:
            self._set_value("sort_column", -1)

    def toggle_theme(self):
        self.window.is_dark_mode = not self.window.is_dark_mode
        if hasattr(self.window.settings, "set_dark_mode"):
            self.window.settings.set_dark_mode(self.window.is_dark_mode)
        else:
            self._set_value("dark_mode", str(self.window.is_dark_mode).lower())
        self.window._apply_theme()
        self.window.apply_filter()

    def current_map_layer(self) -> str:
        if hasattr(self.window.settings, "map_layer"):
            return self.window.settings.map_layer()
        return str(self._value("map_layer", "Mapa Claro") or "Mapa Claro")

    def save_map_layer_preference(self, layer_name: str):
        if hasattr(self.window.settings, "set_map_layer"):
            self.window.settings.set_map_layer(layer_name)
        else:
            self._set_value("map_layer", layer_name)

    def update_recent_files(self, path: str):
        if path in self.window.recent_files:
            self.window.recent_files.remove(path)
        self.window.recent_files.insert(0, path)
        self.window.recent_files = self.window.recent_files[:5]
        if hasattr(self.window.settings, "set_recent_files"):
            self.window.settings.set_recent_files(self.window.recent_files)
        else:
            self._set_value("recent_files", self.window.recent_files)
        self.update_recent_files_menu()

    def restore_recent_files(self, recent_files: List[str]):
        self.window.recent_files = list(recent_files)
        if hasattr(self.window.settings, "set_recent_files"):
            self.window.settings.set_recent_files(self.window.recent_files)
        else:
            self._set_value("recent_files", self.window.recent_files)
        self.update_recent_files_menu()

    def save_before_close(self):
        self.save_sort_settings()
        if hasattr(self.window.settings, "set_active_tab_index"):
            self.window.settings.set_active_tab_index(self.window.tabs.currentIndex())
        else:
            self._set_value("active_tab_index", self.window.tabs.currentIndex())
        if hasattr(self.window.settings, "set_window_geometry"):
            self.window.settings.set_window_geometry(self.window.saveGeometry())
        else:
            self._set_value("window_geometry", self.window.saveGeometry())

    def restore_last_excel_path(self) -> str:
        if hasattr(self.window.settings, "last_excel_path"):
            return self.window.settings.last_excel_path()
        return str(self._value("last_excel_path", "") or "")

    def save_last_excel_path(self, path: str):
        if hasattr(self.window.settings, "set_last_excel_path"):
            self.window.settings.set_last_excel_path(path)
        else:
            self._set_value("last_excel_path", path)

    def clear_last_excel_path(self):
        if hasattr(self.window.settings, "clear_last_excel_path"):
            self.window.settings.clear_last_excel_path()
        else:
            self._remove("last_excel_path")
