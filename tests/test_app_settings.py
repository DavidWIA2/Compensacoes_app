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
    assert settings.last_session_path() == ""
    assert settings.legacy_workbook_path() == ""
    assert settings.database_bootstrap_source_path() == ""
    assert settings.last_export_dir() == ""
    assert settings.map_layer() == "Mapa Claro"
    assert settings.sort_state() == (-1, 0)
    assert settings.window_geometry() is None
    assert settings.operation_history_filter_state() == {}
    assert settings.compensacoes_filter_state() == {}
    assert settings.compensacoes_saved_views() == {}
    assert settings.compensacoes_form_draft() == {}
    assert settings.tcra_filter_state() == {}
    assert settings.tcra_form_draft() == {}

    settings.set_dark_mode(True)
    settings.set_active_tab_index(2)
    settings.set_recent_files(["a.xlsx", "b.xlsx"])
    settings.set_last_session_path("a.xlsx")
    settings.setValue("last_excel_path", "legacy.xlsx")
    settings.set_database_bootstrap_source_path("C:/dados/base.xlsx")
    settings.set_last_export_dir("C:/exports")
    settings.set_map_layer("Satélite")
    settings.set_sort_state(4, 1)
    settings.set_window_geometry(b"geom")
    settings.set_operation_history_filter_state({"action": "EDIT", "search": "uid-1"})
    settings.set_compensacoes_filter_state({"search_text": "gregorio", "quick_filter_mode": "oficios"})
    settings.set_compensacoes_saved_views({"Ofícios": {"quick_filter_mode": "oficios"}})
    settings.set_compensacoes_form_draft({"oficio_processo": "163/23", "caixa": "Ofícios"})
    settings.set_tcra_filter_state({"search_text": "varjao", "quick_filter_mode": "alertas"})
    settings.set_tcra_form_draft({"numero_processo": "26207/2019", "local": "Itamarati"})

    assert settings.is_dark_mode() is True
    assert settings.active_tab_index() == 2
    assert settings.recent_files() == ["a.xlsx", "b.xlsx"]
    assert settings.last_session_path() == "a.xlsx"
    assert settings.legacy_workbook_path() == "legacy.xlsx"
    assert settings.database_bootstrap_source_path() == "C:/dados/base.xlsx"
    assert settings.last_export_dir() == "C:/exports"
    assert settings.map_layer() == "Satélite"
    assert settings.sort_state() == (4, 1)
    assert settings.window_geometry() == b"geom"
    assert settings.operation_history_filter_state() == {"action": "EDIT", "search": "uid-1"}
    assert settings.compensacoes_filter_state() == {"search_text": "gregorio", "quick_filter_mode": "oficios"}
    assert settings.compensacoes_saved_views() == {"Ofícios": {"quick_filter_mode": "oficios"}}
    assert settings.compensacoes_form_draft() == {"oficio_processo": "163/23", "caixa": "Ofícios"}
    assert settings.tcra_filter_state() == {"search_text": "varjao", "quick_filter_mode": "alertas"}
    assert settings.tcra_form_draft() == {"numero_processo": "26207/2019", "local": "Itamarati"}

    settings.clear_last_session_path()
    settings.clear_legacy_workbook_path()
    settings.clear_database_bootstrap_source_path()
    settings.clear_sort_state()
    settings.clear_compensacoes_form_draft()
    settings.clear_tcra_form_draft()

    assert settings.last_session_path() == ""
    assert settings.legacy_workbook_path() == ""
    assert settings.database_bootstrap_source_path() == ""
    assert settings.sort_state() == (-1, 0)
    assert settings.compensacoes_form_draft() == {}
    assert settings.tcra_form_draft() == {}


def test_app_settings_recovers_from_invalid_json_payloads():
    raw = MemorySettings()
    raw.setValue("recent_files", "{invalido")
    raw.setValue("operation_history_filter_state", "{invalido")
    raw.setValue("compensacoes_filter_state", "[1,2,3]")
    raw.setValue("compensacoes_saved_views", "[]")
    raw.setValue("compensacoes_form_draft", "[]")
    raw.setValue("tcra_filter_state", "[1,2,3]")
    raw.setValue("tcra_form_draft", "[]")

    settings = AppSettings(raw)

    assert settings.recent_files() == []
    assert settings.operation_history_filter_state() == {}
    assert settings.compensacoes_filter_state() == {}
    assert settings.compensacoes_saved_views() == {}
    assert settings.compensacoes_form_draft() == {}
    assert settings.tcra_filter_state() == {}
    assert settings.tcra_form_draft() == {}


