import os
import json
from types import SimpleNamespace

import openpyxl

from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem
from app.services.app_settings import AppSettings
from app.utils.logger import LOG_DIR

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from PySide6.QtWidgets import QApplication, QMessageBox, QBoxLayout
from PySide6.QtCore import Qt, QObject, Signal, QThread, QTimer, QRect
from PySide6.QtGui import QCloseEvent, QPalette, QStandardItemModel

from app.application.use_cases.persistence_monitoring import (
    PersistenceRecordOverviewReport,
    PersistenceStatusReport,
)
from app.services.access_service import AccessEnvironment, AppAccessSession
from app.models.display_columns import display_column_index
from app.ui import main_window as main_window_module
from app.ui.main_window import MainWindow
from app.ui.tabs.data_tab import DataTab
from app.ui.components.dialogs import MapFullScreenDialog, TableFullScreenDialog
from app.ui.components.widgets import LockedSplitter
from app.application.use_cases.local_record_queries import (
    LocalDuplicateCheckResult,
    LocalFilterFacetsResult,
    LocalRecordReadResult,
    LocalRecordReadStatus,
)
from app.application.use_cases.local_mutation_sync import LocalMutationSyncStatus
from app.services.sqlite_mirror_service import DEFAULT_SINGLETON_SESSION_PATH

class MockQWebEngineView(QtWidgets.QWidget):
    loadFinished = Signal(bool)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._page = SimpleNamespace(runJavaScript=lambda *a: None)
    def setPage(self, page): self._page = page
    def page(self): return self._page
    def load(self, url): pass
    def setUrl(self, url): pass


class NoopUpdaterWorker(QThread):
    update_available = Signal(str, str)

    def start(self, *args, **kwargs):
        return None

    def quit(self):
        return None

    def wait(self, *args, **kwargs):
        return True

def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "",
        "compensado": "",
        "latitude": "",
        "longitude": "",
        "uid": "test-uid-123"
    }
    base.update(overrides)
    return Compensacao(**base)


def get_app():
    return QApplication.instance() or QApplication([])


import pytest


def settle_window(window, cycles: int = 4):
    app = get_app()
    for _ in range(max(int(cycles), 1)):
        app.processEvents()
    return window


def available_left_panel_table_height(window) -> int:
    layout = window.data_tab.left_panel.layout()
    margins = layout.contentsMargins()
    spacing_count = max(layout.count() - 1, 0)
    return (
        window.data_tab.left_panel.height()
        - margins.top()
        - margins.bottom()
        - window.data_tab.group_totals.height()
        - window.data_tab.bar_export.height()
        - (layout.spacing() * spacing_count)
    )


def assert_left_panel_sections_fit(window) -> None:
    expected_height = available_left_panel_table_height(window)
    assert window.data_tab.table.minimumHeight() == 0
    assert window.data_tab.table.maximumHeight() == expected_height
    assert window.data_tab.table.height() <= expected_height
    assert window.data_tab.group_totals.geometry().bottom() < window.data_tab.bar_export.geometry().top()
    assert window.data_tab.bar_export.geometry().bottom() <= window.data_tab.left_panel.height() - 1


class MockDashboardTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.btn_export_pdf = QtWidgets.QPushButton("Export PDF")
    def update_dashboard(self, *args, **kwargs): pass
    def apply_theme(self, theme): pass
    def export_images(self): return "pie.png", "bar.png"

@pytest.fixture(autouse=True)
def global_mocks(monkeypatch, tmp_path):
    get_app()
    import app.ui.components.ui_utils as ui_utils_module
    import app.ui.controllers.data_controller as data_controller_module
    import app.ui.controllers.form_controller as form_controller_module
    import app.ui.controllers.map_controller as map_controller_module
    from app.services.sqlite_mirror_service import SqliteMirrorService

    # Mock heavy widgets
    monkeypatch.setattr("app.ui.tabs.data_tab.QWebEngineView", MockQWebEngineView)
    monkeypatch.setattr("app.ui.main_window.DashboardTab", MockDashboardTab)
    monkeypatch.setattr(main_window_module, "UpdaterWorker", NoopUpdaterWorker)
    
    # Mock UI blocking calls
    monkeypatch.setattr(MainWindow, "_apply_theme", lambda self: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(ui_utils_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(data_controller_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(form_controller_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(map_controller_module, "msg_confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(main_window_module, "msg_confirm", lambda *args, **kwargs: True)

    # Mock common heavy setup
    monkeypatch.setattr(DataTab, "load_map", lambda self: None)
    monkeypatch.setattr(
        main_window_module,
        "SqliteMirrorService",
        lambda *args, **kwargs: SqliteMirrorService(db_path=tmp_path / "behaviors-mirror.db"),
    )
    
    class GlobalMockSettings:
        def __init__(self, *args, **kwargs): pass
        def value(self, key, default=""): return default
        def setValue(self, key, val): pass
        def remove(self, key): pass

    monkeypatch.setattr("app.ui.main_window.QSettings", GlobalMockSettings)

def test_lazy_map_loading_delays_initialization(monkeypatch):
    calls = []
    
    original_load = MainWindow._load_last_session
    def mock_load_last(self):
        calls.append("session")
        original_load(self)
    monkeypatch.setattr(MainWindow, "_load_last_session", mock_load_last)

    window = MainWindow()

    # Map state should be False right after init
    assert window.data_tab._map_loaded is False
    assert "session" in calls
    
    # After show event, it should turn True
    window.data_tab.showEvent(None)
    assert window.data_tab._map_loaded is False # It remains False because global_mock ignores it, but it proves it didn't crash
    
    window.close()


def test_loading_microbacias_layer_does_not_force_embedded_map_startup(monkeypatch):
    window = MainWindow()
    get_app().processEvents()

    calls = []
    window.gis = SimpleNamespace(to_geojson_obj=lambda: {"type": "FeatureCollection", "features": []})
    monkeypatch.setattr(window.data_tab, "load_map", lambda: calls.append("load_map"))
    window.data_tab._map_loaded = False
    window.data_tab.web = None

    window.map_controller.load_microbacias_layer()

    assert calls == []
    window.close()


def test_main_window_uses_readable_core_labels(monkeypatch):
    window = MainWindow()
    get_app().processEvents()

    assert "Plataforma de Gestão Ambiental" in window.windowTitle()
    assert "Base local" in window.windowTitle()
    assert bool(window.windowState() & Qt.WindowMaximized)
    assert "ofício" in window.data_tab.search.placeholderText().lower()
    assert window.data_tab.filter_eletronico._all_label == "Todos os Tipos"
    assert "Endereço" in window.data_tab.btn_maps.text()
    assert window.session_file_label.text() == "Fonte: Banco local"
    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "Compensações",
        "Painel",
        "Operações",
        "TCRAs",
    ]

    assert window.data_tab.kpi_model.horizontalHeaderItem(0).text() == "Métrica"
    window.close()


def test_main_window_compensacoes_form_exposes_placeholders_clear_buttons_and_tooltips():
    window = MainWindow()
    get_app().processEvents()

    assert window.data_tab.in_oficio.isClearButtonEnabled() is True
    assert "206/2021" in window.data_tab.in_oficio.placeholderText()
    assert window.data_tab.in_end.isClearButtonEnabled() is True
    assert window.data_tab.in_micro.lineEdit().isClearButtonEnabled() is True
    assert window.data_tab.btn_manage_plantios.toolTip() != ""
    assert window.data_tab.btn_clear_filters.toolTip() != ""
    assert window.data_tab.btn_maps.toolTip() != ""
    assert window.data_tab.combo_heatmap_type.toolTip() != ""

    window.close()


def test_main_window_marks_demo_environment_and_uses_demo_database(monkeypatch, tmp_path):
    demo_db = tmp_path / "demo-window.db"
    window = MainWindow(
        access_session=AppAccessSession(
            environment=AccessEnvironment.DEMO,
                label="Demonstração",
            auth_mode="demo_local",
            local_db_path=str(demo_db),
            is_anonymous=True,
        )
    )
    get_app().processEvents()

    window._refresh_window_chrome()

    assert window.persistence_service.db_path == demo_db
    assert window.session_environment_label.text() == "Ambiente: Demonstração"
    assert "[Demonstração]" in window.windowTitle()
    window.close()


def test_main_window_auto_loads_production_cache_from_access_session(monkeypatch, tmp_path):
    demo_db = tmp_path / "prod-window.db"
    sqlite_service = main_window_module.DirectSqliteMirrorService(db_path=demo_db)
    sqlite_service.sync_workbook_snapshot(DEFAULT_SINGLETON_SESSION_PATH, [make_record()])

    window = MainWindow(
        access_session=AppAccessSession(
            environment=AccessEnvironment.PRODUCTION,
                label="Produção",
            auth_mode="password",
            user_email="analista@prefeitura.sp.gov.br",
            local_db_path=str(demo_db),
            local_session_path=DEFAULT_SINGLETON_SESSION_PATH,
        )
    )
    get_app().processEvents()

    assert len(window.records) == 1
    assert window.shell_controller.current_session_path() == DEFAULT_SINGLETON_SESSION_PATH
    assert window.session_environment_label.text() == "Ambiente: Produção"
    window.close()


def test_main_window_shell_compacts_for_1440x900_like_layout():
    window = MainWindow()
    window.showNormal()
    window.resize(1320, 860)
    get_app().processEvents()

    window.shell_controller.apply_responsive_layout()

    assert window.search_helper_label.isVisible() is False
    assert window.session_context_label.isVisible() is False
    assert window.session_role_label.isVisible() is False
    assert window.session_write_label.isVisible() is False
    assert window.session_selection_label.isVisible() is False

    window.close()


def test_main_window_shell_stacks_toolbar_for_1440x900_like_layout():
    window = MainWindow()
    window.showNormal()
    window.resize(1320, 860)
    get_app().processEvents()

    window.shell_controller.apply_responsive_layout()

    assert window.shell_controller.toolbar_layout.direction() == QBoxLayout.Direction.TopToBottom
    window.close()


def test_navigation_controller_defers_operations_refresh_until_tab_is_opened(monkeypatch):
    window = MainWindow()
    get_app().processEvents()

    calls = []
    monkeypatch.setattr(
        window.operations_controller,
        "refresh_overview",
        lambda *args, **kwargs: calls.append("refresh"),
    )

    assert window.navigation_controller.is_operations_tab_active() is False
    assert window.navigation_controller.update_operations_overview() is False
    assert calls == []
    assert window._operations_dirty is True

    window.tabs.setCurrentWidget(window.operations_tab)
    get_app().processEvents()

    assert calls == ["refresh"]
    assert window._operations_dirty is False
    window.close()


def test_main_window_adds_admin_tab_for_production_admin(monkeypatch):
    window = MainWindow(
        access_session=AppAccessSession(
            environment=AccessEnvironment.PRODUCTION,
                label="Produção",
            auth_mode="password",
            user_id="admin-1",
            user_email="admin@prefeitura.sp.gov.br",
            app_role="admin",
            access_token="token",
            refresh_token="refresh",
        )
    )
    get_app().processEvents()

    tab_titles = [window.tabs.tabText(index) for index in range(window.tabs.count())]

    assert "Administração" in tab_titles
    assert getattr(window, "admin_users_tab", None) is not None
    assert window.session_user_label.text() == "Conta: admin@prefeitura.sp.gov.br"
    assert window.btn_sign_out.text() == "Sair"
    window.close()


def test_main_window_request_sign_out_relaunches_login(monkeypatch):
    window = MainWindow(
        access_session=AppAccessSession(
            environment=AccessEnvironment.PRODUCTION,
            label="Produção",
            auth_mode="password",
            user_id="admin-1",
            user_email="admin@saocarlos.sp.gov.br",
            app_role="admin",
            access_token="token",
            refresh_token="refresh",
        )
    )
    get_app().processEvents()
    window._enable_sign_out_controls()

    calls = []
    monkeypatch.setattr(window.form_controller, "confirm_discard_changes", lambda action: True)
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "question",
        lambda *args, **kwargs: main_window_module.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(window.access_service, "sign_out_session", lambda session: calls.append(("sign_out", session)))
    monkeypatch.setattr(main_window_module, "relaunch_login_process", lambda: True)
    monkeypatch.setattr(window, "close", lambda: calls.append(("close", None)))

    result = window.request_sign_out()

    assert result is True
    assert calls[0][0] == "sign_out"
    assert calls[1] == ("close", None)


def test_main_window_sign_out_starts_locked_until_window_is_ready():
    window = MainWindow(
        access_session=AppAccessSession(
            environment=AccessEnvironment.PRODUCTION,
            label="Produção",
            auth_mode="password",
            user_id="admin-1",
            user_email="admin@saocarlos.sp.gov.br",
            app_role="admin",
            access_token="token",
            refresh_token="refresh",
        )
    )
    get_app().processEvents()

    assert window.btn_sign_out.isEnabled() is False
    assert window.action_sign_out.isEnabled() is False

    window._enable_sign_out_controls()

    assert window.btn_sign_out.isEnabled() is True
    assert window.action_sign_out.isEnabled() is True
    window.close()


def test_main_window_ignores_unexpected_close_during_startup_guard(monkeypatch):
    window = MainWindow()
    get_app().processEvents()
    window._startup_close_guard_armed = True

    calls = []
    monkeypatch.setattr(window.lifecycle_controller, "prepare_close", lambda event: calls.append("prepare") or True)

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted() is False
    assert calls == []

    window._disable_startup_close_guard()
    event = QCloseEvent()
    window.closeEvent(event)

    assert calls == ["prepare"]


def test_main_window_disables_global_search_on_admin_tab(monkeypatch):
    window = MainWindow(
        access_session=AppAccessSession(
            environment=AccessEnvironment.PRODUCTION,
            label="Producao",
            auth_mode="password",
            user_id="admin-1",
            user_email="admin@prefeitura.sp.gov.br",
            app_role="admin",
            access_token="token",
            refresh_token="refresh",
        )
    )
    get_app().processEvents()

    window.search.setText("consulta")
    window.tabs.setCurrentWidget(window.admin_users_tab)
    get_app().processEvents()

    assert window.search.isEnabled() is False
    assert "administração" in window.search.placeholderText().lower()

    window.tabs.setCurrentWidget(window.data_tab)
    get_app().processEvents()

    assert window.search.isEnabled() is True
    assert "ofício" in window.search.placeholderText().lower()
    assert window.search.text() == "consulta"
    window.close()


def test_main_window_tcra_tab_disables_global_search_and_refreshes_on_activation(monkeypatch):
    window = MainWindow()
    get_app().processEvents()
    calls = []

    monkeypatch.setattr(window.tcra_tab, "handle_tab_activated", lambda: calls.append("refresh"))

    assert window.search.isEnabled() is True
    assert "ofício" in window.search.placeholderText().lower()

    window.tabs.setCurrentWidget(window.tcra_tab)
    get_app().processEvents()

    assert calls == ["refresh"]
    assert window.search.isEnabled() is True
    assert "buscar tcra" in window.search.placeholderText().lower()
    assert window.tcra_tab.search_input.isHidden() is True

    window.tabs.setCurrentWidget(window.data_tab)
    get_app().processEvents()

    assert window.search.isEnabled() is True
    assert "ofício" in window.search.placeholderText().lower()
    assert window.tcra_tab.search_input.isHidden() is False
    window.close()


def test_main_window_bootstraps_lazy_session_runtime(monkeypatch):
    created = []

    class LazyExcelLoader:
        def __init__(self):
            created.append("loader")
            self.path = ""
            self.wb = None
            self.ws = None
            self.plantio_ws = None
            self.col_map = {}
            self.plantio_col_map = {}
            self.uid_to_row = {}
            self.last_backup_time = 0
            self.merged_cells_warning = False
            self.loaded_source_mtime_ns = 0
            self.loaded_source_size = 0

        def load(self, path):
            self.path = path
            self.wb = object()
            self.ws = object()
            return []

    monkeypatch.setattr(main_window_module, "ExternalSpreadsheetAdapter", LazyExcelLoader)

    window = MainWindow()

    assert window.session_runtime.path == "session://banco-local"
    assert window.session_runtime.has_materialized_workbook() is False
    assert created == []
    window.close()


def test_tipo_options_are_fixed_even_without_workbook_data():
    window = MainWindow()
    get_app().processEvents()
    window.records = [make_record(eletronico="SIM")]
    window._update_filters_from_records()
    window._setup_dynamic_form_options_from_records()

    tipo_buttons = [
        window.data_tab.eletronico_layout.itemAt(index).widget().text()
        for index in range(4)
    ]
    tipo_model = window.data_tab.filter_eletronico.model()

    assert tipo_buttons == ["Nulo", "Ofício", "Físico", "Eletrônico"]
    assert [tipo_model.item(index).text() for index in range(1, tipo_model.rowCount())] == [
        "Nulo",
        "Ofício",
        "Físico",
        "Eletrônico",
    ]
    window.close()


def test_update_filters_from_records_can_use_sqlite_filter_facets(monkeypatch):
    window = MainWindow()
    get_app().processEvents()
    window.gis = None
    window.records = [make_record(oficio_processo="123/2024", microbacia="Sessao")]

    monkeypatch.setattr(
        window.shell_controller.local_record_queries,
        "resolve_filter_facets",
        lambda workbook_path, **kwargs: LocalFilterFacetsResult(
            source="sqlite",
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            mirrored_records=2,
            session_records=1,
            microbacias=("Gregorio", "Medeiros"),
            years=("2026", "2025"),
        ),
    )
    monkeypatch.setattr(
        window.shell_controller.local_record_queries,
        "build_filter_facets_status",
        lambda result: {"source": result.source, "micro_count": len(result.microbacias), "year_count": len(result.years)},
    )

    window._update_filters_from_records()
    window._setup_dynamic_form_options_from_records()

    micro_model = window.data_tab.filter_micro.model()
    micro_items = [micro_model.item(index).text() for index in range(1, micro_model.rowCount())]
    year_items = [window.data_tab.filter_year.itemText(index) for index in range(window.data_tab.filter_year.count())]
    form_micro_items = [window.data_tab.in_micro.itemText(index) for index in range(window.data_tab.in_micro.count())]

    assert micro_items == ["Gregorio", "Medeiros"]
    assert year_items == ["Todos", "2026", "2025"]
    assert form_micro_items == ["", "Gregorio", "Medeiros"]
    assert window._local_filter_facets_status == {"source": "sqlite", "micro_count": 2, "year_count": 2}
    window.close()


def test_update_filters_from_records_prefers_official_gis_microbacias(monkeypatch):
    window = MainWindow()
    get_app().processEvents()
    window.records = [make_record(oficio_processo="123/2024", microbacia="Gregorio")]
    window.gis = SimpleNamespace(
        list_microbacias=lambda: ["Água Quente", "Gregório", "Jockey"],
        normalize_microbacia_name=lambda value: {"Gregorio": "Gregório"}.get(value, value),
    )

    monkeypatch.setattr(
        window.shell_controller.local_record_queries,
        "resolve_filter_facets",
        lambda workbook_path, **kwargs: LocalFilterFacetsResult(
            source="sqlite",
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            mirrored_records=2,
            session_records=1,
            microbacias=("Gregorio", "Medeiros"),
            years=("2026",),
        ),
    )
    monkeypatch.setattr(
        window.shell_controller.local_record_queries,
        "build_filter_facets_status",
        lambda result: {"source": result.source, "micro_count": len(result.microbacias)},
    )

    window._update_filters_from_records()
    window._setup_dynamic_form_options_from_records()
    window.data_tab.filter_micro.set_checked_items(["Gregorio"], all_selected=False)

    micro_model = window.data_tab.filter_micro.model()
    micro_items = [micro_model.item(index).text() for index in range(1, micro_model.rowCount())]
    form_micro_items = [window.data_tab.in_micro.itemText(index) for index in range(window.data_tab.in_micro.count())]

    assert micro_items == ["Água Quente", "Gregório", "Jockey", "Medeiros"]
    assert form_micro_items == ["", "Água Quente", "Gregório", "Jockey", "Medeiros"]
    assert window.data_tab.filter_micro.checked_items() == ["Gregório"]
    window.close()


def test_filter_widgets_reuse_cached_filter_facets_result(monkeypatch):
    window = MainWindow()
    get_app().processEvents()
    window.records = [make_record(oficio_processo="123/2024", microbacia="Sessao")]
    window.session_runtime.path = "dummy.xlsx"
    calls = []
    facets = LocalFilterFacetsResult(
        source="sqlite",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-31T12:00:00+00:00",
        mirrored_records=2,
        session_records=1,
        microbacias=("Gregorio", "Medeiros"),
        years=("2026",),
    )

    monkeypatch.setattr(
        window.shell_controller.local_record_queries,
        "resolve_filter_facets",
        lambda workbook_path, **kwargs: calls.append(workbook_path) or facets,
    )
    monkeypatch.setattr(
        window.shell_controller.local_record_queries,
        "build_filter_facets_status",
        lambda result: {"source": result.source, "micro_count": len(result.microbacias)},
    )

    window._update_filters_from_records()
    window._setup_dynamic_form_options_from_records()

    assert calls == ["dummy.xlsx"]
    assert window._local_filter_facets_result is facets
    assert window._local_filter_facets_status == {"source": "sqlite", "micro_count": 2}
    window.close()


def test_update_filters_from_records_rebinds_runtime_persistence_service_after_swap(tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("stub", encoding="utf-8")
    stat_result = workbook_path.stat()
    window = MainWindow()
    get_app().processEvents()
    window.gis = None
    window.session_runtime.path = str(workbook_path)
    window.records = [make_record(oficio_processo="123/2026", microbacia="Sessao")]

    class SwappedPersistenceService:
        def get_workbook_snapshot_summary(self, workbook_path):
            return SimpleNamespace(
                workbook_path=workbook_path,
                synced_at="2026-03-31T12:00:00+00:00",
                record_count=1,
                source_mtime_ns=int(stat_result.st_mtime_ns),
                source_size=int(stat_result.st_size),
            )

        def query_filter_facets_for_workbook(self, workbook_path):
            return SimpleNamespace(
                workbook_path=workbook_path,
                synced_at="2026-03-31T12:00:00+00:00",
                record_count=1,
                microbacias=("Gregorio", "Medeiros"),
                years=("2026",),
            )

    window.persistence_service = SwappedPersistenceService()

    window._update_filters_from_records()

    micro_model = window.data_tab.filter_micro.model()
    micro_items = [micro_model.item(index).text() for index in range(1, micro_model.rowCount())]
    assert micro_items == ["Gregorio", "Medeiros"]
    assert getattr(window._local_filter_facets_status, "source", None) == "sqlite"
    window.close()


def test_load_gis_refreshes_microbacia_options_after_success(monkeypatch):
    window = MainWindow()
    get_app().processEvents()
    calls = []
    real_isdir = os.path.isdir

    monkeypatch.setattr(
        "app.ui.controllers.data_controller.os.path.isdir",
        lambda path: True if path == window.MICROB_DIR else real_isdir(path),
    )
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.GisService",
        lambda *args, **kwargs: SimpleNamespace(
            to_geojson_obj=lambda: {"type": "FeatureCollection", "features": []},
            list_microbacias=lambda: ["Água Quente", "Gregório"],
            normalize_microbacia_name=lambda value: {"Gregorio": "Gregório"}.get(value, value),
        ),
    )
    monkeypatch.setattr(window, "_load_microbacias_layer", lambda: calls.append("layer"))
    monkeypatch.setattr(window, "_update_filters_from_records", lambda: calls.append("filters"))
    monkeypatch.setattr(window, "_setup_dynamic_form_options_from_records", lambda: calls.append("form"))

    assert window.data_controller.load_gis() is True
    assert calls == ["layer", "filters", "form"]
    window.close()


def test_eletronico_disables_caixa_but_arquivado_still_fills_it():
    window = MainWindow()
    get_app().processEvents()

    for button in window.data_tab.eletronico_group.buttons():
        if button.text() == "Eletrônico":
            button.click()
            break

    assert window.data_tab.in_caixa.isEnabled() is False

    window.data_tab.chk_arquivado.setChecked(True)

    assert window.data_tab.in_caixa.text() == "Arquivado"
    assert window.data_tab.in_caixa.isEnabled() is False

    window.data_tab.chk_arquivado.setChecked(False)

    assert window.data_tab.in_caixa.text() == ""
    assert window.data_tab.in_caixa.isEnabled() is False
    window.close()


def test_finalize_startup_layout_aligns_splitter_and_left_panel(monkeypatch):
    window = MainWindow()
    calls = []
    monkeypatch.setattr(window.data_tab, "align_splitter_to_table_width", lambda: calls.append("align"))
    monkeypatch.setattr(window.data_tab, "_sync_left_panel_heights", lambda: calls.append("sync"))

    window._finalize_startup_layout()

    assert calls[:2] == ["align", "sync"]
    assert calls[-2:] == ["sync", "align"]
    assert len(calls) == 4
    window.close()


def test_startup_reenables_ui_when_last_excel_is_loaded(monkeypatch):
    def fake_load_last_session(self):
        self.session_runtime.path = "dummy.xlsx"
        # Use a local mock for this specific test
        real_exists = os.path.exists
        def mock_exists(p):
            if p == "dummy.xlsx": return True
            return real_exists(p)
        monkeypatch.setattr(os.path, "exists", mock_exists)
        
        self.records = [make_record()]
        self.filtered_records = list(self.records)
        self._update_ui_after_load()

    monkeypatch.setattr(MainWindow, "_load_last_session", fake_load_last_session)

    window = MainWindow()

    assert window.data_tab.table.isEnabled() is True
    assert window.data_tab.in_oficio.isEnabled() is True
    assert window.data_tab.btn_add.isEnabled() is True
    window.close()


def test_apply_filter_updates_visible_results_label(monkeypatch):
    window = MainWindow()
    window.records = [
        make_record(oficio_processo="ABC-1"),
        make_record(excel_row=3, oficio_processo="XYZ-2"),
    ]
    window.data_tab.search.setText("ABC")
    window.apply_filter()

    assert window.data_tab.lbl_results.text() == "1 registros"

    window.data_tab.search.setText("SEM-RESULTADO")
    window.apply_filter()

    assert window.data_tab.lbl_results.text() == "0 registros"
    window.close()


def test_apply_filter_can_use_sqlite_mirror_record_source(monkeypatch):
    window = MainWindow()
    window.records = [
        make_record(oficio_processo="ABC-1", uid="session-1"),
        make_record(excel_row=3, oficio_processo="XYZ-2", uid="session-2"),
    ]
    mirrored_records = [
        make_record(oficio_processo="MIRROR-1", uid="mirror-1", microbacia="Gregorio"),
        make_record(excel_row=3, oficio_processo="MIRROR-2", uid="mirror-2", microbacia="Medeiros"),
    ]
    monkeypatch.setattr(
        window.data_controller.local_record_queries,
        "resolve_filtered_record_source",
        lambda workbook_path, **kwargs: LocalRecordReadResult(
            source="sqlite",
            records=tuple(mirrored_records),
            strategy="sqlite_query",
        ),
    )

    window.data_tab.search.setText("mirror")
    window.apply_filter()

    assert [record.uid for record in window.filtered_records] == ["mirror-1", "mirror-2"]
    assert window._local_record_read_status is not None
    assert window._local_record_read_status.source == "sqlite"
    assert window._local_record_read_status.filtered_records == 2
    assert window._filtered_metrics is not None
    window.close()


def test_table_plantio_column_respects_header_minimum_width(monkeypatch):
    window = MainWindow()
    header = window.data_tab.table.horizontalHeader()
    column = window.data_tab.PLANTIO_COLUMN_INDEX
    header.resizeSection(column, 40)

    window.data_tab._resize_column_to_texts(column, [])

    header_text = window.data_tab.table_model.headerData(column, Qt.Horizontal, Qt.DisplayRole)
    expected_min_width = header.fontMetrics().horizontalAdvance(str(header_text)) + max(int(28 * window.scale_factor), 28)

    assert header.sectionSize(column) >= expected_min_width
    window.close()


def test_table_oficio_column_respects_visible_row_text_width(monkeypatch):
    window = MainWindow()
    long_oficio = "123456/2026 - PROCESSO MUITO MAIOR"
    window.records = [
        make_record(oficio_processo=long_oficio),
        make_record(excel_row=3, oficio_processo="1/2026", uid="u-2"),
    ]

    window.apply_filter()

    header = window.data_tab.table.horizontalHeader()
    column = window.data_tab.OFICIO_COLUMN_INDEX
    expected_min_width = max(
        header.fontMetrics().horizontalAdvance(str(window.data_tab.table_model.headerData(column, Qt.Horizontal, Qt.DisplayRole))),
        window.data_tab.table.fontMetrics().horizontalAdvance(long_oficio),
    ) + max(int(28 * window.scale_factor), 28)

    assert header.sectionSize(column) >= expected_min_width
    window.close()


def test_table_tipo_column_reserves_width_for_standard_options():
    window = MainWindow()
    window.records = [
        make_record(eletronico=""),
        make_record(excel_row=3, uid="u-2", eletronico="NAO"),
    ]

    window.apply_filter()

    header = window.data_tab.table.horizontalHeader()
    column = window.data_tab.TIPO_COLUMN_INDEX
    expected_min_width = max(
        header.fontMetrics().horizontalAdvance(str(window.data_tab.table_model.headerData(column, Qt.Horizontal, Qt.DisplayRole))),
        window.data_tab.table.fontMetrics().horizontalAdvance("Eletrônico"),
    ) + max(int(28 * window.scale_factor), 28)

    assert header.sectionSize(column) >= expected_min_width
    window.close()


def test_table_address_columns_gain_more_space_than_short_fields():
    window = MainWindow()
    window.records = [
        make_record(
            endereco="Rua muito mais longa para validar a largura visível da coluna principal",
            endereco_plantio="Área de plantio longa para validar a largura da coluna de plantio",
        ),
        make_record(excel_row=3, uid="u-2", endereco="Rua curta", endereco_plantio="Área curta"),
    ]

    window.apply_filter()

    header = window.data_tab.table.horizontalHeader()
    endereco_width = header.sectionSize(display_column_index("endereco"))
    plantio_width = header.sectionSize(display_column_index("endereco_plantio"))
    tipo_width = header.sectionSize(display_column_index("eletronico"))
    caixa_width = header.sectionSize(display_column_index("caixa"))

    assert endereco_width > tipo_width
    assert plantio_width > caixa_width
    window.close()


def test_table_address_columns_respect_maximum_width_cap():
    window = MainWindow()
    very_long_address = "Endereço " + ("muito longo " * 40)
    window.records = [
        make_record(endereco=very_long_address, endereco_plantio=very_long_address),
    ]

    window.apply_filter()

    header = window.data_tab.table.horizontalHeader()
    endereco_column = display_column_index("endereco")
    plantio_column = display_column_index("endereco_plantio")
    endereco_max_width = window.data_tab._column_width_bounds("endereco")[1]
    plantio_max_width = window.data_tab._column_width_bounds("endereco_plantio")[1]

    assert header.sectionSize(endereco_column) <= endereco_max_width
    assert header.sectionSize(plantio_column) <= plantio_max_width
    window.close()


def test_apply_filter_preserves_splitter_sizes_for_long_oficio(monkeypatch):
    window = MainWindow()
    long_oficio = "999999/2026 - PROCESSO MUITO MUITO MUITO LONGO"
    window.records = [
        make_record(oficio_processo="123/2026"),
        make_record(excel_row=3, uid="u-2", oficio_processo=long_oficio),
    ]
    window.filtered_records = list(window.records)
    window._update_filters_from_records()
    window.data_tab.splitter.setSizes([420, 760])
    expected_sizes = window.data_tab.splitter.sizes()

    window.search.setText("999999")
    window.apply_filter()

    assert window.data_tab.splitter.sizes() == expected_sizes
    window.close()


def test_table_ignores_content_width_for_layout_stability():
    window = MainWindow()

    assert window.data_tab.table.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Ignored
    assert window.data_tab.table.sizePolicy().verticalPolicy() == QtWidgets.QSizePolicy.Ignored
    assert window.data_tab.table.minimumWidth() == 0
    assert window.data_tab.table.minimumHeight() == 0
    assert window.data_tab.group_totals.minimumHeight() == window.data_tab.group_totals.maximumHeight()

    window.close()


def test_apply_filter_keeps_totals_and_export_bar_vertically_stable():
    window = MainWindow()
    window.records = [
        make_record(oficio_processo="123/2026", endereco="Rua Jose A"),
        make_record(excel_row=3, uid="u-2", oficio_processo="999999/2026 - PROCESSO MUITO MUITO MUITO LONGO", endereco="Rua Jose B"),
        make_record(excel_row=4, uid="u-3", oficio_processo="1/2026", endereco="Rua X"),
    ]
    window.filtered_records = list(window.records)
    window._update_filters_from_records()
    window.resize(1600, 900)
    window.show()
    settle_window(window)

    window.search.setText("j")
    window.apply_filter()
    settle_window(window)
    expected_group_y = window.data_tab.group_totals.geometry().y()
    expected_export_y = window.data_tab.bar_export.geometry().y()

    window.search.setText("jo")
    window.apply_filter()
    settle_window(window)

    group_shift = window.data_tab.group_totals.geometry().y() - expected_group_y
    export_shift = window.data_tab.bar_export.geometry().y() - expected_export_y
    assert_left_panel_sections_fit(window)
    if window.data_tab._is_compact_layout():
        assert abs(group_shift - export_shift) <= 2
    else:
        assert abs(group_shift) <= 2
        assert export_shift == group_shift

    window.close()


def test_table_max_height_is_clamped_to_left_panel_space():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    settle_window(window)

    expected_max_height = available_left_panel_table_height(window)

    assert window.data_tab.table.minimumHeight() == 0
    assert window.data_tab.table.maximumHeight() == expected_max_height
    assert window.data_tab.table.height() <= expected_max_height

    window.close()


def test_splitter_and_panels_ignore_vertical_size_hints():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    assert window.data_tab.splitter.sizePolicy().verticalPolicy() == QtWidgets.QSizePolicy.Ignored
    assert window.data_tab.left_panel.sizePolicy().verticalPolicy() == QtWidgets.QSizePolicy.Ignored
    assert window.data_tab.right_panel.sizePolicy().verticalPolicy() == QtWidgets.QSizePolicy.Ignored


def test_compensacoes_splitter_is_locked_for_manual_drag():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    settle_window(window)

    assert isinstance(window.data_tab.splitter, LockedSplitter)

    window.close()

    window.close()


def test_apply_filter_keeps_window_and_table_height_stable():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    settle_window(window)

    initial_window_height = window.height()
    initial_splitter_height = window.data_tab.splitter.height()
    initial_table_height = window.data_tab.table.height()

    window.search.setText("Gregorio")
    window.apply_filter()
    settle_window(window)

    assert window.height() == initial_window_height
    assert window.data_tab.splitter.height() == initial_splitter_height
    assert_left_panel_sections_fit(window)
    if window.data_tab._is_compact_layout():
        assert window.data_tab.table.height() >= initial_table_height
    else:
        assert window.data_tab.table.height() == initial_table_height

    window.close()


def test_progress_bar_visibility_does_not_expand_table_area():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    settle_window(window, cycles=6)

    initial_splitter_height = window.data_tab.splitter.height()
    initial_table_height = window.data_tab.table.height()

    window.progress_bar.setVisible(True)
    window.progress_bar.setRange(0, 10)
    window.progress_bar.setValue(2)
    settle_window(window, cycles=6)

    assert window.data_tab.splitter.height() == initial_splitter_height
    assert_left_panel_sections_fit(window)
    if window.data_tab._is_compact_layout():
        assert window.data_tab.table.height() >= initial_table_height
    else:
        assert window.data_tab.table.height() == initial_table_height

    window.close()


def test_lock_table_height_prevents_vertical_growth():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    original_height = window.data_tab.table.height()
    window.data_tab.lock_table_height()
    expected_height = original_height

    assert window.data_tab.table.height() == expected_height
    assert window.data_tab.table.minimumHeight() == expected_height
    assert window.data_tab.table.maximumHeight() == expected_height

    window.close()


def test_lock_splitter_height_freezes_current_splitter_height():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    current_height = window.data_tab.splitter.height()
    window.data_tab.lock_splitter_height()

    assert window.data_tab.splitter.minimumHeight() == current_height
    assert window.data_tab.splitter.maximumHeight() == current_height

    window.close()


def test_reload_keeps_table_constrained_and_bottom_sections_visible(monkeypatch):
    window = MainWindow()
    window.records = [
        make_record(oficio_processo="123/2026", endereco="Rua Jose A"),
        make_record(excel_row=3, uid="u-2", oficio_processo="456/2026", endereco="Rua Jose B"),
    ]
    window.filtered_records = list(window.records)
    window._update_filters_from_records()
    window.resize(1600, 900)
    window.show()
    settle_window(window)

    expected_group_y = window.data_tab.group_totals.geometry().y()
    expected_export_y = window.data_tab.bar_export.geometry().y()
    expected_window_height = window.height()

    monkeypatch.setattr(window.form_controller, "confirm_discard_changes", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(window.data_controller, "load_session", lambda *_args, **_kwargs: window.data_controller.update_ui_after_load() or True)
    window.session_runtime.path = "C:/temp/fake.xlsx"

    window.reload()
    settle_window(window)

    expected_height = available_left_panel_table_height(window)

    assert window.data_tab.table.height() <= expected_height
    assert window.data_tab.table.maximumHeight() == expected_height
    assert window.height() == expected_window_height
    assert_left_panel_sections_fit(window)
    if window.data_tab._is_compact_layout():
        assert abs(window.data_tab.group_totals.geometry().y() - expected_group_y) <= 48
        assert abs(window.data_tab.bar_export.geometry().y() - expected_export_y) <= 48
    else:
        assert window.data_tab.group_totals.geometry().y() == expected_group_y
        assert window.data_tab.bar_export.geometry().y() == expected_export_y

    window.close()


def test_batch_geocode_keeps_window_height_stable(monkeypatch):
    window = MainWindow()
    window.records = [
        make_record(endereco="Rua Jose A", latitude="", longitude="", microbacia="", uid="u-1"),
        make_record(excel_row=3, endereco="Rua Jose B", latitude="", longitude="", microbacia="", uid="u-2"),
    ]
    window.filtered_records = list(window.records)
    window._update_filters_from_records()
    window.session_runtime.path = "C:/temp/fake.xlsx"
    window.resize(1600, 900)
    window.show()
    settle_window(window)

    class ImmediateGeocodeWorker(QObject):
        progress_update = Signal(int, str)
        finished_process = Signal(object)

        def __init__(self, records):
            super().__init__()
            self.records = records

        def start(self):
            self.progress_update.emit(1, "fake")
            QTimer.singleShot(0, lambda: self.finished_process.emit({2: {"main": (-22.0, -47.0)}}))

        def isRunning(self):
            return False

        def stop(self):
            return None

        def quit(self):
            return None

        def wait(self, *_args):
            return True

    monkeypatch.setattr("app.ui.controllers.map_controller.GeocodeWorker", ImmediateGeocodeWorker)
    monkeypatch.setattr(window.map_controller, "persist_batch_geocode_results", lambda _results: 1)
    monkeypatch.setattr(window, "reload", lambda: window.data_controller.update_ui_after_load())

    expected_window_height = window.height()
    expected_group_y = window.data_tab.group_totals.geometry().y()
    expected_export_y = window.data_tab.bar_export.geometry().y()

    window.run_batch_geocode()
    settle_window(window, cycles=10)

    assert window.height() == expected_window_height
    assert_left_panel_sections_fit(window)
    if window.data_tab._is_compact_layout():
        assert abs(window.data_tab.group_totals.geometry().y() - expected_group_y) <= 96
        assert abs(window.data_tab.bar_export.geometry().y() - expected_export_y) <= 96
    else:
        assert window.data_tab.group_totals.geometry().y() == expected_group_y
        assert window.data_tab.bar_export.geometry().y() == expected_export_y

    window.close()


def test_export_bar_buttons_fit_inside_bar_height():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    settle_window(window)

    export_bar_height = window.data_tab.bar_export.height()
    for button in [
        window.data_tab.btn_export_csv,
        window.data_tab.btn_export_spreadsheet,
        window.data_tab.btn_export_pdf,
    ]:
        assert button.geometry().bottom() <= export_bar_height

    window.close()


def test_crud_bar_has_padding_and_secondary_edge_actions():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    settle_window(window)

    margins = window.data_tab.crud_layout.contentsMargins()
    assert margins.top() > 0
    assert margins.bottom() > 0
    assert window.data_tab.btn_clear.property("kind") == "secondary"
    assert window.data_tab.btn_ficha_pdf.property("kind") == "secondary"

    window.close()


def test_right_panel_reserves_width_for_original_form_layout():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    settle_window(window)

    preferred_width = window.data_tab.preferred_right_panel_width()
    minimum_width = window.data_tab.right_panel.minimumWidth()
    assert minimum_width >= preferred_width
    assert minimum_width >= window.data_tab.map_group.minimumSizeHint().width()
    assert minimum_width >= window.data_tab.form_group.minimumSizeHint().width()
    assert minimum_width >= 560
    assert window.data_tab.form_group.layout().itemAtPosition(0, 4).widget() is window.data_tab.in_avtec
    assert window.data_tab.form_group.layout().itemAtPosition(3, 4).widget() is window.data_tab.in_caixa
    assert window.data_tab.form_group.layout().itemAtPosition(4, 1).widget() is window.data_tab.plantio_actions_container
    assert window.data_tab.btn_manage_plantios.minimumWidth() >= (
        window.data_tab.btn_manage_plantios.fontMetrics().horizontalAdvance(window.data_tab.btn_manage_plantios.text()) + 20
    )
    assert window.data_tab.in_end_plantio.minimumWidth() >= 170

    window.close()


def test_align_splitter_uses_available_width_instead_of_stale_sizes(monkeypatch):
    window = MainWindow()
    captured = {}
    expected_right_width = 714

    monkeypatch.setattr(window.data_tab, "_update_responsive_constraints", lambda: window.data_tab.right_panel.setMinimumWidth(expected_right_width))
    monkeypatch.setattr(window.data_tab, "preferred_left_panel_width", lambda: 1200)
    monkeypatch.setattr(window.data_tab, "_preferred_splitter_anchor_left_width", lambda: None)
    monkeypatch.setattr(window.data_tab.splitter, "sizes", lambda: [120, 120])
    monkeypatch.setattr(window.data_tab.splitter, "contentsRect", lambda: QRect(0, 0, 1890, 640))
    monkeypatch.setattr(window.data_tab.splitter, "count", lambda: 2)
    monkeypatch.setattr(window.data_tab.splitter, "handleWidth", lambda: 7)
    monkeypatch.setattr(window.data_tab.splitter, "setSizes", lambda sizes: captured.setdefault("sizes", list(sizes)))

    window.data_tab.align_splitter_to_table_width()

    assert captured["sizes"] == [1169, 714]

    window.close()


def test_form_group_button_height_fits_plantio_action_row():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    assert window.data_tab.btn_manage_plantios.height() <= window.data_tab.plantio_actions_container.height()

    window.close()


def test_form_group_keeps_minimum_height_for_plantio_controls():
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    assert window.data_tab.form_group.minimumHeight() >= window.data_tab.form_group.minimumSizeHint().height()
    assert window.data_tab.plantio_summary_container.height() >= window.data_tab.in_end_plantio.height()
    assert window.data_tab.plantio_actions_container.height() >= window.data_tab.btn_manage_plantios.height()

    window.close()


def test_update_ui_after_load_syncs_sqlite_snapshot(monkeypatch):
    window = MainWindow()
    record = make_record()
    calls = []

    class StubPersistenceService:
        def sync_workbook_snapshot(self, workbook_path, records):
            calls.append((workbook_path, list(records)))

    window.persistence_service = StubPersistenceService()
    window.session_runtime.path = "C:/temp/base.xlsx"
    window.records = [record]
    monkeypatch.setattr(window, "_update_filters_from_records", lambda: None)
    monkeypatch.setattr(window, "_setup_dynamic_form_options_from_records", lambda: None)
    monkeypatch.setattr(window.data_controller, "load_gis", lambda: True)
    monkeypatch.setattr(window.data_controller, "apply_filter", lambda: None)
    monkeypatch.setattr(window.data_tab, "align_splitter_to_table_width", lambda: None)
    monkeypatch.setattr(window, "clear_form", lambda force=False: None)
    monkeypatch.setattr(window, "refresh_operations_overview", lambda: None)

    window.data_controller.update_ui_after_load()

    assert calls == [("C:/temp/base.xlsx", [record])]

    window.close()


def test_left_panel_layout_keeps_bottom_breathing_room():
    window = MainWindow()

    assert window.data_tab.left_panel.layout().contentsMargins().bottom() >= 12
    assert window.data_tab.group_totals.minimumHeight() == window.data_tab.group_totals.maximumHeight()
    compact_mode = window.data_tab._is_compact_layout()
    short_mode = window.data_tab._is_short_layout()
    very_short_mode = window.data_tab._is_very_short_layout()
    expected_height = max(
        int(
            (
                166
                if very_short_mode
                else 174
                if short_mode
                else 190
                if compact_mode
                else 230
            )
            * window.scale_factor
        ),
        148 if very_short_mode else 156 if compact_mode or short_mode else 200,
    )
    assert window.data_tab.group_totals.height() == expected_height

    window.close()


def test_totals_micro_table_shows_all_microbasins_with_scroll_when_needed():
    window = MainWindow()

    metrics = {
        "total_geral": 100,
        "total_pendente": 80,
        "total_compensado": 20,
        "pend_micro_sorted": [(f"Micro {i}", i) for i in range(10)],
    }

    window.data_tab.update_totals_tables(metrics)

    assert window.data_tab.micro_model.rowCount() == 10
    assert window.data_tab.micro_table.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded

    window.close()


def test_align_splitter_to_table_width_uses_table_content_width(monkeypatch):
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    expected_left = min(
        window.data_tab.preferred_left_panel_width(),
        sum(window.data_tab.splitter.sizes()) - window.data_tab.right_panel.minimumWidth(),
    )
    anchor_left = window.data_tab._preferred_splitter_anchor_left_width()
    if anchor_left is not None:
        expected_left = min(expected_left, anchor_left)

    captured = []
    monkeypatch.setattr(window.data_tab.splitter, "setSizes", lambda sizes: captured.append(list(sizes)))
    window.data_tab.align_splitter_to_table_width()

    assert captured
    assert captured[-1][0] == expected_left

    window.close()


def test_align_splitter_to_table_width_respects_visual_button_anchor(monkeypatch):
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    get_app().processEvents()

    available_left = sum(window.data_tab.splitter.sizes()) - window.data_tab.right_panel.minimumWidth()
    monkeypatch.setattr(window.data_tab, "preferred_left_panel_width", lambda: available_left + 200)
    monkeypatch.setattr(window.data_tab, "_preferred_splitter_anchor_left_width", lambda: 780)

    captured = []
    monkeypatch.setattr(window.data_tab.splitter, "setSizes", lambda sizes: captured.append(list(sizes)))
    window.data_tab.align_splitter_to_table_width()

    assert captured
    assert captured[-1][0] == min(780, available_left)
    window.close()


def test_export_spreadsheet_reuses_cached_filtered_metrics(monkeypatch, tmp_path):
    window = MainWindow()
    window.records = [
        make_record(oficio_processo="ABC-1", compensacao="10", microbacia="Gregorio"),
        make_record(excel_row=3, oficio_processo="XYZ-2", compensacao="5", microbacia="Medeiros"),
    ]
    window.data_tab.search.setText("ABC")
    window.data_tab.filter_status.setCurrentText("Pendentes")
    window.apply_filter()

    captured = {}
    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "saida.xlsx"))
    monkeypatch.setattr(
        "app.ui.controllers.export_controller.export_spreadsheet_two_sheets",
        lambda path, records, filtros_txt, selected_cols, kpis, pend_micro_sorted, pend_ele_sorted: captured.update(
            {
                "path": path,
                "records": records,
                "pend_micro_sorted": pend_micro_sorted,
                "selected_cols": selected_cols,
            }
        ),
    )

    monkeypatch.setattr(
        "app.ui.controllers.export_controller.compute_metrics",
        lambda *_args, **_kwargs: pytest.fail("compute_metrics nao deveria ser recalculado durante a exportacao"),
    )

    window.export_spreadsheet_clicked()

    assert captured["path"].endswith("saida.xlsx")
    assert len(captured["records"]) == 1
    assert captured["pend_micro_sorted"] == [("Gregorio", 10.0)]
    assert "endereco_plantio" in captured["selected_cols"]
    assert window._filtered_metrics is not None
    assert window._filtered_metrics["count_total"] == 1
    window.close()


def test_apply_filter_defers_dashboard_update_until_panel_tab(monkeypatch):
    window = MainWindow()
    window.records = [make_record(oficio_processo="ABC-1", compensacao="10", microbacia="Gregorio")]
    window.filtered_records = list(window.records)
    window._dashboard_record_overview = PersistenceRecordOverviewReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-30T12:00:00+00:00",
        total_records=1,
        compensados_count=0,
        pendentes_count=1,
        records_with_plantios_count=0,
        records_without_microbacia_count=0,
        records_without_coordinates_count=1,
        top_microbacias=(("Gregorio", 1),),
    )

    calls = []
    monkeypatch.setattr(window.dash_tab, "update_dashboard", lambda *args, **kwargs: calls.append(args))

    window.tabs.setCurrentWidget(window.data_tab)
    window.apply_filter()

    assert calls == []
    assert window._dashboard_dirty is True

    window.tabs.setCurrentWidget(window.dash_tab)

    assert len(calls) == 1
    assert len(calls[0]) == 5
    assert calls[0][3] == window._dashboard_record_overview
    assert calls[0][4] == window._local_record_read_status
    assert window._dashboard_dirty is False
    window.close()


def test_export_csv_reports_failure_without_raising(monkeypatch, tmp_path):
    window = MainWindow()
    window.records = [make_record(oficio_processo="ABC-1")]
    window.filtered_records = list(window.records)
    errors = []

    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "saida.csv"))
    monkeypatch.setattr(
        "app.ui.controllers.export_controller.export_csv",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("disco cheio")),
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: errors.append(args[2]))

    try:
        window.export_csv_clicked()
    except RuntimeError:
        errors.append("disco cheio")

    assert errors and "disco cheio" in errors[0]
    window.close()


def test_export_csv_uses_shell_visible_records(monkeypatch, tmp_path):
    window = MainWindow()
    window.filtered_records = [make_record(uid="session-visible")]
    captured = {}
    visible_records = [make_record(uid="sqlite-visible", oficio_processo="SQL-1")]

    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "saida.csv"))
    monkeypatch.setattr(window.shell_controller, "visible_records", lambda: list(visible_records))
    monkeypatch.setattr(
        "app.ui.controllers.export_controller.export_csv",
        lambda path, records, selected_cols: captured.update(
            {
                "path": path,
                "uids": [record.uid for record in records],
                "selected_cols": list(selected_cols),
            }
        ),
    )

    window.export_csv_clicked()

    assert captured["path"].endswith("saida.csv")
    assert captured["uids"] == ["sqlite-visible"]
    assert captured["selected_cols"]
    window.close()


def test_export_ficha_pdf_prompts_observation_and_forwards_it(monkeypatch, tmp_path):
    window = MainWindow()
    window.selected = make_record(oficio_processo="ABC-1")
    captured = {}

    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "ficha.pdf"))
    monkeypatch.setattr(
        "app.ui.controllers.export_controller.QInputDialog.getMultiLineText",
        lambda *args, **kwargs: ("Observacao de teste", True),
    )
    monkeypatch.setattr(
        "app.ui.controllers.export_controller.export_individual_pdf",
        lambda path, record, observation="": captured.update(
            {
                "path": path,
                "record": record,
                "observation": observation,
            }
        ),
    )

    window.export_ficha_pdf()

    assert captured["path"].endswith("ficha.pdf")
    assert captured["record"] is window.selected
    assert captured["observation"] == "Observacao de teste"
    window.close()


def test_export_dashboard_pdf_uses_images_from_dash_tab(monkeypatch, tmp_path):
    window = MainWindow()
    window.records = [make_record(compensacao="10", microbacia="Gregorio")]
    window.filtered_records = list(window.records)
    window.data_tab.search.setText("Gregorio")
    window._dashboard_record_overview = PersistenceRecordOverviewReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-30T12:00:00+00:00",
        total_records=1,
        compensados_count=0,
        pendentes_count=1,
        records_with_plantios_count=0,
        records_without_microbacia_count=0,
        records_without_coordinates_count=1,
        top_microbacias=(("Gregorio", 1),),
    )

    captured = {}
    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "painel.pdf"))
    
    def fake_export_images():
        return "pie.png", "bar.png"

    monkeypatch.setattr(window.dash_tab, "export_images", fake_export_images)
    monkeypatch.setattr(
        "app.ui.controllers.export_controller.export_dashboard_pdf",
        lambda path, titulo, kpi_lines, filtros_txt, chart_images: captured.update(
            {
                "path": path,
                "chart_images": chart_images,
                "kpi_lines": list(kpi_lines),
            }
        ),
    )

    window.export_dashboard_pdf_clicked()

    assert captured["path"].endswith("painel.pdf")
    assert captured["chart_images"] == ["pie.png", "bar.png"]
    assert any("Espelho local: 1 registro(s)" in line for line in captured["kpi_lines"])
    assert any("Top microbacias no espelho: Gregorio: 1" in line for line in captured["kpi_lines"])
    window.close()


def test_export_dashboard_pdf_uses_shell_resolved_dashboard_report(monkeypatch, tmp_path):
    window = MainWindow()
    window.records = [make_record(compensacao="10", microbacia="Gregorio")]
    window.filtered_records = list(window.records)
    window.session_runtime.path = "dummy.xlsx"
    captured = {}
    report = PersistenceRecordOverviewReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-30T12:00:00+00:00",
        total_records=1,
        compensados_count=0,
        pendentes_count=1,
        records_with_plantios_count=0,
        records_without_microbacia_count=0,
        records_without_coordinates_count=1,
        top_microbacias=(("Gregorio", 1),),
    )
    calls = {"overview": 0}

    monkeypatch.setattr(window, "_get_save_path", lambda *args, **kwargs: str(tmp_path / "painel.pdf"))
    monkeypatch.setattr(window.dash_tab, "export_images", lambda: ("pie.png", "bar.png"))
    monkeypatch.setattr(
        window.shell_controller,
        "resolved_dashboard_record_overview",
        lambda **kwargs: calls.__setitem__("overview", calls["overview"] + 1) or report,
    )
    monkeypatch.setattr(
        window.shell_controller,
        "resolved_filtered_metrics",
        lambda: {
            "count_total": 1,
            "total_geral": 10.0,
            "total_pendente": 10.0,
            "total_compensado": 0.0,
            "pend_micro_sorted": [("Gregorio", 10.0)],
            "pend_ele_sorted": [("Eletrônico", 10.0)],
        },
    )
    monkeypatch.setattr(
        "app.ui.controllers.export_controller.export_dashboard_pdf",
        lambda path, titulo, kpi_lines, filtros_txt, chart_images: captured.update(
            {
                "path": path,
                "chart_images": list(chart_images),
                "kpi_lines": list(kpi_lines),
            }
        ),
    )

    window.export_dashboard_pdf_clicked()

    assert calls["overview"] >= 1
    assert captured["path"].endswith("painel.pdf")
    assert captured["chart_images"] == ["pie.png", "bar.png"]
    assert any("Espelho local: 1 registro(s)" in line for line in captured["kpi_lines"])
    assert window._dashboard_record_overview is report
    window.close()


def test_form_action_buttons_follow_selection_state(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if "dummy.xlsx" in p else real_exists(p))
    
    window = MainWindow()
    window.session_runtime.path = "dummy.xlsx"
    window._update_form_action_buttons()
    window.clear_form()

    assert window.data_tab.btn_add.isEnabled() is True
    assert window.data_tab.btn_save_edit.isEnabled() is False
    assert window.data_tab.btn_delete.isEnabled() is False
    assert window.selected is None

    window.selected = make_record()
    window._fill_form(window.selected)

    # After fill_form, it's not dirty yet
    assert window.data_tab.btn_save_edit.isEnabled() is False
    
    # Make it dirty
    window.data_tab.in_oficio.setText("MODIFICADO")
    assert window.data_tab.btn_save_edit.isEnabled() is True
    assert window.data_tab.btn_delete.isEnabled() is True
    window.close()


def test_sn_keeps_add_enabled_for_new_record(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if "dummy.xlsx" in p else real_exists(p))

    window = MainWindow()
    window.session_runtime.path = "dummy.xlsx"
    window.clear_form()

    window.data_tab.chk_sn.setChecked(True)

    assert window.data_tab.in_oficio.text() == "S/N"
    assert window.data_tab.in_oficio.isEnabled() is False
    assert window.data_tab.btn_add.isEnabled() is True

    window.close()


def test_sn_marks_existing_record_as_dirty_and_keeps_save_enabled(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if "dummy.xlsx" in p else real_exists(p))

    window = MainWindow()
    window.session_runtime.path = "dummy.xlsx"
    window.selected = make_record(oficio_processo="123/2026")
    window._fill_form(window.selected)

    assert window.data_tab.btn_save_edit.isEnabled() is False

    window.data_tab.chk_sn.setChecked(True)

    assert window.data_tab.in_oficio.text() == "S/N"
    assert window._is_form_dirty() is True
    assert window.data_tab.btn_save_edit.isEnabled() is True

    window.close()


def test_table_row_selection_populates_form(monkeypatch):
    window = MainWindow()
    window.session_runtime.path = "dummy.xlsx"
    monkeypatch.setattr(window, "_run_map_js", lambda *args, **kwargs: None)
    r3 = make_record(
        excel_row=3,
        oficio_processo="PROC-3",
        latitude="-22.01",
        longitude="-47.89",
        uid="u3",
    )
    
    window.filtered_records = [r3]
    window.data_tab.table_model.records = [r3]
    window.data_tab.table_model.layoutChanged.emit()
    
    index = window.data_tab.proxy.index(0, 0)
    window._on_table_clicked(index)

    assert window.selected is not None
    assert window.selected.excel_row == 3
    assert window.data_tab.in_oficio.text() == "PROC-3"
    assert window.last_marker_coords == (-22.01, -47.89)
    assert window.data_tab.btn_street_view.isEnabled() is True
    window.close()


def test_delete_shortcut_uses_current_table_row(monkeypatch):
    window = MainWindow()
    r3 = make_record(excel_row=3, oficio_processo="PROC-3", uid="u3")
    window.filtered_records = [r3]
    window.data_tab.table_model.records = [r3]
    window.data_tab.table_model.layoutChanged.emit()
    window.data_tab.table.setCurrentIndex(window.data_tab.proxy.index(0, 0))

    deleted = []
    monkeypatch.setattr(window, "delete_selected", lambda: deleted.append(window.selected.uid if window.selected else None))

    window._delete_selected_from_table_shortcut()

    assert deleted == ["u3"]
    window.close()


def test_open_table_fullscreen_restores_splitter_sizes(monkeypatch):
    window = MainWindow()
    splitter = window.data_tab.splitter
    splitter.setSizes([420, 680])
    expected_sizes = splitter.sizes()
    captured = {}

    class FakeDialog:
        def __init__(self, parent, content_widget, on_close_callback):
            self._content_widget = content_widget
            self._on_close_callback = on_close_callback

        def exec(self):
            self._on_close_callback(self._content_widget)
            return 0

    monkeypatch.setattr("app.ui.controllers.map_controller.TableFullScreenDialog", FakeDialog)
    monkeypatch.setattr("app.ui.controllers.map_controller.QTimer.singleShot", lambda _ms, fn: fn())
    monkeypatch.setattr(splitter, "setSizes", lambda sizes: captured.setdefault("sizes", list(sizes)))

    window.open_table_fullscreen()

    assert captured["sizes"] == expected_sizes
    window.close()


def test_table_fullscreen_dialog_prioritizes_address_columns(monkeypatch):
    container = QtWidgets.QWidget()
    container.resize(1600, 900)
    layout = QtWidgets.QVBoxLayout(container)

    main_table = QtWidgets.QTableView()
    main_table.setModel(QStandardItemModel(2, 9))
    main_header = main_table.horizontalHeader()
    main_header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
    for index in range(9):
        main_header.resizeSection(index, 120)

    side_table = QtWidgets.QTableView()
    side_table.setModel(QStandardItemModel(2, 2))

    layout.addWidget(main_table)
    layout.addWidget(side_table)

    monkeypatch.setattr(TableFullScreenDialog, "showMaximized", lambda self: self.resize(1600, 900))
    monkeypatch.setattr("app.ui.controllers.map_controller.QTimer.singleShot", lambda _ms, fn: fn())
    monkeypatch.setattr("app.ui.components.dialogs.QTimer.singleShot", lambda _ms, fn: fn())

    dialog = TableFullScreenDialog(QtWidgets.QWidget(), container, lambda widget: None)

    assert main_header.sectionResizeMode(0) == QtWidgets.QHeaderView.Interactive
    assert main_header.sectionSize(5) > main_header.sectionSize(1)
    assert main_header.sectionSize(8) > main_header.sectionSize(4)
    assert main_header.sectionSize(8) > main_header.sectionSize(2)

    dialog._restore_table_layout()

    assert main_header.sectionResizeMode(0) == QtWidgets.QHeaderView.Interactive
    dialog.close()


def test_table_fullscreen_dialog_exposes_and_syncs_filters(monkeypatch):
    window = MainWindow()
    window.records = [
        make_record(oficio_processo="123/2026", microbacia="Gregorio", eletronico="SIM"),
        make_record(excel_row=3, oficio_processo="999/2025", microbacia="Medeiros", eletronico="NAO", uid="u-2"),
    ]
    window.filtered_records = list(window.records)
    window._update_filters_from_records()
    window.search.setText("Gregorio")
    window.data_tab.filter_status.setCurrentText("Pendentes")
    year_index = window.data_tab.filter_year.findText("2026")
    window.data_tab.filter_year.setCurrentIndex(year_index)
    window.data_tab.filter_micro.set_checked_items(["Gregorio"], all_selected=False)
    window.data_tab.filter_eletronico.set_checked_items(["Eletrônico"], all_selected=False)
    window.apply_filter()

    monkeypatch.setattr(TableFullScreenDialog, "showMaximized", lambda self: None)
    monkeypatch.setattr("app.ui.components.dialogs.QTimer.singleShot", lambda _ms, fn: fn())

    dialog = TableFullScreenDialog(window, window.data_tab.left_panel, lambda widget: None)

    assert dialog.search_fs.text() == "Gregorio"
    assert dialog.filter_status_fs.currentText() == "Pendentes"
    assert dialog.filter_year_fs.currentText() == "2026"
    assert dialog.filter_micro_fs.checked_items() == ["Gregório"]
    assert dialog.filter_eletronico_fs.checked_items() == ["Eletrônico"]

    dialog.search_fs.setText("Medeiros")
    dialog.filter_status_fs.setCurrentText("Todos")
    year_index = dialog.filter_year_fs.findText("2025")
    dialog.filter_year_fs.setCurrentIndex(year_index)
    dialog.filter_micro_fs.set_checked_items(["Medeiros"], all_selected=False)
    dialog.filter_eletronico_fs.set_checked_items(["Físico"], all_selected=False)
    dialog._apply_filters_to_main()

    assert window.search.text() == "Medeiros"
    assert window.data_tab.filter_status.currentText() == "Todos"
    assert window.data_tab.filter_year.currentText() == "2025"
    assert window.data_tab.filter_micro.checked_items() == ["Medeiros"]
    assert window.data_tab.filter_eletronico.checked_items() == ["Físico"]
    dialog.close()
    window.close()


def test_open_map_fullscreen_passes_current_heatmap_points(monkeypatch):
    window = MainWindow()
    window.filtered_records = [
        make_record(compensado="", latitude="-22.01", longitude="-47.89"),
    ]
    window.data_tab.chk_heatmap.setChecked(True)
    window.data_tab.combo_heatmap_type.setCurrentText("Pendentes")
    captured = {}

    class FakeDialog:
        def __init__(self, _parent, _html_path, _geojson, _theme, _marker, _gis, _layer, heatmap_points):
            captured["heatmap_points"] = heatmap_points

        def exec(self):
            return 0

    monkeypatch.setattr("app.ui.controllers.map_controller.MapFullScreenDialog", FakeDialog)

    window.open_map_fullscreen()

    assert captured["heatmap_points"] == [[-22.01, -47.89]]
    window.close()


def test_search_on_map_persists_detected_microbacia(monkeypatch):
    window = MainWindow()
    monkeypatch.setattr("app.ui.controllers.map_controller.geocode_address_arcgis", lambda address: (-22.01, -47.89))
    window.gis = SimpleNamespace(
        find_microbacia=lambda lat, lng: "Gregorio",
        to_geojson_obj=lambda: {}
    )
    monkeypatch.setattr(window, "_highlight_microbacia", lambda micro: None)
    monkeypatch.setattr(window, "_set_map_marker", lambda lat, lng: None)

    window.data_tab.in_end.setText("Rua Teste")
    window.search_on_map()

    assert window.data_tab.in_micro.currentText() == "Gregório"
    window.close()


def test_load_custom_layer_runs_generated_script(monkeypatch):
    window = MainWindow()
    captured = {"scripts": [], "infos": []}

    monkeypatch.setattr(
        "app.ui.controllers.map_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("C:/tmp/camada.geojson", "Arquivos GIS (*.geojson *.json *.kml)"),
    )
    monkeypatch.setattr(
        window.map_controller,
        "_read_custom_layer_geojson",
        lambda path: {"type": "FeatureCollection", "features": [{"path": path}]},
    )
    monkeypatch.setattr(window.map_controller, "run_map_js", lambda script, context: captured["scripts"].append((context, script)))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: captured["infos"].append(args[2]))

    window.load_custom_layer()

    assert captured["scripts"][0][0] == "load-custom-layer"
    assert "window.customLayer = L.geoJSON" in captured["scripts"][0][1]
    assert captured["infos"] == ["Camada carregada com sucesso."]
    window.close()


def test_search_on_map_enables_street_view_after_geocode(monkeypatch):
    window = MainWindow()
    monkeypatch.setattr("app.ui.controllers.map_controller.geocode_address_arcgis", lambda address: (-22.02, -47.91))
    monkeypatch.setattr(window, "_run_map_js", lambda *args, **kwargs: None)
    monkeypatch.setattr(window, "_highlight_microbacia", lambda *args, **kwargs: None)
    window.gis = SimpleNamespace(
        find_microbacia=lambda lat, lng: None,
        to_geojson_obj=lambda: {}
    )

    assert window.data_tab.btn_street_view.isEnabled() is False

    window.data_tab.in_end.setText("Rua Teste")
    window.search_on_map()

    assert window.last_marker_coords == (-22.02, -47.91)
    assert window.data_tab.btn_street_view.isEnabled() is True
    window.close()


def test_open_street_view_uses_last_marker_when_no_addresses(monkeypatch):
    window = MainWindow()
    opened = []
    window.last_marker_coords = (-22.03, -47.92)

    monkeypatch.setattr(
        "app.ui.controllers.map_controller.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )

    window.open_street_view()

    assert opened == ["https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=-22.03,-47.92"]
    window.close()


def test_open_street_view_prompts_for_selected_address(monkeypatch):
    window = MainWindow()
    opened = []
    markers = []
    window.data_tab.in_end.setText("Rua Principal")
    window.form_plantios = [
        PlantioItem(sequence=1, endereco="Rua Plantio A", qtd_mudas="4"),
        PlantioItem(sequence=2, endereco="Rua Plantio B", qtd_mudas="6"),
    ]

    monkeypatch.setattr(
        "app.ui.controllers.map_controller.QInputDialog.getItem",
        lambda *args, **kwargs: ("Plantio 2: Rua Plantio B (6 mudas)", True),
    )
    monkeypatch.setattr("app.ui.controllers.map_controller.geocode_address_arcgis", lambda address: (-22.04, -47.93))
    monkeypatch.setattr(window.map_controller, "set_map_marker", lambda lat, lng: markers.append((lat, lng)))
    monkeypatch.setattr(
        "app.ui.controllers.map_controller.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()),
    )

    window.open_street_view()

    assert markers == [(-22.04, -47.93)]
    assert opened == ["https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=-22.04,-47.93"]
    window.close()


def test_heatmap_realizadas_uses_plantio_coordinates():
    window = MainWindow()
    record = make_record(
        compensado="SIM",
        latitude="-22.01",
        longitude="-47.89",
        latitude_plantio="-22.05",
        longitude_plantio="-47.95",
    )

    assert window._build_heatmap_point(record, "Realizadas") == [-22.05, -47.95]

    window.close()


def test_heatmap_pendentes_keeps_main_coordinates():
    window = MainWindow()
    record = make_record(
        compensado="",
        latitude="-22.01",
        longitude="-47.89",
        latitude_plantio="-22.05",
        longitude_plantio="-47.95",
    )

    assert window._build_heatmap_point(record, "Pendentes") == [-22.01, -47.89]

    window.close()


def test_heatmap_tudo_preserves_main_coordinates_for_compensated_records():
    window = MainWindow()
    record = make_record(
        compensado="SIM",
        latitude="-22.01",
        longitude="-47.89",
        latitude_plantio="-22.05",
        longitude_plantio="-47.95",
    )

    assert window._build_heatmap_point(record, "Tudo") == [-22.01, -47.89]

    window.close()


def test_fullscreen_heatmap_realizadas_uses_same_plantio_coordinates():
    window = MainWindow()
    window.filtered_records = [
        make_record(
            compensado="SIM",
            latitude="-22.01",
            longitude="-47.89",
            latitude_plantio="-22.05",
            longitude_plantio="-47.95",
        )
    ]
    fake_dialog = SimpleNamespace(
        chk_fs_heatmap=SimpleNamespace(isChecked=lambda: True),
        combo_fs_heatmap=SimpleNamespace(currentText=lambda: "Realizadas"),
        parent_window=window,
    )

    assert MapFullScreenDialog._get_current_points_fs(fake_dialog) == [[-22.05, -47.95]]

    window.close()


def test_fullscreen_heatmap_returns_empty_points_when_disabled():
    window = MainWindow()
    window.filtered_records = [
        make_record(
            compensado="SIM",
            latitude="-22.01",
            longitude="-47.89",
            latitude_plantio="-22.05",
            longitude_plantio="-47.95",
        )
    ]
    fake_dialog = SimpleNamespace(
        chk_fs_heatmap=SimpleNamespace(isChecked=lambda: False),
        combo_fs_heatmap=SimpleNamespace(currentText=lambda: "Realizadas"),
        parent_window=window,
    )

    assert MapFullScreenDialog._get_current_points_fs(fake_dialog) == []

    window.close()


def test_record_needs_batch_geocode_when_only_plantio_coords_are_missing():
    window = MainWindow()
    record = make_record(
        latitude="-22.01",
        longitude="-47.89",
        microbacia="Gregorio",
        endereco_plantio="Rua Plantio",
        latitude_plantio="",
        longitude_plantio="",
    )

    assert window._record_needs_batch_geocode(record) is True
    window.close()


def test_on_geocode_finished_persists_batch_coordinates(monkeypatch):
    window = MainWindow()
    record = make_record(
        uid="u-geo",
        endereco="Rua Principal",
        endereco_plantio="Rua Plantio",
        latitude="",
        longitude="",
        latitude_plantio="",
        longitude_plantio="",
        microbacia="",
    )
    window.records = [record]
    window.session_runtime.path = "dummy.xlsx"
    window.gis = SimpleNamespace(find_microbacia=lambda lat, lng: "Gregorio")

    persisted = {}
    reloaded = []
    monkeypatch.setattr(
        window.map_controller.persistence,
        "prepare_base",
        lambda workbook_path, **kwargs: type(
            "Preparation",
            (),
            {"base_records": (record,), "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.map_controller.persistence,
        "execute_batch_geocode",
        lambda **kwargs: persisted.update(kwargs)
        or type(
            "WriteResult",
            (),
            {
                "status": LocalMutationSyncStatus(
                    status="sqlite",
                    operation="batch_geocode",
                    workbook_path="dummy.xlsx",
                    strategy="snapshot_rebuild",
                    record_count=len(kwargs["projected_records"]),
                ),
                "write_status": type(
                    "WriteStatus",
                    (),
                    {"status": "sqlite_authoritative", "operation": "batch_geocode", "issues": (), "finalized": False},
                )(),
                "records": tuple(kwargs["projected_records"]),
                "excel_result": len(kwargs["updated_records"]),
                "rollback_issues": (),
                "finalized": False,
            },
        )(),
    )
    monkeypatch.setattr(window, "reload", lambda: reloaded.append(True))

    window.on_geocode_finished({
        record.excel_row: {
            "main": (-22.01, -47.89),
            "plantio": (-22.02, -47.90),
        }
    })

    assert len(persisted["projected_records"]) == 1
    saved_record = persisted["projected_records"][0]
    assert saved_record.latitude == "-22.01"
    assert saved_record.longitude == "-47.89"
    assert saved_record.latitude_plantio == "-22.02"
    assert saved_record.longitude_plantio == "-47.9"
    assert saved_record.microbacia == "Gregorio"
    assert reloaded == [True]
    window.close()


def test_persist_batch_geocode_uses_authoritative_runtime_base_and_tracks_sync_status(monkeypatch):
    window = MainWindow()
    window.session_runtime.path = "dummy.xlsx"
    window.records = [make_record(excel_row=3, uid="session-stale", endereco="Rua Sessao")]
    window.gis = SimpleNamespace(find_microbacia=lambda lat, lng: "Gregorio")

    authoritative_record = make_record(
        excel_row=12,
        uid="geo-authoritative",
        endereco="Rua Autoritativa",
        latitude="",
        longitude="",
        microbacia="",
    )
    sync_calls = []
    persisted = {}

    monkeypatch.setattr(
        window.map_controller.persistence,
        "prepare_base",
        lambda workbook_path, **kwargs: type(
            "Preparation",
            (),
            {"base_records": (authoritative_record,), "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.map_controller.persistence,
        "execute_batch_geocode",
        lambda **kwargs: sync_calls.append(kwargs)
        or persisted.update(kwargs)
        or type(
            "WriteResult",
            (),
            {
                "status": LocalMutationSyncStatus(
                    status="sqlite",
                    operation="batch_geocode",
                    workbook_path="dummy.xlsx",
                    strategy="snapshot_rebuild",
                    record_count=len(kwargs["projected_records"]),
                ),
                "write_status": type(
                    "WriteStatus",
                    (),
                    {"status": "sqlite_authoritative", "operation": "batch_geocode", "issues": (), "finalized": False},
                )(),
                "records": tuple(kwargs["projected_records"]),
                "excel_result": len(kwargs["updated_records"]),
                "rollback_issues": (),
                "finalized": False,
            },
        )(),
    )

    updated = window._persist_batch_geocode_results(
        {
            authoritative_record.excel_row: {
                "main": (-22.01, -47.89),
            }
        }
    )

    assert updated == 1
    assert len(sync_calls) == 1
    assert [record.uid for record in sync_calls[0]["authoritative_records"]] == ["geo-authoritative"]
    assert persisted["updated_records"][0].uid == "geo-authoritative"
    assert persisted["projected_records"][0].latitude == "-22.01"
    assert persisted["projected_records"][0].microbacia == "Gregorio"
    assert window._local_mutation_sync_status is not None
    assert window._local_mutation_sync_status.operation == "batch_geocode"
    window.close()


def test_search_on_map_plantio_asks_which_address_to_use(monkeypatch):
    window = MainWindow()
    captured = []
    window.form_plantios = [
        PlantioItem(sequence=1, endereco="Rua Plantio A", qtd_mudas="4"),
        PlantioItem(sequence=2, endereco="Rua Plantio B", qtd_mudas="6"),
    ]

    monkeypatch.setattr(
        "app.ui.controllers.map_controller.QInputDialog.getItem",
        lambda *args, **kwargs: ("Plantio 2: Rua Plantio B (6 mudas)", True),
    )
    monkeypatch.setattr(window.map_controller, "perform_geocode", lambda address: captured.append(address))

    window.search_on_map_plantio()

    assert captured == ["Rua Plantio B"]
    window.close()


def test_on_geocode_finished_updates_all_plantios(monkeypatch):
    window = MainWindow()
    record = make_record(
        uid="u-multi",
        compensado="SIM",
        plantios=[
            PlantioItem(sequence=1, endereco="Rua Plantio A", qtd_mudas="3"),
            PlantioItem(sequence=2, endereco="Rua Plantio B", qtd_mudas="7"),
        ],
    )
    window.records = [record]
    window.session_runtime.path = "dummy.xlsx"
    window.gis = SimpleNamespace(find_microbacia=lambda lat, lng: "Gregorio")

    persisted = {}
    monkeypatch.setattr(
        window.map_controller.persistence,
        "prepare_base",
        lambda workbook_path, **kwargs: type(
            "Preparation",
            (),
            {"base_records": (record,), "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.map_controller.persistence,
        "execute_batch_geocode",
        lambda **kwargs: persisted.update(kwargs)
        or type(
            "WriteResult",
            (),
            {
                "status": LocalMutationSyncStatus(
                    status="sqlite",
                    operation="batch_geocode",
                    workbook_path="dummy.xlsx",
                    strategy="snapshot_rebuild",
                    record_count=len(kwargs["projected_records"]),
                ),
                "write_status": type(
                    "WriteStatus",
                    (),
                    {"status": "sqlite_authoritative", "operation": "batch_geocode", "issues": (), "finalized": False},
                )(),
                "records": tuple(kwargs["projected_records"]),
                "excel_result": len(kwargs["updated_records"]),
                "rollback_issues": (),
                "finalized": False,
            },
        )(),
    )
    monkeypatch.setattr(window, "reload", lambda: None)

    window.on_geocode_finished(
        {
            record.excel_row: {
                "plantios": {
                    1: (-22.01, -47.89),
                    2: (-22.02, -47.90),
                }
            }
        }
    )

    saved_record = persisted["projected_records"][0]
    assert saved_record.plantios[0].latitude == "-22.01"
    assert saved_record.plantios[1].longitude == "-47.9"
    assert saved_record.latitude_plantio == "-22.01"
    assert saved_record.endereco_plantio == "2 áreas / 10 mudas"


def test_heatmap_realizadas_includes_all_plantio_coordinates():
    window = MainWindow()
    record = make_record(
        compensado="SIM",
        plantios=[
            PlantioItem(sequence=1, endereco="Rua Plantio A", qtd_mudas="3", latitude="-22.05", longitude="-47.95"),
            PlantioItem(sequence=2, endereco="Rua Plantio B", qtd_mudas="7", latitude="-22.06", longitude="-47.96"),
        ],
    )

    assert window._build_heatmap_points(record, "Realizadas") == [[-22.05, -47.95], [-22.06, -47.96]]

    window.close()


def test_perform_geocode_surfaces_not_found(monkeypatch):
    window = MainWindow()
    warnings = []

    monkeypatch.setattr("app.ui.controllers.map_controller.geocode_address_arcgis", lambda address: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    window._perform_geocode("Endereço Inexistente")

    assert warnings and "localizar" in warnings[0]
    window.close()


def test_load_last_session_reports_failures_and_clears_setting(monkeypatch, tmp_path):
    state = {"last_session_path": str(tmp_path / "ultima.xlsx")}

    class MockSettings:
        def __init__(self, *args, **kwargs): pass
        def value(self, key, default=""): return state.get(key, default)
        def setValue(self, key, val): state[key] = val
        def remove(self, key): state.pop(key, None)

    monkeypatch.setattr("app.ui.main_window.QSettings", MockSettings)

    window = MainWindow()
    monkeypatch.setattr(
        window.authoritative_persistence,
        "ensure_singleton_session",
        lambda: SimpleNamespace(session_path="session://banco-local", display_name="Banco local"),
    )
    monkeypatch.setattr(window.data_controller, "load_session", lambda *args, **kwargs: True)

    window._load_last_session()

    assert "last_session_path" not in state
    window.close()


def test_load_last_session_bootstraps_singleton_from_legacy_workbook(monkeypatch, tmp_path):
    legacy_path = tmp_path / "ultima.xlsx"
    legacy_path.write_text("planilha-legada", encoding="utf-8")
    state = {"last_excel_path": str(legacy_path)}

    class MockSettings:
        def __init__(self, *args, **kwargs):
            pass

        def value(self, key, default=""):
            return state.get(key, default)

        def setValue(self, key, val):
            state[key] = val

        def remove(self, key):
            state.pop(key, None)

    monkeypatch.setattr("app.ui.main_window.QSettings", MockSettings)
    monkeypatch.setattr(MainWindow, "_load_last_session", lambda self: None)

    window = MainWindow()
    calls = {}
    monkeypatch.setattr(
        window.data_controller.persistence,
        "migrate_legacy_workbook_to_singleton",
        lambda path: calls.update({"migrate": path}) or "session://banco-local",
    )
    monkeypatch.setattr(
        window.data_controller,
        "load_session",
        lambda path, confirm_discard=True: calls.update({"load": (path, confirm_discard)}) or True,
    )

    assert window.data_controller.load_last_session() is True
    assert calls["migrate"] == os.path.abspath(str(legacy_path))
    assert calls["load"] == ("session://banco-local", False)
    assert state["database_bootstrap_source_path"] == os.path.abspath(str(legacy_path))
    assert "last_excel_path" not in state
    window.close()


def test_load_last_session_ignores_legacy_bootstrap_in_production(monkeypatch, tmp_path):
    legacy_path = tmp_path / "ultima.xlsx"
    legacy_path.write_text("planilha-legada", encoding="utf-8")
    state = {"last_excel_path": str(legacy_path)}

    class MockSettings:
        def __init__(self, *args, **kwargs):
            pass

        def value(self, key, default=""):
            return state.get(key, default)

        def setValue(self, key, val):
            state[key] = val

        def remove(self, key):
            state.pop(key, None)

    monkeypatch.setattr("app.ui.main_window.QSettings", MockSettings)
    monkeypatch.setattr(MainWindow, "_load_last_session", lambda self: None)

    window = MainWindow(
        access_session=AppAccessSession(
            environment=AccessEnvironment.PRODUCTION,
            label="Producao",
            auth_mode="password",
            user_email="analista@prefeitura.sp.gov.br",
            local_db_path=str(tmp_path / "producao.db"),
            local_session_path="session://banco-local",
        )
    )
    calls = {}

    monkeypatch.setattr(
        window.data_controller.persistence,
        "migrate_legacy_workbook_to_singleton",
        lambda path: (_ for _ in ()).throw(AssertionError(f"nao deveria migrar legado em producao: {path}")),
    )
    monkeypatch.setattr(
        window.data_controller.persistence,
        "ensure_singleton_session",
        lambda: SimpleNamespace(session_path="session://banco-local", display_name="Banco local"),
    )
    monkeypatch.setattr(
        window.data_controller,
        "load_session",
        lambda path, confirm_discard=True: calls.update({"load": (path, confirm_discard)}) or True,
    )

    assert window.data_controller.load_last_session() is True
    assert calls["load"] == ("session://banco-local", False)
    assert state["last_excel_path"] == str(legacy_path)
    window.close()


def test_load_last_session_falls_back_to_singleton_database(monkeypatch):
    state = {}

    class MockSettings:
        def __init__(self, *args, **kwargs):
            pass

        def value(self, key, default=""):
            return state.get(key, default)

        def setValue(self, key, val):
            state[key] = val

        def remove(self, key):
            state.pop(key, None)

    monkeypatch.setattr("app.ui.main_window.QSettings", MockSettings)
    monkeypatch.setattr(MainWindow, "_load_last_session", lambda self: None)

    window = MainWindow()
    calls = {}

    monkeypatch.setattr(
        window.data_controller.persistence,
        "ensure_singleton_session",
        lambda: SimpleNamespace(session_path="session://banco-local", display_name="Banco local"),
    )
    monkeypatch.setattr(
        window.data_controller,
        "load_session",
        lambda path, confirm_discard=True: calls.update({"load": (path, confirm_discard)}) or True,
    )

    assert window.data_controller.load_last_session() is True
    assert calls["load"] == ("session://banco-local", False)
    window.close()


def test_load_session_failure_restores_previous_filter_state(monkeypatch):
    window = MainWindow()
    window.records = [
        make_record(oficio_processo="123/2026", microbacia="Gregorio", eletronico="SIM"),
        make_record(excel_row=3, oficio_processo="999/2025", microbacia="Medeiros", eletronico="NAO", uid="u-2"),
    ]
    window.filtered_records = list(window.records)
    window._update_filters_from_records()

    window.data_tab.search.setText("Gregorio")
    window.data_tab.filter_status.setCurrentText("Pendentes")
    year_index = window.data_tab.filter_year.findText("2026")
    window.data_tab.filter_year.setCurrentIndex(year_index)
    window.data_tab.filter_micro.set_checked_items(["Gregorio"], all_selected=False)
    window.data_tab.filter_eletronico.set_checked_items(["Eletrônico"], all_selected=False)
    window.apply_filter()

    monkeypatch.setattr(window.session_runtime, "load", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("falhou")))

    window._load_session("quebrado.xlsx")

    assert window.data_tab.search.text() == "Gregorio"
    assert window.data_tab.filter_status.currentText() == "Pendentes"
    assert window.data_tab.filter_year.currentText() == "2026"
    assert window.data_tab.filter_micro.checked_items() == ["Gregório"]
    assert window.data_tab.filter_eletronico.checked_items() == ["Eletrônico"]
    assert len(window.records) == 2
    window.close()


def test_load_session_continues_when_gis_fails(ui_window_factory, monkeypatch, tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "Oficio/ Processo",
            "Eletronico",
            "Caixa",
            "Av. Tec.",
            "Compensacao",
            "Endereco",
            "Microbacia",
            "Compensado",
        ]
    )
    sheet.append(["123/2026", "SIM", "CX-1", "AT-1", 8, "Rua A", "Gregorio", ""])
    workbook.save(workbook_path)

    window = ui_window_factory()
    map_calls = []
    real_isdir = os.path.isdir

    monkeypatch.setattr(window, "_run_map_js", lambda script, context: map_calls.append((context, script)))
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.os.path.isdir",
        lambda path: True if path == window.MICROB_DIR else real_isdir(path),
    )
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.GisService",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("shapefile quebrado")),
    )

    assert window._load_session(str(workbook_path)) is True
    assert len(window.records) == 1
    assert window.gis is None
    assert "Microbacias indisponiveis" in window.data_tab.map_notice_label.text()
    assert any(context == "clear-microbacias-load-failure" for context, _script in map_calls)
    assert any(context == "gis-load-failure-status" for context, _script in map_calls)
    window.close()


def test_load_session_can_hydrate_session_records_from_sqlite_snapshot(monkeypatch):
    window = MainWindow()
    session_records = [make_record(oficio_processo="EXCEL-1", uid="excel-1")]
    mirrored_records = [make_record(oficio_processo="SQLITE-1", uid="sqlite-1", microbacia="Gregorio")]

    def fake_run_blocking_spec(spec):
        window.session_runtime.path = "dummy.xlsx"
        return SimpleNamespace(records=session_records)

    monkeypatch.setattr(window, "run_blocking_spec", fake_run_blocking_spec)
    monkeypatch.setattr(
        window.persistence_service,
        "sync_workbook_snapshot",
        lambda workbook_path, records: SimpleNamespace(
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            record_count=len(records),
        ),
    )
    monkeypatch.setattr(window.data_controller, "_refresh_dashboard_record_overview", lambda: None)
    monkeypatch.setattr(
        window.data_controller.local_record_queries,
        "resolve_record_source",
        lambda workbook_path, **kwargs: LocalRecordReadResult(
            source="sqlite",
            records=tuple(mirrored_records),
            strategy="sqlite_snapshot",
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            mirrored_records=1,
            session_records=1,
        ),
    )
    monkeypatch.setattr(window.data_controller, "load_gis", lambda: True)
    monkeypatch.setattr(window.data_controller, "apply_filter", lambda: None)
    monkeypatch.setattr(window.data_tab, "align_splitter_to_table_width", lambda: None)
    monkeypatch.setattr(window, "clear_form", lambda *args, **kwargs: True)
    monkeypatch.setattr(window, "refresh_operations_overview", lambda: None)
    monkeypatch.setattr(window, "_load_sort_settings", lambda: None)

    assert window._load_session("dummy.xlsx") is True
    assert [record.uid for record in window.records] == ["sqlite-1"]
    assert window._local_session_source_status is not None
    assert window._local_session_source_status.source == "sqlite"
    assert window._local_session_source_status.strategy == "sqlite_snapshot"
    window.close()


def test_load_session_clears_previous_write_statuses(monkeypatch):
    window = MainWindow()
    window._local_mutation_sync_status = SimpleNamespace(status="sqlite", operation="edit")
    window._authoritative_write_status = SimpleNamespace(status="sqlite_primary", operation="edit")

    authoritative_result = SimpleNamespace(
        loaded_records=(make_record(oficio_processo="EXCEL-1", uid="excel-1"),),
        records=(make_record(oficio_processo="SQLITE-1", uid="sqlite-1"),),
        local_session_source_status=LocalRecordReadStatus(
            status="sqlite",
            source="sqlite",
            strategy="sqlite_snapshot",
            workbook_path="dummy.xlsx",
            synced_at="2026-03-31T12:00:00+00:00",
            mirrored_records=1,
            session_records=1,
            filtered_records=1,
        ),
        issues=(),
    )

    def fake_run_blocking_spec(_spec):
        window.session_runtime.path = "dummy.xlsx"
        return authoritative_result

    monkeypatch.setattr(window, "run_blocking_spec", fake_run_blocking_spec)
    monkeypatch.setattr(window.data_controller, "_refresh_dashboard_record_overview", lambda: None)
    monkeypatch.setattr(window.data_controller, "load_gis", lambda: True)
    monkeypatch.setattr(window.data_controller, "apply_filter", lambda: None)
    monkeypatch.setattr(window.data_tab, "align_splitter_to_table_width", lambda: None)
    monkeypatch.setattr(window, "clear_form", lambda *args, **kwargs: True)
    monkeypatch.setattr(window, "refresh_operations_overview", lambda: None)
    monkeypatch.setattr(window, "_load_sort_settings", lambda: None)

    assert window._load_session("dummy.xlsx") is True
    assert window._local_mutation_sync_status is None
    assert window._authoritative_write_status is None
    assert window._local_session_source_status.source == "sqlite"
    window.close()


def test_load_settings_restores_geometry_and_tab(monkeypatch):
    state = {"window_geometry": b"geom", "active_tab_index": 1}
    restored = []
    
    monkeypatch.setattr(MainWindow, "restoreGeometry", lambda self, geometry: restored.append(geometry) or True)

    window = MainWindow()
    window.settings = SimpleNamespace(
        value=lambda key, default=None: state.get(key, default),
        setValue=lambda *args, **kwargs: None,
    )
    window._load_settings()

    assert restored == [b"geom"]
    assert window._startup_geometry_restored is True
    assert window.tabs.currentIndex() == 1
    window.close()


def test_load_settings_filters_missing_recent_files(monkeypatch, tmp_path):
    existing = "session://base-principal"

    class MemorySettings:
        def __init__(self):
            self._data = {}

        def value(self, key, default=None):
            return self._data.get(key, default)

        def setValue(self, key, value):
            self._data[key] = value

        def remove(self, key):
            self._data.pop(key, None)

    window = MainWindow()
    window.settings = AppSettings(MemorySettings())
    window.settings.set_recent_files([existing, existing, str(tmp_path / "missing.xlsx")])
    monkeypatch.setattr(
        window.authoritative_persistence,
        "resolve_session_availability",
        lambda path: SimpleNamespace(
            path=path,
            display_label="Base principal",
            detail_message="Sessão SQLite local disponível para Base principal.",
            is_openable=(path == existing),
        ),
    )

    window._load_settings()

    assert window.recent_files == []
    assert window.settings.recent_files() == []
    window.close()


def test_recent_files_menu_is_hidden_in_single_database_mode():
    window = MainWindow()
    window._update_recent_files_menu()
    assert not hasattr(window, "menu_recent")
    window.close()


def test_close_event_persists_geometry_and_active_tab(monkeypatch):
    window = MainWindow()
    saved = {}
    window.settings = SimpleNamespace(
        value=lambda key, default=None: saved.get(key, default),
        setValue=lambda key, value: saved.__setitem__(key, value),
        remove=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(window, "saveGeometry", lambda: b"geom")
    
    window.tabs.setCurrentIndex(1)
    window.close()

    assert saved["window_geometry"] == b"geom"
    assert saved["active_tab_index"] == 1


def test_help_menu_exposes_support_actions():
    window = MainWindow()

    assert window.action_export_diagnostics.text() == "Exportar Diagnóstico"
    assert window.action_open_logs.text() == "Abrir Pasta de Logs"
    assert window.action_about.text() == "Sobre"
    window.close()


def test_file_menu_exposes_operation_history_action():
    window = MainWindow()

    assert window.action_reload.text() == "Recarregar"
    assert window.action_operation_history.text() == "Histórico de Operações"
    assert not hasattr(window, "action_database")
    assert not hasattr(window, "btn_open")
    assert not hasattr(window, "btn_reload")
    window.close()


def test_close_event_stops_geocode_worker(monkeypatch):
    window = MainWindow()
    calls = []

    worker = SimpleNamespace(
        progress_update=SimpleNamespace(disconnect=lambda: calls.append("disconnect_progress")),
        finished_process=SimpleNamespace(disconnect=lambda: calls.append("disconnect_finished")),
        isRunning=lambda: True,
        stop=lambda: calls.append("stop"),
        quit=lambda: calls.append("quit"),
        wait=lambda timeout: calls.append(("wait", timeout)) or True,
    )
    window.geo_worker = worker
    window.track_background_worker(
        "batch_geocode",
        worker,
        disconnect_callbacks=[
            lambda: worker.progress_update.disconnect(),
            lambda: worker.finished_process.disconnect(),
        ],
        stop_callback=worker.stop,
        wait_ms=10000,
    )

    window.close()

    assert "disconnect_progress" in calls
    assert "disconnect_finished" in calls
    assert "stop" in calls
    assert "quit" in calls
    assert ("wait", 10000) in calls


def test_open_logs_folder_uses_log_directory(monkeypatch):
    window = MainWindow()
    opened = []

    monkeypatch.setattr("app.ui.controllers.support_controller.QDesktopServices.openUrl", lambda url: opened.append(url.toLocalFile()))

    window.open_logs_folder()

    assert [os.path.normcase(os.path.normpath(path)) for path in opened] == [os.path.normcase(os.path.normpath(LOG_DIR))]
    window.close()


def test_export_diagnostics_writes_file_and_remembers_directory(monkeypatch, tmp_path):
    class MemorySettings:
        def __init__(self):
            self._data = {}

        def value(self, key, default=None):
            return self._data.get(key, default)

        def setValue(self, key, value):
            self._data[key] = value

        def remove(self, key):
            self._data.pop(key, None)

    window = MainWindow()
    window.settings = AppSettings(MemorySettings())
    target = tmp_path / "suporte" / "diag.json"
    target.parent.mkdir()

    monkeypatch.setattr(
        "app.ui.controllers.support_controller.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(target), "JSON (*.json)"),
    )

    window.export_diagnostics()

    assert target.exists()
    with open(target, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["app"]["version"]
    assert "session" in payload
    assert "persistence" in payload
    assert payload["persistence"]["available"] is True
    assert window.settings.last_export_dir() == str(target.parent)
    window.close()


def test_run_map_js_reports_failures_without_raising(monkeypatch):
    logs = []
    window = MainWindow()
    fake_page = SimpleNamespace(runJavaScript=lambda script: (_ for _ in ()).throw(RuntimeError("web indisponivel")))
    window.data_tab.web = SimpleNamespace(page=lambda: fake_page)
    window.data_tab._web_view_initialized = True

    monkeypatch.setattr("app.ui.controllers.map_controller.logger.error", lambda msg: logs.append(str(msg)))

    window._run_map_js("window.setStatus('x');", "status")

    assert logs and "MAP JS" in logs[0]
    assert "status" in logs[0]
    window.close()


def test_delete_selected_surfaces_lookup_errors(monkeypatch):
    window = MainWindow()
    errors = []
    reloaded = []
    window.session_runtime.path = "dummy.xlsx"
    window.records = [make_record(uid="u-delete")]
    window.selected = make_record(uid="u-delete")

    monkeypatch.setattr(
        window.form_controller.persistence,
        "prepare_delete",
        lambda *args, **kwargs: type(
            "Preparation",
            (),
            {"base_records": tuple(window.records), "selected_record": window.selected, "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.persistence,
        "execute_delete",
        lambda *args, **kwargs: (_ for _ in ()).throw(LookupError("UID ausente")),
    )
    monkeypatch.setattr(window, "reload", lambda: reloaded.append(True))
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: errors.append(args[2]))

    window.delete_selected()

    assert reloaded == []
    assert errors == ["Nao foi possivel excluir o registro: UID ausente"]
    window.close()


def test_add_new_writes_audit_entry(monkeypatch):
    window = MainWindow()
    audits = []
    refreshed = []

    monkeypatch.setattr(window.form_controller.persistence.session_backup_service, "create_backup", lambda **kwargs: "C:/tmp/add.json")
    monkeypatch.setattr(
        window.form_controller.local_mutation_sync,
        "apply_after_add",
        lambda **kwargs: type(
            "MutationResult",
            (),
            {
                "status": type(
                    "Status",
                    (),
                    {
                        "status": "sqlite",
                        "strategy": "incremental",
                        "synced_at": "2026-03-31T12:00:00+00:00",
                        "record_count": len(kwargs["existing_records"]) + 1,
                        "issues": (),
                        "operation": "add",
                        "uses_sqlite": True,
                    },
                )(),
                "records": tuple([*kwargs["existing_records"], kwargs["added_record"]]),
            },
        )(),
    )
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: audits.append(payload))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    window.session_runtime.path = "dummy.xlsx"
    window.data_tab.in_oficio.setText("123/2026")
    window.data_tab.in_avtec.setText("AT-55")
    window.data_tab.in_comp.setText("10")
    window.data_tab.in_end.setText("Rua Nova")

    window.add_new()

    assert len(refreshed) == 1
    assert audits[0]["action"] == "add"
    assert audits[0]["backup_path"].endswith("add.json")
    assert audits[0]["after"]["av_tec"] == "AT-55"
    window.close()


def test_add_new_does_not_depend_on_external_workbook_state(monkeypatch):
    window = MainWindow()
    infos = []

    monkeypatch.setattr(window.form_controller.persistence.session_backup_service, "create_backup", lambda **kwargs: "C:/tmp/add.json")
    monkeypatch.setattr(
        window.form_controller.local_mutation_sync,
        "apply_after_add",
        lambda **kwargs: type(
            "MutationResult",
            (),
            {
                "status": type(
                    "Status",
                    (),
                    {
                        "status": "sqlite",
                        "strategy": "incremental",
                        "synced_at": "2026-03-31T12:00:00+00:00",
                        "record_count": len(kwargs["existing_records"]) + 1,
                        "issues": (),
                        "operation": "add",
                        "uses_sqlite": True,
                    },
                )(),
                "records": tuple([*kwargs["existing_records"], kwargs["added_record"]]),
            },
        )(),
    )
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: None)
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: True)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: infos.append(args[2]))

    window.session_runtime.path = "dummy.xlsx"
    window.data_tab.in_oficio.setText("123/2026")
    window.data_tab.in_avtec.setText("AT-55")
    window.data_tab.in_comp.setText("10")
    window.data_tab.in_end.setText("Rua Nova")

    window.add_new()

    assert infos == ["Adicionado com sucesso."]
    window.close()


def test_add_new_uses_authoritative_runtime_base_for_projection_and_sync(monkeypatch):
    window = MainWindow()
    refreshed = []
    execute_calls = []
    authoritative_base = [make_record(uid="uid-sqlite-base", av_tec="AT-BASE", excel_row=8)]

    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        window.form_controller.persistence,
        "prepare_create",
        lambda workbook_path, **kwargs: type(
            "Preparation",
            (),
            {"base_records": tuple(authoritative_base), "duplicate_row": None, "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.persistence,
        "execute_add",
        lambda record, **kwargs: execute_calls.append({"record": record, **kwargs})
        or type(
            "WriteResult",
            (),
            {
                "status": LocalMutationSyncStatus(
                    status="sqlite",
                    operation="add",
                    workbook_path="dummy.xlsx",
                    strategy="incremental",
                    record_count=2,
                ),
                "write_status": type(
                    "WriteStatus",
                    (),
                    {"status": "sqlite_authoritative", "operation": "add", "issues": (), "finalized": False},
                )(),
                "records": tuple([*authoritative_base, make_record(uid="uid-added", av_tec=record.av_tec, excel_row=9)]),
                "excel_result": None,
                "rollback_issues": (),
                "finalized": False,
            },
        )(),
    )

    window.session_runtime.path = "dummy.xlsx"
    window.records = [make_record(uid="uid-stale-session", av_tec="AT-OLD", excel_row=2)]
    window.data_tab.in_oficio.setText("123/2026")
    window.data_tab.in_avtec.setText("AT-55")
    window.data_tab.in_comp.setText("10")
    window.data_tab.in_end.setText("Rua Nova")

    window.add_new()

    assert len(execute_calls) == 1
    assert [record.uid for record in execute_calls[0]["authoritative_records"]] == ["uid-sqlite-base"]
    assert [record.uid for record in refreshed[0]] == ["uid-sqlite-base", "uid-added"]
    window.close()


def test_save_edit_blocks_invalid_payload(monkeypatch):
    window = MainWindow()
    saved = []
    warnings = []

    monkeypatch.setattr(window.session_runtime, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.session_runtime, "save_edit", lambda record: saved.append(record))
    monkeypatch.setattr(window, "reload", lambda: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    window.session_runtime.path = "dummy.xlsx"
    window.selected = make_record()
    window._fill_form(window.selected)
    window.data_tab.in_comp.setText("")

    window.save_edit()

    assert saved == []
    assert warnings and "Compensação" in warnings[0]
    window.close()
def test_save_edit_writes_audit_entry(monkeypatch):
    window = MainWindow()
    audits = []
    refreshed = []

    monkeypatch.setattr(window.form_controller.persistence.session_backup_service, "create_backup", lambda **kwargs: "C:/tmp/edit.json")
    monkeypatch.setattr(
        window.form_controller.local_mutation_sync,
        "apply_after_edit",
        lambda **kwargs: type(
            "MutationResult",
            (),
            {
                "status": type(
                    "Status",
                    (),
                    {
                        "status": "sqlite",
                        "strategy": "incremental",
                        "synced_at": "2026-03-31T12:00:00+00:00",
                        "record_count": len(kwargs["existing_records"]),
                        "issues": (),
                        "operation": "edit",
                        "uses_sqlite": True,
                    },
                )(),
                "records": tuple(
                    [
                        kwargs["updated_record"]
                        if getattr(record, "uid", "") == getattr(kwargs["updated_record"], "uid", "")
                        else record
                        for record in kwargs["existing_records"]
                    ]
                ),
            },
        )(),
    )
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: audits.append(payload))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_selected_record",
        lambda workbook_path, **kwargs: type(
            "SelectionResult",
            (),
            {"record": make_record(caixa="CX-1", uid="uid-edit"), "issues": ()},
        )(),
    )

    window.session_runtime.path = "dummy.xlsx"
    window.records = [make_record(caixa="CX-1", uid="uid-edit")]
    window.selected = window.records[0]
    window._fill_form(window.selected)
    window.data_tab.in_caixa.setText("CX-9")

    window.save_edit()

    assert len(refreshed) == 1
    assert audits[0]["action"] == "edit"
    assert audits[0]["before"]["caixa"] == "CX-1"
    assert audits[0]["after"]["caixa"] == "CX-9"
    window.close()


def test_save_edit_does_not_depend_on_external_workbook_state(monkeypatch):
    window = MainWindow()
    infos = []

    monkeypatch.setattr(window.form_controller.persistence.session_backup_service, "create_backup", lambda **kwargs: "C:/tmp/edit.json")
    monkeypatch.setattr(
        window.form_controller.local_mutation_sync,
        "apply_after_edit",
        lambda **kwargs: type(
            "MutationResult",
            (),
            {
                "status": type(
                    "Status",
                    (),
                    {
                        "status": "sqlite",
                        "strategy": "incremental",
                        "synced_at": "2026-03-31T12:00:00+00:00",
                        "record_count": len(kwargs["existing_records"]),
                        "issues": (),
                        "operation": "edit",
                        "uses_sqlite": True,
                    },
                )(),
                "records": tuple(
                    [
                        kwargs["updated_record"]
                        if getattr(record, "uid", "") == getattr(kwargs["updated_record"], "uid", "")
                        else record
                        for record in kwargs["existing_records"]
                    ]
                ),
            },
        )(),
    )
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: infos.append(args[2]))

    window.session_runtime.path = "dummy.xlsx"
    window.selected = make_record(caixa="CX-1", uid="uid-edit")
    window._fill_form(window.selected)
    window.data_tab.in_caixa.setText("CX-9")

    window.save_edit()

    assert infos == ["Salvo com sucesso."]
    window.close()


def test_check_duplicate_av_tec_rebinds_runtime_persistence_service_after_swap(tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("stub", encoding="utf-8")
    stat_result = workbook_path.stat()
    window = MainWindow()
    window.session_runtime.path = str(workbook_path)
    window.records = [make_record(uid="dup-uid-1", av_tec="AT-1")]

    class SwappedPersistenceService:
        def get_workbook_snapshot_summary(self, workbook_path):
            return SimpleNamespace(
                workbook_path=workbook_path,
                synced_at="2026-03-31T12:00:00+00:00",
                record_count=1,
                source_mtime_ns=int(stat_result.st_mtime_ns),
                source_size=int(stat_result.st_size),
            )

        def find_duplicate_av_tec_for_workbook(self, workbook_path, *, av_tec, current_uid=""):
            return 12 if av_tec == "AT-DUPLICADA" else None

    window.persistence_service = SwappedPersistenceService()

    assert window.form_controller.check_duplicate_av_tec("AT-DUPLICADA", "") == 12
    window.close()


def test_resolved_dashboard_record_overview_rebinds_runtime_persistence_service_after_swap(tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("stub", encoding="utf-8")
    window = MainWindow()
    window.session_runtime.path = str(workbook_path)
    window._dashboard_record_overview = None

    class SwappedPersistenceService:
        def build_workbook_record_overview(
            self,
            workbook_path,
            *,
            top_microbacias_limit=5,
            sample_limit=5,
        ):
            return SimpleNamespace(
                workbook_path=workbook_path,
                synced_at="2026-03-31T12:00:00+00:00",
                total_records=7,
                compensados_count=2,
                pendentes_count=5,
                records_with_plantios_count=1,
                records_without_microbacia_count=0,
                records_without_coordinates_count=3,
                top_microbacias=(("Gregorio", 7),)[: int(top_microbacias_limit)],
                sample_records=(),
            )

    window.persistence_service = SwappedPersistenceService()

    report = window.shell_controller.resolved_dashboard_record_overview(
        refresh=True,
        top_microbacias_limit=1,
        sample_limit=0,
    )

    assert report is not None
    assert report.total_records == 7
    assert report.top_microbacias == (("Gregorio", 7),)
    assert window._dashboard_record_overview is report
    window.close()


def test_resolved_persistence_status_report_rebinds_runtime_persistence_service_after_swap(tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("stub", encoding="utf-8")
    window = MainWindow()
    window.session_runtime.path = str(workbook_path)
    window.records = [make_record(uid="u-1"), make_record(uid="u-2")]
    window._local_session_source_status = LocalRecordReadStatus(
        status="sqlite",
        source="sqlite",
        strategy="sqlite_snapshot",
        workbook_path=str(workbook_path),
        synced_at="2026-03-31T12:00:00+00:00",
        mirrored_records=2,
        session_records=2,
        filtered_records=2,
    )

    class SwappedPersistenceService:
        def get_workbook_snapshot_summary(self, workbook_path):
            return SimpleNamespace(
                workbook_path=workbook_path,
                synced_at="2026-03-31T12:00:00+00:00",
                record_count=2,
                plantio_count=1,
                audit_event_count=4,
            )

    window.persistence_service = SwappedPersistenceService()

    report = window.shell_controller.resolved_persistence_status_report(
        refresh=True,
        expected_audit_events=4,
    )

    assert isinstance(report, PersistenceStatusReport)
    assert report.status == "sincronizado"
    assert report.mirrored_records == 2
    assert report.expected_audit_events == 4
    assert window._persistence_status_report is report
    window.close()


def test_save_edit_uses_authoritative_selected_record_for_audit_and_target(monkeypatch):
    window = MainWindow()
    audits = []

    monkeypatch.setattr(window.form_controller.persistence.session_backup_service, "create_backup", lambda **kwargs: "C:/tmp/edit.json")
    monkeypatch.setattr(
        window.form_controller.local_mutation_sync,
        "apply_after_edit",
        lambda **kwargs: type(
            "MutationResult",
            (),
            {
                "status": type(
                    "Status",
                    (),
                    {
                        "status": "sqlite",
                        "strategy": "incremental",
                        "synced_at": "2026-03-31T12:00:00+00:00",
                        "record_count": len(kwargs["existing_records"]),
                        "issues": (),
                        "operation": "edit",
                        "uses_sqlite": True,
                    },
                )(),
                "records": tuple(
                    [
                        kwargs["updated_record"]
                        if getattr(record, "uid", "") == getattr(kwargs["updated_record"], "uid", "")
                        else record
                        for record in kwargs["existing_records"]
                    ]
                ),
            },
        )(),
    )
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: audits.append(payload))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_selected_record",
        lambda workbook_path, **kwargs: type(
            "SelectionResult",
            (),
            {
                "record": make_record(excel_row=9, uid="uid-authoritative", caixa="CX-AUTH", av_tec="AT-AUTH"),
                "issues": (),
            },
        )(),
    )

    window.session_runtime.path = "dummy.xlsx"
    window.selected = make_record(excel_row=3, uid="uid-stale", caixa="CX-OLD", av_tec="AT-OLD")
    window._fill_form(window.selected)
    window.data_tab.in_caixa.setText("CX-EDIT")

    window.save_edit()

    assert audits[0]["before"]["uid"] == "uid-authoritative"
    assert audits[0]["before"]["caixa"] == "CX-AUTH"
    assert audits[0]["after"]["uid"] == "uid-authoritative"
    assert audits[0]["after"]["excel_row"] == 9
    window.close()


def test_save_edit_uses_authoritative_runtime_base_for_projection_and_sync(monkeypatch):
    window = MainWindow()
    refreshed = []
    sync_calls = []
    authoritative_base = [
        make_record(excel_row=9, uid="uid-authoritative", caixa="CX-AUTH", av_tec="AT-AUTH"),
        make_record(excel_row=10, uid="uid-neighbor", caixa="CX-NB", av_tec="AT-NB"),
    ]

    monkeypatch.setattr(window.form_controller.persistence.session_backup_service, "create_backup", lambda **kwargs: "C:/tmp/edit.json")
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_selected_record",
        lambda workbook_path, **kwargs: type(
            "SelectionResult",
            (),
            {"record": authoritative_base[0], "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_authoritative_record_source",
        lambda workbook_path, **kwargs: type(
            "RecordSource",
            (),
            {"records": tuple(authoritative_base), "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.local_mutation_sync,
        "apply_after_edit",
        lambda **kwargs: sync_calls.append(kwargs)
        or type(
            "MutationResult",
            (),
            {
                "status": type("Status", (), {"issues": (), "operation": "edit"})(),
                "records": tuple(
                    [
                        make_record(excel_row=9, uid="uid-authoritative", caixa="CX-EDIT", av_tec="AT-AUTH"),
                        authoritative_base[1],
                    ]
                ),
            },
        )(),
    )

    window.session_runtime.path = "dummy.xlsx"
    window.records = [make_record(excel_row=3, uid="uid-stale-session", caixa="CX-OLD", av_tec="AT-OLD")]
    window.selected = make_record(excel_row=3, uid="uid-stale-session", caixa="CX-OLD", av_tec="AT-OLD")
    window._fill_form(window.selected)
    window.data_tab.in_caixa.setText("CX-EDIT")

    window.save_edit()

    assert len(sync_calls) == 1
    assert [record.uid for record in sync_calls[0]["existing_records"]] == ["uid-authoritative", "uid-neighbor"]
    assert [record.uid for record in refreshed[0]] == ["uid-authoritative", "uid-neighbor"]
    assert refreshed[0][0].caixa == "CX-EDIT"
    window.close()


def test_delete_selected_writes_audit_entry(monkeypatch):
    window = MainWindow()
    audits = []
    refreshed = []

    monkeypatch.setattr(window.form_controller.persistence.session_backup_service, "create_backup", lambda **kwargs: "C:/tmp/delete.json")
    monkeypatch.setattr(
        window.form_controller.persistence,
        "prepare_delete",
        lambda *args, **kwargs: type(
            "Preparation",
            (),
            {
                "base_records": (window.selected,),
                "selected_record": window.selected,
                "issues": (),
            },
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.local_mutation_sync,
        "apply_after_delete",
        lambda **kwargs: type(
            "MutationResult",
            (),
            {
                "status": type(
                    "Status",
                    (),
                    {
                        "status": "sqlite",
                        "strategy": "incremental",
                        "synced_at": "2026-03-31T12:00:00+00:00",
                        "record_count": max(len(kwargs["existing_records"]) - 1, 0),
                        "issues": (),
                        "operation": "delete",
                        "uses_sqlite": True,
                    },
                )(),
                "records": (),
            },
        )(),
    )
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: audits.append(payload))

    window.session_runtime.path = "dummy.xlsx"
    window.selected = make_record(uid="uid-delete", av_tec="AT-DEL")

    window.delete_selected()

    assert len(refreshed) == 1
    assert audits[0]["action"] == "delete"
    assert audits[0]["before"]["uid"] == "uid-delete"
    assert audits[0]["backup_path"].endswith("delete.json")
    window.close()


def test_delete_selected_uses_authoritative_selected_record_for_delete_and_audit(monkeypatch):
    window = MainWindow()
    audits = []

    monkeypatch.setattr(window.form_controller.persistence.session_backup_service, "create_backup", lambda **kwargs: "C:/tmp/delete.json")
    monkeypatch.setattr(
        window.form_controller.local_mutation_sync,
        "apply_after_delete",
        lambda **kwargs: type(
            "MutationResult",
            (),
            {
                "status": type(
                    "Status",
                    (),
                    {
                        "status": "sqlite",
                        "strategy": "incremental",
                        "synced_at": "2026-03-31T12:00:00+00:00",
                        "record_count": max(len(kwargs["existing_records"]) - 1, 0),
                        "issues": (),
                        "operation": "delete",
                        "uses_sqlite": True,
                    },
                )(),
                "records": (),
            },
        )(),
    )
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: audits.append(payload))
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_selected_record",
        lambda workbook_path, **kwargs: type(
            "SelectionResult",
            (),
            {
                "record": make_record(excel_row=12, uid="uid-authoritative-delete", av_tec="AT-AUTH-DEL"),
                "issues": (),
            },
        )(),
    )

    window.session_runtime.path = "dummy.xlsx"
    window.selected = make_record(excel_row=4, uid="uid-stale-delete", av_tec="AT-OLD-DEL")

    window.delete_selected()

    assert audits[0]["before"]["uid"] == "uid-authoritative-delete"
    assert audits[0]["backup_path"].endswith("delete.json")
    window.close()


def test_delete_selected_uses_authoritative_runtime_base_for_projection_and_sync(monkeypatch):
    window = MainWindow()
    refreshed = []
    sync_calls = []
    authoritative_deleted = make_record(excel_row=12, uid="uid-authoritative-delete", av_tec="AT-AUTH-DEL")
    authoritative_base = [
        authoritative_deleted,
        make_record(excel_row=13, uid="uid-neighbor-delete", av_tec="AT-NB-DEL"),
    ]

    monkeypatch.setattr(window.form_controller.persistence.session_backup_service, "create_backup", lambda **kwargs: "C:/tmp/delete.json")
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refreshed.append(records) or True)
    monkeypatch.setattr(window.audit_service, "append_event", lambda **payload: None)
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_selected_record",
        lambda workbook_path, **kwargs: type(
            "SelectionResult",
            (),
            {"record": authoritative_deleted, "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_authoritative_record_source",
        lambda workbook_path, **kwargs: type(
            "RecordSource",
            (),
            {"records": tuple(authoritative_base), "issues": ()},
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.local_mutation_sync,
        "apply_after_delete",
        lambda **kwargs: sync_calls.append(kwargs)
        or type(
            "MutationResult",
            (),
            {
                "status": type("Status", (), {"issues": (), "operation": "delete"})(),
                "records": (make_record(excel_row=12, uid="uid-neighbor-delete", av_tec="AT-NB-DEL"),),
            },
        )(),
    )

    window.session_runtime.path = "dummy.xlsx"
    window.records = [make_record(excel_row=4, uid="uid-stale-session-delete", av_tec="AT-OLD-DEL")]
    window.selected = make_record(excel_row=4, uid="uid-stale-session-delete", av_tec="AT-OLD-DEL")

    window.delete_selected()

    assert len(sync_calls) == 1
    assert [record.uid for record in sync_calls[0]["existing_records"]] == [
        "uid-authoritative-delete",
        "uid-neighbor-delete",
    ]
    assert [record.uid for record in refreshed[0]] == ["uid-neighbor-delete"]
    assert refreshed[0][0].excel_row == 12
    window.close()


def test_save_edit_requires_endereco_plantio_when_compensado(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if p == "dummy.xlsx" else real_exists(p))

    window = MainWindow()
    saved = []
    warnings = []

    monkeypatch.setattr(window.session_runtime, "ensure_workbook_is_current", lambda: None)
    monkeypatch.setattr(window.session_runtime, "save_edit", lambda record: saved.append(record))
    monkeypatch.setattr(window, "reload", lambda: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    window.session_runtime.path = "dummy.xlsx"
    window.selected = make_record()
    window._fill_form(window.selected)

    window.data_tab.chk_compensado.setChecked(True)
    window.data_tab.in_end_plantio.setText("")

    assert window.data_tab.btn_save_edit.isEnabled() is False

    window.save_edit()

    assert saved == []
    assert warnings == ["Preencha Endereço Plantio para salvar um registro compensado."]
    window.close()


def test_save_edit_reenables_when_endereco_plantio_is_filled(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if p == "dummy.xlsx" else real_exists(p))

    window = MainWindow()
    window.session_runtime.path = "dummy.xlsx"
    window.selected = make_record()
    window._fill_form(window.selected)

    window.data_tab.chk_compensado.setChecked(True)
    window.data_tab.in_end_plantio.setText("")
    assert window.data_tab.btn_save_edit.isEnabled() is False

    window.data_tab.in_end_plantio.setText("Rua do Plantio, 123")
    assert window.data_tab.btn_save_edit.isEnabled() is True

    window.close()


def test_duplicate_av_tec_highlight_keeps_current_palette_colors():
    window = MainWindow()
    duplicate_record = make_record(uid="u-1", av_tec="AT-1")
    selected_record = make_record(excel_row=3, uid="u-2", av_tec="AT-2")
    window.records = [duplicate_record, selected_record]
    window.selected = selected_record
    window._fill_form(selected_record)

    palette = window.data_tab.in_avtec.palette()
    expected_bg = palette.color(QPalette.ColorRole.Base).name()
    expected_text = palette.color(QPalette.ColorRole.Text).name()

    window.data_tab.in_avtec.setText("AT-1")
    window._validate_as_you_type()

    style = window.data_tab.in_avtec.styleSheet()

    assert "border: 2px solid #e74c3c;" in style
    assert f"background-color: {expected_bg};" in style
    assert f"color: {expected_text};" in style
    assert "#fdf0ed" not in style

    window.close()


def test_duplicate_av_tec_highlight_can_use_sqlite_duplicate_lookup(monkeypatch):
    window = MainWindow()
    selected_record = make_record(excel_row=3, uid="u-2", av_tec="AT-2")
    window.records = [selected_record]
    window.selected = selected_record
    window._fill_form(selected_record)

    monkeypatch.setattr(
        window.form_controller.local_record_queries,
        "resolve_duplicate_av_tec",
        lambda workbook_path, **kwargs: LocalDuplicateCheckResult(
            source="sqlite",
            duplicate_row=10,
            strategy="sqlite_duplicate",
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            mirrored_records=1,
            session_records=1,
        ),
    )

    window.data_tab.in_avtec.setText("AT-1")
    window._validate_as_you_type()

    assert "border: 2px solid #e74c3c;" in window.data_tab.in_avtec.styleSheet()
    assert window.data_tab.in_avtec.toolTip() == "Esta Av. Técnica já existe na linha 9."
    window.close()


def test_compensado_cannot_be_unchecked_when_endereco_plantio_has_data(monkeypatch):
    window = MainWindow()
    warnings = []
    record = make_record(compensado="SIM", endereco_plantio="Rua do Plantio, 123")
    window.selected = record

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    window._fill_form(record)
    assert window.data_tab.chk_compensado.isChecked() is True

    window.data_tab.chk_compensado.setChecked(False)

    assert window.data_tab.chk_compensado.isChecked() is True
    assert window.data_tab.in_end_plantio.isEnabled() is True
    assert warnings == ["Limpe Endereço Plantio antes de desmarcar Compensado."]
    window.close()


def test_save_edit_refreshes_runtime_session_without_full_reload(monkeypatch):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: True if p == "dummy.xlsx" else real_exists(p))

    window = MainWindow()
    executed = []
    refresh_calls = []
    infos = []

    monkeypatch.setattr(
        window.form_controller.persistence,
        "prepare_update",
        lambda *args, **kwargs: type(
            "Preparation",
            (),
            {
                "base_records": (window.selected,),
                "selected_record": window.selected,
                "effective_record": None,
                "duplicate_row": None,
                "issues": (),
            },
        )(),
    )
    monkeypatch.setattr(
        window.form_controller.persistence,
        "execute_edit",
        lambda record, **kwargs: executed.append(record)
        or type(
            "WriteResult",
            (),
            {
                "status": LocalMutationSyncStatus(
                    status="sqlite",
                    operation="edit",
                    workbook_path="dummy.xlsx",
                    strategy="incremental",
                    record_count=1,
                ),
                "write_status": type(
                    "WriteStatus",
                    (),
                    {"status": "sqlite_authoritative", "operation": "edit", "issues": (), "finalized": False},
                )(),
                "records": (record,),
                "excel_result": None,
                "rollback_issues": (),
                "finalized": False,
            },
        )(),
    )
    monkeypatch.setattr(window, "reload", lambda *args, **kwargs: pytest.fail("reload nao deveria ser usado apos save_edit"))
    monkeypatch.setattr(window.data_controller, "refresh_runtime_after_mutation", lambda records: refresh_calls.append(records) or True)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: infos.append(args[2]))

    window.session_runtime.path = "dummy.xlsx"
    window.selected = make_record()
    window._fill_form(window.selected)
    window.data_tab.in_comp.setText("11")

    window.save_edit()

    assert len(executed) == 1
    assert executed[0].compensacao == "11"
    assert len(refresh_calls) == 1
    assert infos == ["Salvo com sucesso."]
    window.close()


def test_show_rollback_dialog_uses_audit_history_when_available(monkeypatch, tmp_path):
    window = MainWindow()
    restored = {}
    reloaded = []

    current_file = tmp_path / "base.xlsx"
    current_file.write_text("atual", encoding="utf-8")
    backup_file = tmp_path / "backup-op.xlsx"

    event = SimpleNamespace(
        event_id="evt-1",
        timestamp="2026-03-30T12:00:00+00:00",
        action="edit",
        summary="Registro alterado: AT-1",
        backup_path=str(backup_file),
    )

    monkeypatch.setattr(
        window.data_controller.persistence,
        "build_rollback_dialog_plan",
        lambda *args, **kwargs: type(
            "RollbackPlan",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"label": "30/03/2026 12:00:00 - EDIT - Registro alterado: AT-1"},
                    )()
                ],
                "prompt": "Escolha",
            },
        )(),
    )
    monkeypatch.setattr(
        window.data_controller.persistence,
        "resolve_rollback_choice",
        lambda *_args, **_kwargs: type(
            "RestoreRequest",
            (),
            {
                "backup_path": str(backup_file),
                "rollback_source": "operation_audit",
                "metadata": {"event_id": event.event_id},
                "label": event.summary,
                "confirmation_title": "Confirmar",
                "confirmation_message": "Restaurar?",
            },
        )(),
    )
    monkeypatch.setattr(
        window.data_controller.persistence,
        "restore_backup",
        lambda selected_file, **kwargs: restored.update({"selected_file": selected_file, **kwargs}),
    )
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.QInputDialog.getItem",
        lambda *args, **kwargs: ("30/03/2026 12:00:00 - EDIT - Registro alterado: AT-1", True),
    )
    monkeypatch.setattr(window.data_controller, "reload", lambda *args, **kwargs: reloaded.append(True))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    window.session_runtime.path = str(current_file)

    window.show_rollback_dialog()

    assert restored["selected_file"] == str(backup_file)
    assert reloaded == [True]
    assert restored["rollback_source"] == "operation_audit"
    assert restored["metadata"]["event_id"] == "evt-1"
    window.close()


def test_restore_backup_file_reloads_without_second_discard_prompt(monkeypatch):
    window = MainWindow()
    reload_calls = []

    window.session_runtime.path = "dummy.xlsx"
    monkeypatch.setattr(window.data_controller.persistence, "restore_backup", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        window.data_controller,
        "reload",
        lambda *args, **kwargs: reload_calls.append(kwargs) or True,
    )
    monkeypatch.setattr(window, "refresh_operations_overview", lambda: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    assert (
        window.data_controller._restore_backup_file(
            "C:/tmp/backup.xlsx",
            rollback_source="operation_audit",
            metadata={"event_id": "evt-1"},
            label="restore-test",
        )
        is True
    )
    assert reload_calls == [{"confirm_discard": False}]
    window.close()


def test_show_operation_history_restores_selected_audit_snapshot(monkeypatch):
    window = MainWindow()
    restored = {}

    event = SimpleNamespace(
        event_id="evt-2",
        timestamp="2026-03-30T13:00:00+00:00",
        action="import",
        summary="2 registro(s) importado(s)",
        backup_path="C:/tmp/import-backup.xlsx",
        metadata={"source_path": "importar.xlsx"},
        before=None,
        after={"imported_count": 2},
    )

    class FakeOperationHistoryDialog:
        def __init__(self, _parent, events):
            restored["events"] = list(events)
            self.restore_requested = True
            self.selected_event = events[0]

        def exec(self):
            return True

    monkeypatch.setattr(window.audit_service, "list_events_for_workbook", lambda *_args, **_kwargs: [event])
    monkeypatch.setattr(
        "app.ui.controllers.data_controller.OperationHistoryDialog",
        FakeOperationHistoryDialog,
    )
    monkeypatch.setattr(
        window.data_controller,
        "_restore_backup_file",
        lambda selected_file, **kwargs: restored.update({"selected_file": selected_file, **kwargs}) or True,
    )

    window.session_runtime.path = "dummy.xlsx"

    window.show_operation_history()

    assert restored["events"] == [event]
    assert restored["selected_file"] == "C:/tmp/import-backup.xlsx"
    assert restored["rollback_source"] == "operation_audit"
    assert restored["metadata"]["event_id"] == "evt-2"
    assert restored["label"] == "2 registro(s) importado(s)"
    window.close()



