from app.services.app_settings import AppSettings


class MemorySettings:
    def __init__(self):
        self._data = {}

    def value(self, key, default=None):
        return self._data.get(key, default)

    def setValue(self, key, value):
        self._data[key] = value

    def remove(self, key):
        self._data.pop(key, None)


def test_app_settings_round_trip_and_defaults():
    settings = AppSettings(MemorySettings())

    assert settings.is_dark_mode() is False
    assert settings.active_tab_index() == 0
    assert settings.recent_files() == []
    assert settings.last_excel_path() == ""
    assert settings.last_export_dir() == ""
    assert settings.map_layer() == "Mapa Claro"
    assert settings.sort_state() == (-1, 0)
    assert settings.window_geometry() is None
    assert settings.operation_history_filter_state() == {}

    settings.set_dark_mode(True)
    settings.set_active_tab_index(2)
    settings.set_recent_files(["a.xlsx", "b.xlsx"])
    settings.set_last_excel_path("a.xlsx")
    settings.set_last_export_dir("C:/exports")
    settings.set_map_layer("Satélite")
    settings.set_sort_state(4, 1)
    settings.set_window_geometry(b"geom")
    settings.set_operation_history_filter_state({"action": "EDIT", "search": "uid-1"})

    assert settings.is_dark_mode() is True
    assert settings.active_tab_index() == 2
    assert settings.recent_files() == ["a.xlsx", "b.xlsx"]
    assert settings.last_excel_path() == "a.xlsx"
    assert settings.last_export_dir() == "C:/exports"
    assert settings.map_layer() == "Satélite"
    assert settings.sort_state() == (4, 1)
    assert settings.window_geometry() == b"geom"
    assert settings.operation_history_filter_state() == {"action": "EDIT", "search": "uid-1"}

    settings.clear_last_excel_path()
    settings.clear_sort_state()

    assert settings.last_excel_path() == ""
    assert settings.sort_state() == (-1, 0)
