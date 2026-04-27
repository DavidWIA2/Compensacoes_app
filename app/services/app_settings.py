import json
from typing import List, Optional, Tuple

from PySide6.QtCore import QSettings

from app.config import APP_SETTINGS_NAME, APP_SETTINGS_ORG, DEFAULT_MAP_LAYER, DEFAULT_THEME_DARK_MODE
from app.utils.logger import get_logger


logger = get_logger("Settings")


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

    def _read_json_list(self, key: str) -> List[str]:
        raw_value = self.value(key)
        if not raw_value:
            return []
        if isinstance(raw_value, list):
            return list(raw_value)
        if isinstance(raw_value, str):
            try:
                decoded = json.loads(raw_value)
            except json.JSONDecodeError as exc:
                logger.warning("Falha ao ler lista em QSettings para '%s': %s", key, exc, exc_info=True)
                return []
            if isinstance(decoded, list):
                return list(decoded)
        logger.warning("Valor inesperado em QSettings para lista '%s': %s", key, type(raw_value).__name__)
        return []

    def _read_mapping(self, key: str) -> dict:
        raw_value = self.value(key, {})
        if isinstance(raw_value, dict):
            return dict(raw_value)
        if isinstance(raw_value, str):
            try:
                decoded = json.loads(raw_value)
            except json.JSONDecodeError as exc:
                logger.warning("Falha ao ler dicionario em QSettings para '%s': %s", key, exc, exc_info=True)
                return {}
            if isinstance(decoded, dict):
                return dict(decoded)
        if raw_value not in ({}, None, ""):
            logger.warning("Valor inesperado em QSettings para dicionario '%s': %s", key, type(raw_value).__name__)
        return {}

    def recent_files(self) -> List[str]:
        return self._read_json_list("recent_files")

    def set_recent_files(self, paths: List[str]):
        self.setValue("recent_files", list(paths))

    def last_session_path(self) -> str:
        return str(self.value("last_session_path", "") or "").strip()

    def set_last_session_path(self, path: str):
        normalized = str(path or "")
        self.setValue("last_session_path", normalized)

    def clear_last_session_path(self):
        self.remove("last_session_path")

    def legacy_workbook_path(self) -> str:
        return str(self.value("last_excel_path", "") or "").strip()

    def clear_legacy_workbook_path(self):
        self.remove("last_excel_path")

    def database_bootstrap_source_path(self) -> str:
        return str(self.value("database_bootstrap_source_path", "") or "").strip()

    def set_database_bootstrap_source_path(self, path: str):
        self.setValue("database_bootstrap_source_path", str(path or "").strip())

    def clear_database_bootstrap_source_path(self):
        self.remove("database_bootstrap_source_path")

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
        return self._read_mapping("operation_history_filter_state")

    def set_operation_history_filter_state(self, state: dict):
        self.setValue("operation_history_filter_state", dict(state or {}))

    def compensacoes_filter_state(self) -> dict:
        return self._read_mapping("compensacoes_filter_state")

    def set_compensacoes_filter_state(self, state: dict):
        self.setValue("compensacoes_filter_state", dict(state or {}))

    def compensacoes_saved_views(self) -> dict:
        return self._read_mapping("compensacoes_saved_views")

    def set_compensacoes_saved_views(self, views: dict):
        self.setValue("compensacoes_saved_views", dict(views or {}))

    def compensacoes_form_draft(self) -> dict:
        return self._read_mapping("compensacoes_form_draft")

    def set_compensacoes_form_draft(self, state: dict):
        self.setValue("compensacoes_form_draft", dict(state or {}))

    def clear_compensacoes_form_draft(self):
        self.remove("compensacoes_form_draft")

    def tcra_filter_state(self) -> dict:
        return self._read_mapping("tcra_filter_state")

    def set_tcra_filter_state(self, state: dict):
        self.setValue("tcra_filter_state", dict(state or {}))

    def tcra_saved_views(self) -> dict:
        return self._read_mapping("tcra_saved_views")

    def set_tcra_saved_views(self, views: dict):
        self.setValue("tcra_saved_views", dict(views or {}))

    def tcra_operational_rules(self) -> dict:
        return self._read_mapping("tcra_operational_rules")

    def set_tcra_operational_rules(self, rules: dict):
        self.setValue("tcra_operational_rules", dict(rules or {}))

    def tcra_form_draft(self) -> dict:
        return self._read_mapping("tcra_form_draft")

    def set_tcra_form_draft(self, state: dict):
        self.setValue("tcra_form_draft", dict(state or {}))

    def clear_tcra_form_draft(self):
        self.remove("tcra_form_draft")

    def last_access_environment(self) -> str:
        return str(self.value("last_access_environment", "production") or "production").strip()

    def set_last_access_environment(self, environment: str):
        self.setValue("last_access_environment", str(environment or "production").strip())

    def last_access_email(self) -> str:
        return str(self.value("last_access_email", "") or "").strip()

    def set_last_access_email(self, email: str):
        self.setValue("last_access_email", str(email or "").strip())
