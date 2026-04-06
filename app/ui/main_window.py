import os
import sys
from typing import List, Optional, Tuple, Dict

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QApplication, QMainWindow,
)

# --- Imports do Projeto ---
from app.config import APP_WINDOW_TITLE, APP_SETTINGS_NAME, APP_SETTINGS_ORG
from app.application.use_cases.authoritative_persistence import AuthoritativePersistenceUseCases
from app.application.use_cases.persistence_monitoring import PersistenceMonitoringUseCases
from app.models.compensacao import Compensacao
from app.services.access_service import AppAccessSession
from app.services.app_settings import AppSettings
from app.services.audit_service import AuditService
from app.services.session_spreadsheet_adapter import ExternalSpreadsheetAdapter
from app.services.session_workbook_runtime import SessionWorkbookRuntime
from app.services.sqlite_mirror_service import SqliteMirrorService
from app.services.sqlite_mirror_service import SqliteMirrorService as DirectSqliteMirrorService
from app.services.coordinates import build_heatmap_point, build_heatmap_points
from app.services.gis_service import GisService

# --- Componentes Modularizados ---
from app.ui.controllers.data_controller import DataController
from app.ui.controllers.export_controller import ExportController
from app.ui.controllers.form_controller import FormController
from app.ui.controllers.map_controller import MapController
from app.ui.controllers.operations_controller import OperationsController
from app.ui.controllers.settings_controller import SettingsController
from app.ui.controllers.support_controller import SupportController
from app.ui.controllers.window_lifecycle_controller import WindowLifecycleController
from app.ui.controllers.window_navigation_controller import WindowNavigationController
from app.ui.controllers.window_command_controller import WindowCommandController
from app.ui.controllers.window_session_controller import WindowSessionController
from app.ui.controllers.window_shell_controller import WindowShellController
from app.ui.components.job_runner import WindowJobRunner
from app.ui.components.job_specs import BackgroundJobSpec, BlockingJobSpec
from app.ui.components.ui_utils import resource_path, _ajustar_ambiente_pyinstaller
from app.ui.components.workers import UpdaterWorker
from app.ui.main_window_support import (
    apply_window_icon,
    apply_window_scaling,
    build_runtime_bundle,
    configure_window_class_registry,
)
from app.ui.tabs.data_tab import DataTab
from app.ui.tabs.dashboard_tab import DashboardTab
from app.ui.tabs.operations_tab import OperationsTab
from app.ui.tabs.tcra_tab import TcraTab
from app.utils.logger import get_logger

_ajustar_ambiente_pyinstaller()

logger = get_logger("UI.MainWindow")

msg_confirm = None

MICROB_NAME_FIELD = "Nome_Do_Arquivo"
MICROB_DIR = resource_path("data", "microbacias")

class MainWindow(QMainWindow):
    def __init__(self, access_session: AppAccessSession | None = None):
        super().__init__()
        self.access_session = access_session or AppAccessSession.local_default()
        self.setWindowTitle(APP_WINDOW_TITLE)
        configure_window_class_registry(
            self,
            data_tab_cls=DataTab,
            dashboard_tab_cls=DashboardTab,
            operations_tab_cls=OperationsTab,
            tcra_tab_cls=TcraTab,
            updater_cls=UpdaterWorker,
            microb_name_field=MICROB_NAME_FIELD,
            microb_dir=MICROB_DIR,
        )
        apply_window_scaling(self, QApplication.instance())
        apply_window_icon(self, resource_path("assets", "app.ico"))

        self.import_adapter_factory = ExternalSpreadsheetAdapter
        self.external_data_adapter_factory = self.import_adapter_factory
        self.is_dark_mode = False
        settings_name = self.access_session.settings_name(APP_SETTINGS_NAME)
        persistence_service_factory = SqliteMirrorService
        if self.access_session.local_db_path:
            target_db_path = os.fspath(self.access_session.local_db_path)
            persistence_service_factory = lambda: DirectSqliteMirrorService(db_path=target_db_path)
        runtime_bundle = build_runtime_bundle(
            settings_factory=AppSettings,
            qsettings_factory=QSettings,
            qsettings_org=APP_SETTINGS_ORG,
            qsettings_name=settings_name,
            loader_factory=self.external_data_adapter_factory,
            session_runtime_cls=SessionWorkbookRuntime,
            persistence_service_factory=persistence_service_factory,
            audit_service_cls=AuditService,
            monitoring_use_cases_cls=PersistenceMonitoringUseCases,
            authoritative_persistence_cls=AuthoritativePersistenceUseCases,
            logger=logger,
        )
        self.settings = runtime_bundle.settings
        self.session_runtime = runtime_bundle.session_runtime
        self.persistence_service = runtime_bundle.persistence_service
        self.audit_service = runtime_bundle.audit_service
        self.authoritative_persistence = runtime_bundle.authoritative_persistence
        self.persistence_monitoring_use_cases = runtime_bundle.persistence_monitoring_use_cases
        self.gis: Optional[GisService] = None
        self.geo_worker = None
        self._startup_window_state_applied = False
        self._startup_layout_pending = False
        self._startup_geometry_restored = False
        self._skip_close_discard_confirmation = False

        self.session_controller = WindowSessionController(self)
        self.navigation_controller = WindowNavigationController(self)
        self.lifecycle_controller = WindowLifecycleController(self)
        self.lifecycle_controller.initialize_timers()
        self.shell_controller = WindowShellController(self)
        self._setup_ui()
        self.job_runner = WindowJobRunner(self)
        self.settings_controller = SettingsController(self)
        self.export_controller = ExportController(self)
        self.form_controller = FormController(self)
        self.data_controller = DataController(self)
        self.map_controller = MapController(self)
        self.operations_controller = OperationsController(self)
        self.support_controller = SupportController(self)
        self.command_controller = WindowCommandController(self)
        self.lifecycle_controller.bind_runtime_hooks()
        self.lifecycle_controller.finalize_initialization()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.lifecycle_controller.handle_resize()

    def begin_busy_operation(
        self,
        message: str,
        *,
        total: Optional[int] = None,
        cancellable: bool = False,
        cancel_callback=None,
    ):
        self.job_runner.begin_busy_operation(
            message,
            total=total,
            cancellable=cancellable,
            cancel_callback=cancel_callback,
        )

    def update_busy_operation(self, value: int, message: Optional[str] = None):
        self.job_runner.update_busy_operation(value, message)

    def end_busy_operation(self, message: str = "Pronto"):
        self.job_runner.end_busy_operation(message)

    def run_blocking_job(
        self,
        busy_message: str,
        operation,
        *,
        total: Optional[int] = None,
        cancellable: bool = False,
        cancel_callback=None,
        success_message: str = "Pronto",
        failure_message: str = "Opera\u00e7\u00e3o interrompida.",
    ):
        return self.job_runner.run_blocking(
            busy_message,
            operation,
            total=total,
            cancellable=cancellable,
            cancel_callback=cancel_callback,
            success_message=success_message,
            failure_message=failure_message,
        )

    def run_blocking_spec(self, spec: BlockingJobSpec):
        return self.job_runner.run_blocking_spec(spec)

    def cancel_active_operation(self):
        return self.job_runner.cancel_active_operation()

    def track_background_worker(
        self,
        name: str,
        worker,
        *,
        disconnect_callbacks=None,
        stop_callback=None,
        wait_ms: int = 1000,
    ):
        return self.job_runner.track_worker(
            name,
            worker,
            disconnect_callbacks=disconnect_callbacks,
            stop_callback=stop_callback,
            wait_ms=wait_ms,
        )

    def release_background_worker(self, name: str):
        return self.job_runner.release_worker(name)

    def start_background_job(self, spec: BackgroundJobSpec):
        return self.job_runner.start_background_job(spec)

    def mark_job_completed(self, name: str, message: str = "Pronto"):
        return self.job_runner.mark_job_completed(name, message)

    def mark_job_failed(self, name: str, message: str):
        return self.job_runner.mark_job_failed(name, message)

    def mark_job_cancelled(self, name: str, message: str):
        return self.job_runner.mark_job_cancelled(name, message)

    def list_runtime_jobs(self, *, limit: int = 20):
        return self.job_runner.list_runtime_jobs(limit=limit)

    @property
    def records(self) -> List[Compensacao]:
        return self.session_controller.state.records

    @records.setter
    def records(self, value: List[Compensacao]):
        self.session_controller.state.records = list(value)

    @property
    def filtered_records(self) -> List[Compensacao]:
        return self.session_controller.state.filtered_records

    @filtered_records.setter
    def filtered_records(self, value: List[Compensacao]):
        self.session_controller.state.filtered_records = list(value)

    @property
    def selected(self) -> Optional[Compensacao]:
        return self.session_controller.state.selected

    @selected.setter
    def selected(self, value: Optional[Compensacao]):
        self.session_controller.state.selected = value

    @property
    def form_plantios(self) -> List[object]:
        return self.session_controller.state.form_plantios

    @form_plantios.setter
    def form_plantios(self, value: List[object]):
        self.session_controller.state.form_plantios = list(value)

    @property
    def last_marker_coords(self) -> Optional[Tuple[float, float]]:
        return self.session_controller.state.last_marker_coords

    @last_marker_coords.setter
    def last_marker_coords(self, value: Optional[Tuple[float, float]]):
        self.session_controller.state.last_marker_coords = value

    @property
    def recent_files(self) -> List[str]:
        return self.session_controller.state.recent_files

    @recent_files.setter
    def recent_files(self, value: List[str]):
        self.session_controller.state.recent_files = list(value)

    @property
    def _record_search_index(self) -> Dict[str, str]:
        return self.session_controller.state.record_search_index

    @_record_search_index.setter
    def _record_search_index(self, value: Dict[str, str]):
        self.session_controller.state.record_search_index = dict(value)

    @property
    def _local_record_read_status(self):
        return self.session_controller.state.local_record_read_status

    @_local_record_read_status.setter
    def _local_record_read_status(self, value):
        self.session_controller.state.local_record_read_status = value

    @property
    def _local_session_source_status(self):
        return self.session_controller.state.local_session_source_status

    @_local_session_source_status.setter
    def _local_session_source_status(self, value):
        self.session_controller.state.local_session_source_status = value

    @property
    def _local_filter_facets_result(self):
        return self.session_controller.state.local_filter_facets_result

    @_local_filter_facets_result.setter
    def _local_filter_facets_result(self, value):
        self.session_controller.state.local_filter_facets_result = value

    @property
    def _local_filter_facets_status(self):
        return self.session_controller.state.local_filter_facets_status

    @_local_filter_facets_status.setter
    def _local_filter_facets_status(self, value):
        self.session_controller.state.local_filter_facets_status = value

    @property
    def _local_mutation_sync_status(self):
        return self.session_controller.state.local_mutation_sync_status

    @_local_mutation_sync_status.setter
    def _local_mutation_sync_status(self, value):
        self.session_controller.state.local_mutation_sync_status = value

    @property
    def _authoritative_write_status(self):
        return self.session_controller.state.authoritative_write_status

    @_authoritative_write_status.setter
    def _authoritative_write_status(self, value):
        self.session_controller.state.authoritative_write_status = value

    @property
    def _filtered_metrics(self) -> Optional[Dict[str, object]]:
        return self.session_controller.state.filtered_metrics

    @_filtered_metrics.setter
    def _filtered_metrics(self, value: Optional[Dict[str, object]]):
        self.session_controller.state.filtered_metrics = dict(value) if value is not None else None

    @property
    def _persistence_status_report(self):
        return self.session_controller.state.persistence_status_report

    @_persistence_status_report.setter
    def _persistence_status_report(self, value):
        self.session_controller.state.persistence_status_report = value

    @property
    def _dashboard_dirty(self) -> bool:
        return self.session_controller.state.dashboard_dirty

    @_dashboard_dirty.setter
    def _dashboard_dirty(self, value: bool):
        self.session_controller.state.dashboard_dirty = bool(value)

    @property
    def _pending_dashboard_metrics(self) -> Optional[Dict[str, object]]:
        return self.session_controller.state.pending_dashboard_metrics

    @_pending_dashboard_metrics.setter
    def _pending_dashboard_metrics(self, value: Optional[Dict[str, object]]):
        self.session_controller.state.pending_dashboard_metrics = dict(value) if value is not None else None

    @property
    def _dashboard_record_overview(self):
        return self.session_controller.state.dashboard_record_overview

    @_dashboard_record_overview.setter
    def _dashboard_record_overview(self, value):
        self.session_controller.state.dashboard_record_overview = value

    def schedule_apply_filter(self):
        return self.data_controller.schedule_apply_filter()

    def _on_map_click(self, lat, lon):
        return self.map_controller.on_map_click(lat, lon)

    def _set_map_marker(self, lat, lon):
        return self.map_controller.set_map_marker(lat, lon)

    def _highlight_microbacia(self, name: str):
        return self.map_controller.highlight_microbacia(name)

    def _set_map_status(self, message: str):
        return self.map_controller.set_map_status(message)

    def _fill_form(self, record):
        return self.form_controller.fill_form(record)

    def _check_duplicate_av_tec(self, av_tec: str, current_uid: str):
        return self.form_controller.check_duplicate_av_tec(av_tec, current_uid)

    def _read_form(self):
        return self.form_controller.read_form()

    def edit_plantios(self):
        return self.command_controller.edit_plantios()

    def add_new(self):
        return self.command_controller.add_new()

    def save_edit(self):
        return self.command_controller.save_edit()

    def delete_selected(self):
        return self.command_controller.delete_selected()

    def reload(self, confirm_discard: bool = True):
        return self.command_controller.reload(confirm_discard=confirm_discard)

    def clear_form(self, force: bool = False):
        return self.command_controller.clear_form(force=force)

    def search_on_map(self):
        return self.command_controller.search_on_map()

    def search_on_map_plantio(self):
        return self.command_controller.search_on_map_plantio()

    def _perform_geocode(self, address: str):
        return self.map_controller.perform_geocode(address)

    def _record_needs_batch_geocode(self, record):
        return self.map_controller.record_needs_batch_geocode(record)

    def _persist_batch_geocode_results(self, results):
        return self.map_controller.persist_batch_geocode_results(results)

    def run_batch_geocode(self):
        return self.command_controller.run_batch_geocode()

    def on_geocode_finished(self, results):
        return self.map_controller.on_geocode_finished(results)

    def toggle_heatmap(self):
        return self.command_controller.toggle_heatmap()

    def _build_heatmap_point(self, record, mode):
        return build_heatmap_point(record, mode)

    def _build_heatmap_points(self, record, mode):
        return build_heatmap_points(record, mode)

    def show_about_dialog(self):
        return self.command_controller.show_about_dialog()

    def show_operation_history(self):
        return self.command_controller.show_operation_history()

    def refresh_operations_overview(self):
        return self.command_controller.refresh_operations_overview()

    def open_selected_operation_backup(self):
        return self.command_controller.open_selected_operation_backup()

    def open_logs_folder(self):
        return self.command_controller.open_logs_folder()

    def export_diagnostics(self):
        return self.command_controller.export_diagnostics()

    def check_for_updates(self):
        return self.command_controller.check_for_updates()

    def present_update_offer(self, *args, **kwargs):
        return self.command_controller.present_update_offer(*args, **kwargs)

    def _prompt_update(self, version: str, notes: str):
        return self.lifecycle_controller.prompt_update(version, notes)

    def _setup_ui(self):
        return self.shell_controller.setup_ui()

    def _current_file_label_text(self) -> str:
        return self.shell_controller.current_file_label_text()

    def _current_records_label_text(self) -> str:
        return self.shell_controller.current_records_label_text()

    def _current_selection_label_text(self) -> str:
        return self.shell_controller.current_selection_label_text()

    def _refresh_window_chrome(self):
        return self.shell_controller.refresh_window_chrome()

    def _setup_menus(self):
        return self.shell_controller.setup_menus()

    def _connect_signals(self):
        return self.shell_controller.connect_signals()

    def _setup_shortcuts(self):
        return self.shell_controller.setup_shortcuts()

    def _on_form_field_changed(self):
        return self.shell_controller.on_form_field_changed()

    def _validate_as_you_type(self):
        return self.shell_controller.validate_as_you_type()

    def _is_form_dirty(self) -> bool:
        return self.shell_controller.is_form_dirty()

    def _update_address_search_enabled(self):
        return self.shell_controller.update_address_search_enabled()

    def _on_chk_sn_toggled(self, checked):
        return self.shell_controller.on_chk_sn_toggled(checked)

    def _on_chk_arquivado_toggled(self, checked):
        return self.shell_controller.on_chk_arquivado_toggled(checked)

    def _finalize_startup_layout(self):
        return self.shell_controller.finalize_startup_layout()

    def _apply_theme(self):
        return self.shell_controller.apply_theme()

    def _apply_theme_to_map(self):
        return self.shell_controller.apply_theme_to_map()

    def _update_filters_from_records(self):
        return self.shell_controller.update_filters_from_records()

    def _setup_dynamic_form_options_from_records(self):
        return self.shell_controller.setup_dynamic_form_options_from_records()

    def open_columns_dialog(self):
        return self.command_controller.open_columns_dialog()

    def _on_table_clicked(self, index):
        return self.shell_controller.on_table_clicked(index)

    def _delete_selected_from_table_shortcut(self):
        return self.command_controller.delete_selected_from_table_shortcut()

    def _get_visible_column_attrs(self) -> List[str]:
        return self.shell_controller.get_visible_column_attrs()

    # Legacy implementations removed after controller migration.

    def _update_recent_files_menu(self):
        return self.settings_controller.update_recent_files_menu()

    def _snapshot_session_runtime_state(self) -> Dict[str, object]:
        return self.data_controller.snapshot_session_runtime_state()

    def _restore_session_runtime_state(self, snapshot: Dict[str, object]):
        return self.data_controller.restore_session_runtime_state(snapshot)

    def _metrics_to_kpi_rows(self, metrics: Dict[str, object]) -> List[Tuple[str, str]]:
        return self.export_controller.metrics_to_kpi_rows(metrics)

    def _build_filter_summary(self) -> str:
        return self.export_controller.build_filter_summary()

    def _snapshot_filter_state(self) -> Dict[str, object]:
        return self.data_controller.snapshot_filter_state()

    def _restore_filter_state(self, state: Dict[str, object]):
        return self.data_controller.restore_filter_state(state)

    def _clear_loaded_data_state(self):
        return self.data_controller.clear_loaded_data_state()

    def _restore_previous_state(
        self,
        previous_records: List[Compensacao],
        previous_filtered: List[Compensacao],
        previous_selected: Optional[Compensacao],
        previous_marker: Optional[Tuple[float, float]],
        previous_filter_state: Dict[str, object],
    ):
        return self.data_controller.restore_previous_state(
            previous_records,
            previous_filtered,
            previous_selected,
            previous_marker,
            previous_filter_state,
        )

    def open_street_view(self):
        return self.command_controller.open_street_view()

    def load_custom_layer(self):
        return self.command_controller.load_custom_layer()

    def show_rollback_dialog(self):
        return self.command_controller.show_rollback_dialog()

    def import_external_data(self):
        return self.data_controller.import_external_data()

    def new_session(self):
        return self.command_controller.new_session()

    def _update_form_action_buttons(self):
        return self.form_controller.update_form_action_buttons()

    def _on_map_loaded(self, ok):
        return self.map_controller.on_map_loaded(ok)

    def _initial_map_sync(self):
        return self.map_controller.initial_map_sync()

    def _load_settings(self):
        return self.settings_controller.load_settings()

    def _apply_startup_window_state(self):
        return self.settings_controller.apply_startup_window_state()

    def toggle_theme(self):
        return self.command_controller.toggle_theme()

    def _load_session(self, path, confirm_discard: bool = True):
        return self.data_controller.load_session(path, confirm_discard=confirm_discard)

    def _load_session_source(self, path, confirm_discard: bool = True):
        return self._load_session(path, confirm_discard=confirm_discard)

    def open_session(self):
        return self.command_controller.open_session()

    def _load_last_session(self):
        return self.data_controller.load_last_session()

    def _load_last_session_source(self):
        return self.data_controller.load_last_session()

    def _load_sort_settings(self):
        return self.settings_controller.load_sort_settings()

    def _save_sort_settings(self):
        return self.settings_controller.save_sort_settings()

    def _update_ui_after_load(self):
        return self.data_controller.update_ui_after_load()

    def _load_gis(self):
        return self.data_controller.load_gis()

    def _update_dashboard_view(self, metrics: Dict[str, object]):
        return self.navigation_controller.update_dashboard(metrics)

    def _on_tab_changed(self, index: int):
        return self.navigation_controller.on_tab_changed(index)

    def _load_microbacias_layer(self):
        return self.map_controller.load_microbacias_layer()

    def _run_map_js(self, script: str, context: str):
        return self.map_controller.run_map_js(script, context)

    def apply_filter(self):
        return self.data_controller.apply_filter()

    def clear_filters(self):
        return self.command_controller.clear_filters()

    def reset_sorting(self):
        return self.command_controller.reset_sorting()

    def open_table_fullscreen(self):
        return self.command_controller.open_table_fullscreen()

    def open_map_fullscreen(self):
        return self.command_controller.open_map_fullscreen()

    def save_map_layer_preference(self, layer_name):
        return self.settings_controller.save_map_layer_preference(layer_name)

    def export_csv_clicked(self):
        return self.command_controller.export_csv_clicked()

    def export_spreadsheet_clicked(self):
        return self.command_controller.export_spreadsheet_clicked()

    def export_pdf_clicked(self):
        return self.command_controller.export_pdf_clicked()

    def export_ficha_pdf(self):
        return self.command_controller.export_ficha_pdf()

    def export_dashboard_pdf_clicked(self):
        return self.command_controller.export_dashboard_pdf_clicked()

    def _get_save_path(self, title, filter):
        return self.export_controller.get_save_path(title, filter)

    def closeEvent(self, event):
        if not self.lifecycle_controller.prepare_close(event):
            return
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

