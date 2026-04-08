import os
from typing import List

from PySide6.QtCore import Qt, QTimer

from app.ui.controllers.settings_support import (
    build_loaded_window_settings_state,
    coerce_recent_files,
    collapse_recent_files_for_single_database_mode,
    ensure_window_fits_available_geometry,
    is_named_session_path,
    normalize_session_path,
    resolve_preferred_directory,
)


class SettingsController:
    def __init__(self, window):
        self.window = window

    @staticmethod
    def _is_named_session(path: str) -> bool:
        return is_named_session_path(path)

    @staticmethod
    def _normalize_path(path: str) -> str:
        return normalize_session_path(path)

    def _value(self, key: str, default=None):
        return self.window.settings.value(key, default)

    def _set_value(self, key: str, value):
        self.window.settings.setValue(key, value)

    def _remove(self, key: str):
        if hasattr(self.window.settings, "remove"):
            self.window.settings.remove(key)

    def update_recent_files_menu(self):
        menu_recent = getattr(self.window, "menu_recent", None)
        if menu_recent is None:
            return
        menu_recent.clear()
        if not self.window.recent_files:
            action = menu_recent.addAction("Nenhum")
            action.setEnabled(False)
            return

        for path in self.window.recent_files:
            availability = self._resolve_session_availability(path)
            action = menu_recent.addAction(availability.display_label)
            action.setToolTip(availability.detail_message)
            action.triggered.connect(lambda checked=False, p=path: self.window._load_session(p))

    def _resolve_session_availability(self, path: str):
        normalized = self._normalize_path(path)
        persistence = getattr(self.window, "authoritative_persistence", None)
        if persistence is not None:
            return persistence.resolve_session_availability(normalized)

        class _FallbackAvailability:
            def __init__(self, target_path: str):
                self.path = target_path
                self.display_name = os.path.basename(target_path) or target_path
                self.has_workbook_file = bool(target_path and os.path.exists(target_path))
                self.has_local_snapshot = False
                self.source_kind = "workbook_only" if self.has_workbook_file else "missing"

            @property
            def is_openable(self) -> bool:
                return self.has_workbook_file

            @property
            def display_label(self) -> str:
                return self.display_name or "nenhuma"

            @property
            def detail_message(self) -> str:
                if self.has_workbook_file:
                    return f"Sessão vinculada a {self.path} com arquivo original disponível."
                return f"Sessão indisponível para {self.path}."

        return _FallbackAvailability(normalized)

    def _sanitize_recent_files(self, recent_files: List[str]) -> List[str]:
        return collapse_recent_files_for_single_database_mode(recent_files)

    def load_settings(self):
        is_dark_mode = (
            self.window.settings.is_dark_mode()
            if hasattr(self.window.settings, "is_dark_mode")
            else str(self._value("dark_mode", "false")).lower() == "true"
        )
        geometry = (
            self.window.settings.window_geometry()
            if hasattr(self.window.settings, "window_geometry")
            else self._value("window_geometry")
        )
        active_tab_index = (
            self.window.settings.active_tab_index()
            if hasattr(self.window.settings, "active_tab_index")
            else int(self._value("active_tab_index", 0))
        )
        raw_recent_files = (
            self.window.settings.recent_files()
            if hasattr(self.window.settings, "recent_files")
            else coerce_recent_files(self._value("recent_files"))
        )
        loaded_state = build_loaded_window_settings_state(
            is_dark_mode=is_dark_mode,
            geometry=geometry,
            restore_geometry=self.window.restoreGeometry,
            active_tab_index=active_tab_index,
            tabs_count=self.window.tabs.count(),
            recent_files=self._sanitize_recent_files(list(raw_recent_files)),
        )
        self.window.is_dark_mode = loaded_state.is_dark_mode
        self.window._startup_geometry_restored = loaded_state.geometry_restored
        self.window.tabs.setCurrentIndex(loaded_state.active_tab_index)
        self.window.recent_files = list(loaded_state.recent_files)

        cleaned_recents = list(loaded_state.recent_files)
        if cleaned_recents != list(raw_recent_files):
            self.restore_recent_files(cleaned_recents)
        else:
            self.window.recent_files = cleaned_recents
        self.update_recent_files_menu()

    def apply_startup_window_state(self):
        if self.window._startup_window_state_applied:
            return

        self.window._startup_window_state_applied = True
        state = self.window.windowState() & ~(Qt.WindowMinimized | Qt.WindowFullScreen)
        if not self.window._startup_geometry_restored:
            state |= Qt.WindowMaximized
        self.window.setWindowState(state)
        ensure_window_fits_available_geometry(self.window)
        self.window._startup_layout_pending = True
        QTimer.singleShot(0, self.window._finalize_startup_layout)
        QTimer.singleShot(150, self.window._finalize_startup_layout)

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
        self.window.recent_files = self._sanitize_recent_files([path])
        if hasattr(self.window.settings, "set_recent_files"):
            self.window.settings.set_recent_files(self.window.recent_files)
        else:
            self._set_value("recent_files", self.window.recent_files)
        self.update_recent_files_menu()

    def restore_recent_files(self, recent_files: List[str]):
        self.window.recent_files = self._sanitize_recent_files(recent_files)
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

    def restore_last_session_path(self) -> str:
        if hasattr(self.window.settings, "last_session_path"):
            return self.window.settings.last_session_path()
        return str(self._value("last_session_path", "") or "")

    def restore_legacy_workbook_path(self) -> str:
        if hasattr(self.window.settings, "legacy_workbook_path"):
            legacy_path = self.window.settings.legacy_workbook_path()
        else:
            legacy_path = str(self._value("last_excel_path", "") or "")
        normalized = self._normalize_path(legacy_path)
        if not normalized or self._is_named_session(normalized):
            return ""
        return normalized

    def restore_database_bootstrap_source_path(self) -> str:
        if hasattr(self.window.settings, "database_bootstrap_source_path"):
            return str(self.window.settings.database_bootstrap_source_path() or "").strip()
        return str(self._value("database_bootstrap_source_path", "") or "").strip()

    def pending_singleton_bootstrap_source_path(self) -> str:
        legacy_path = self.restore_legacy_workbook_path()
        if not legacy_path:
            return ""
        if self.restore_database_bootstrap_source_path():
            return ""
        return legacy_path

    def mark_singleton_bootstrap_completed(self, source_path: str):
        normalized = self._normalize_path(source_path)
        if hasattr(self.window.settings, "set_database_bootstrap_source_path"):
            self.window.settings.set_database_bootstrap_source_path(normalized)
        else:
            self._set_value("database_bootstrap_source_path", normalized)

        if hasattr(self.window.settings, "clear_legacy_workbook_path"):
            self.window.settings.clear_legacy_workbook_path()
        else:
            self._remove("last_excel_path")

    def save_last_session_path(self, path: str):
        self.clear_last_session_path()

    def clear_last_session_path(self):
        if hasattr(self.window.settings, "clear_last_session_path"):
            self.window.settings.clear_last_session_path()
        else:
            self._remove("last_session_path")

    def tcra_form_draft(self) -> dict:
        if hasattr(self.window.settings, "tcra_form_draft"):
            return dict(self.window.settings.tcra_form_draft() or {})
        state = self._value("tcra_form_draft", {})
        return dict(state) if isinstance(state, dict) else {}

    def set_tcra_form_draft(self, state: dict):
        if hasattr(self.window.settings, "set_tcra_form_draft"):
            self.window.settings.set_tcra_form_draft(dict(state or {}))
        else:
            self._set_value("tcra_form_draft", dict(state or {}))

    def clear_tcra_form_draft(self):
        if hasattr(self.window.settings, "clear_tcra_form_draft"):
            self.window.settings.clear_tcra_form_draft()
        else:
            self._remove("tcra_form_draft")


    def preferred_session_dialog_dir(self) -> str:
        current_path = (
            self.window.shell_controller.current_session_path()
            if hasattr(self.window, "shell_controller")
            else str(
                getattr(
                    getattr(self.window, "session_runtime", None),
                    "session_path",
                    getattr(getattr(self.window, "session_runtime", None), "path", ""),
                )
                or ""
            )
        ) or self.restore_last_session_path()
        return resolve_preferred_directory(
            current_path,
            self.restore_database_bootstrap_source_path(),
            self.restore_legacy_workbook_path(),
        )

    def preferred_import_dialog_dir(self) -> str:
        return self.preferred_session_dialog_dir()


    def preferred_export_dir(self) -> str:
        export_dir = ""
        if hasattr(self.window.settings, "last_export_dir"):
            export_dir = self.window.settings.last_export_dir()
        else:
            export_dir = str(self._value("last_export_dir", "") or "")

        return resolve_preferred_directory(export_dir, self.preferred_session_dialog_dir())

    def save_last_export_dir(self, path: str):
        normalized = self._normalize_path(path)
        if not normalized:
            return

        export_dir = normalized if os.path.isdir(normalized) else os.path.dirname(normalized)
        if not export_dir:
            return

        if hasattr(self.window.settings, "set_last_export_dir"):
            self.window.settings.set_last_export_dir(export_dir)
        else:
            self._set_value("last_export_dir", export_dir)

    def tcra_filter_state(self) -> dict:
        if hasattr(self.window.settings, "tcra_filter_state"):
            state = self.window.settings.tcra_filter_state()
        else:
            raw_state = self._value("tcra_filter_state", {})
            state = dict(raw_state) if isinstance(raw_state, dict) else {}
        return dict(state or {})

    def set_tcra_filter_state(self, state: dict):
        clean_state = dict(state or {})
        if hasattr(self.window.settings, "set_tcra_filter_state"):
            self.window.settings.set_tcra_filter_state(clean_state)
        else:
            self._set_value("tcra_filter_state", clean_state)
