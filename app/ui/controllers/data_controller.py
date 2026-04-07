import json
import os
import time
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QInputDialog, QMessageBox

from app.application.use_cases.authoritative_persistence import AuthoritativePersistenceUseCases
from app.application.use_cases.local_record_queries import LocalRecordReadResult
from app.application.use_cases.authoritative_persistence_write_support import (
    generate_unique_uid,
    next_excel_row,
)
from app.application.use_cases.session_startup_use_cases import build_singleton_session_startup_plan
from app.application.use_cases.authoritative_persistence_support import build_remote_snapshot_refresh_result
from app.config import SEARCH_FILTER_DEBOUNCE_MS
from app.models.compensacao import Compensacao
from app.services.access_service import AccessEnvironment
from app.services.error_service import friendly_error_message
from app.services.gis_service import GisService
from app.services.records_service import (
    build_record_search_index,
    compute_metrics,
    display_tipo_value,
)
from app.services.session_spreadsheet_adapter import ExternalSpreadsheetAdapter
from app.ui.components.dialogs import OperationHistoryDialog
from app.ui.components.job_specs import BlockingJobSpec
from app.ui.controllers.data_controller_support import (
    FilterStateSnapshot,
    PreviousDataState,
    capture_previous_data_state,
    clear_loaded_data_view,
    reset_authoritative_runtime_state,
    restore_filter_state_snapshot,
    restore_previous_session_snapshot,
    build_filter_state_snapshot,
)
from app.ui.components.ui_utils import msg_confirm
from app.utils.logger import get_logger


logger = get_logger("UI.Data")

class DataController:
    NEW_SESSION_OPTION = "+ Nova sess\u00e3o..."
    REMOTE_OPERATIONAL_REFRESH_INTERVAL_SECONDS = 60.0

    def __init__(self, window):
        self.window = window
        session_runtime = getattr(window, "session_runtime", None)
        import_adapter_factory = (
            getattr(window, "external_data_adapter_factory", None)
            or getattr(window, "import_adapter_factory", None)
            or ExternalSpreadsheetAdapter
        )
        self.persistence = getattr(window, "authoritative_persistence", None) or AuthoritativePersistenceUseCases(
            session_runtime,
            window.audit_service,
            getattr(window, "persistence_service", None),
            loader_factory=import_adapter_factory,
        )
        self.persistence_use_cases = getattr(window, "persistence_monitoring_use_cases", None)
        self.local_record_queries = self.persistence.local_record_queries
        self.local_mutation_sync = self.persistence.local_mutation_sync
        self.local_write_authority = self.persistence.local_write_authority
        self.authoritative_write = self.persistence.authoritative_write
        self._last_remote_operational_refresh_monotonic = 0.0
        self.filter_timer = QTimer(window)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self.apply_filter)

    def _runtime_workbook(self):
        return getattr(self.window, "session_runtime", None)

    def _current_session_path(self) -> str:
        if hasattr(self.window, "shell_controller"):
            return self.window.shell_controller.current_session_path()
        runtime = self._runtime_workbook()
        if runtime is None:
            return ""
        return str(
            getattr(runtime, "session_path", getattr(runtime, "path", "")) or ""
        ).strip()

    @staticmethod
    def _is_named_session_path(path: str) -> bool:
        return str(path or "").strip().lower().startswith("session://")

    def schedule_apply_filter(self):
        self.filter_timer.start(SEARCH_FILTER_DEBOUNCE_MS)

    def snapshot_session_runtime_state(self):
        return self.persistence.snapshot_workbook_service_state()

    def restore_session_runtime_state(self, snapshot) -> None:
        self.persistence.restore_workbook_service_state(snapshot)

    def _reset_authoritative_runtime_state(self) -> None:
        reset_authoritative_runtime_state(self.window)

    def _bind_runtime_persistence_service(self) -> None:
        self.persistence.set_persistence_service(getattr(self.window, "persistence_service", None))

    def snapshot_filter_state(self) -> Dict[str, object]:
        return build_filter_state_snapshot(self.window).to_dict()

    def restore_filter_state(self, state: Dict[str, object]):
        restore_filter_state_snapshot(
            self.window,
            FilterStateSnapshot.from_mapping(state),
            display_tipo_value,
        )

    def clear_loaded_data_state(self):
        clear_loaded_data_view(self.window, compute_metrics([]))

    def restore_previous_state(
        self,
        previous_records: List[Compensacao],
        previous_filtered: List[Compensacao],
        previous_selected: Optional[Compensacao],
        previous_marker: Optional[Tuple[float, float]],
        previous_filter_state: Dict[str, object],
    ):
        previous_state = PreviousDataState(
            session_snapshot=self.window.session_controller.snapshot(),
            records=tuple(previous_records),
            filtered_records=tuple(previous_filtered),
            selected=previous_selected,
            last_marker_coords=previous_marker,
            filter_state=FilterStateSnapshot.from_mapping(previous_filter_state),
            runtime_state=None,
            recent_files=tuple(self.window.recent_files),
        )
        restore_previous_session_snapshot(
            self.window,
            previous_state,
            build_search_index=build_record_search_index,
        )

        if self.window.records:
            self.update_ui_after_load()
            self.restore_filter_state(previous_state.filter_state.to_dict())
            self.apply_filter()
            self.window._load_sort_settings()
            self.window._refresh_window_chrome()
            if self.window.selected is not None:
                self.window._fill_form(previous_selected)
                self.window._update_form_action_buttons()
                self.window._update_address_search_enabled()
        else:
            self.clear_loaded_data_state()

    def load_session(self, path: str, confirm_discard: bool = True):
        current_path = (
            self.window.shell_controller.current_session_path()
            if hasattr(self.window, "shell_controller")
            else self._current_session_path()
        )
        if confirm_discard and current_path and self.window.form_controller.has_pending_changes():
            if not self.window.form_controller.confirm_discard_changes("recarregar o banco local"):
                return False

        self._bind_runtime_persistence_service()
        logger.info(f"Tentando carregar banco local: {path}")
        previous_state = capture_previous_data_state(
            self.window,
            runtime_state=self.snapshot_session_runtime_state(),
        )

        try:
            workbook_result = self.window.run_blocking_spec(
                BlockingJobSpec(
                    name="load_session",
                    busy_message="Carregando banco local...",
                    operation=lambda: self.persistence.load_session(path),
                    success_message="Banco local carregado.",
                    failure_message="Falha ao carregar o banco local.",
                )
            )
            loaded_records = list(getattr(workbook_result, "loaded_records", getattr(workbook_result, "records", ())))
            self._reset_authoritative_runtime_state()

            if hasattr(workbook_result, "local_session_source_status"):
                self.window.records = list(getattr(workbook_result, "records", ()))
                self.window._local_session_source_status = getattr(workbook_result, "local_session_source_status", None)
                self._store_remote_snapshot_refresh_status(
                    getattr(workbook_result, "remote_refresh_status", None)
                )
                if getattr(workbook_result, "issues", ()):
                    logger.warning(
                        "Sessao carregada com observacoes apos carga inicial: %s",
                        " | ".join(str(issue) for issue in getattr(workbook_result, "issues", ()) if str(issue).strip()),
                    )
                self._refresh_dashboard_record_overview()
            else:
                self.window.records = loaded_records
                self._sync_workbook_snapshot()
                self._hydrate_loaded_record_source(loaded_records)

            self.window._record_search_index = build_record_search_index(self.window.records)
            logger.info("Runtime de sessão retornou %s registros.", len(self.window.records))
            if not self.window.records:
                logger.warning("Atenção: A sessão foi lida, mas retornou 0 registros.")

            self.window.settings_controller.save_last_session_path(path)
            self.window.settings_controller.update_recent_files(path)
            self._apply_loaded_runtime_state(self.window.records, sync_snapshot=False)
            self.window._load_sort_settings()
            logger.info("Interface atualizada com sucesso apos carga de dados.")
            return True
        except Exception as exc:
            self.restore_session_runtime_state(previous_state.runtime_state)
            restore_previous_session_snapshot(
                self.window,
                previous_state,
                build_search_index=build_record_search_index,
            )
            self.window.settings_controller.restore_recent_files(list(previous_state.recent_files))
            self.window.settings_controller.clear_last_session_path()
            self.restore_previous_state(
                list(previous_state.records),
                list(previous_state.filtered_records),
                previous_state.selected,
                previous_state.last_marker_coords,
                previous_state.filter_state.to_dict(),
            )
            logger.error(f"Erro fatal ao carregar {path}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "abrir a sessão")
            QMessageBox.critical(self.window, title, message)
            return False

    def _hydrate_loaded_record_source(self, fallback_records: List[Compensacao]) -> None:
        self._bind_runtime_persistence_service()
        record_source = self.local_record_queries.resolve_record_source(
            self._current_session_path(),
            fallback_records=fallback_records,
        )
        self.window.records = list(record_source.records)
        self.window._record_search_index = build_record_search_index(self.window.records)
        self.window._local_session_source_status = self.local_record_queries.build_read_status(
            record_source,
            filtered_records=len(self.window.records),
        )
        if record_source.issues:
            logger.warning(
                "Sessao carregada com fallback em memoria apos leitura inicial: %s",
                " | ".join(record_source.issues),
            )

    def _resolve_authoritative_import_base_records(self) -> List[Compensacao]:
        self._bind_runtime_persistence_service()
        preparation = self.local_write_authority.prepare_base(
            self._current_session_path(),
            fallback_records=self.window.records,
        )
        self.persistence.log_preparation_issues("importacao", preparation.issues)
        return list(preparation.base_records)

    @staticmethod
    def _next_excel_row(records: List[Compensacao]) -> int:
        return next_excel_row(records)

    @staticmethod
    def _generate_unique_uid(used_uids: set[str]) -> str:
        return generate_unique_uid(used_uids)

    def _assign_provisional_import_identities(
        self,
        imported_records: List[Compensacao],
        *,
        existing_records: List[Compensacao],
    ) -> None:
        self.persistence.assign_provisional_import_identities(
            imported_records,
            existing_records=existing_records,
        )

    def _store_local_mutation_status(self, status) -> None:
        self.persistence.store_local_mutation_status(self.window, status)

    def _store_authoritative_write_status(self, status) -> None:
        self.persistence.store_authoritative_write_status(self.window, status)

    def _store_remote_snapshot_refresh_status(self, status) -> None:
        self.window._remote_snapshot_refresh_status = status

    def _refresh_operational_surface(self) -> None:
        if hasattr(self.window, "_refresh_window_chrome"):
            self.window._refresh_window_chrome()
        if hasattr(self.window, "refresh_operations_overview"):
            self.window.refresh_operations_overview()

    def update_ui_after_load(self):
        self._apply_loaded_runtime_state(self.window.records, sync_snapshot=True)

    def _apply_loaded_runtime_state(
        self,
        records: List[Compensacao],
        *,
        sync_snapshot: bool,
    ) -> None:
        self.window.records = list(records)
        self.window._record_search_index = build_record_search_index(self.window.records)
        self.window._update_filters_from_records()
        self.window._setup_dynamic_form_options_from_records()
        if sync_snapshot:
            self._sync_workbook_snapshot()
        self.load_gis()
        self.apply_filter()
        self.window.data_tab.align_splitter_to_table_width()
        QTimer.singleShot(0, self.window.data_tab.align_splitter_to_table_width)
        QTimer.singleShot(0, self.window.data_tab._sync_left_panel_heights)
        self.window.data_tab.table.clearSelection()
        self.window.clear_form(force=True)
        self.window.refresh_operations_overview()

    def refresh_runtime_after_mutation(
        self,
        projected_records: List[Compensacao],
    ) -> bool:
        try:
            self._bind_runtime_persistence_service()
            record_source = self.persistence.resolve_runtime_record_source(
                self._current_session_path(),
                fallback_records=projected_records,
            )
            self.window._local_session_source_status = self.local_record_queries.build_read_status(
                record_source,
                filtered_records=len(record_source.records),
            )
            if record_source.issues:
                logger.warning(
                    "Sessao atualizada com fallback em memoria apos mutacao: %s",
                    " | ".join(record_source.issues),
                )
            self._apply_loaded_runtime_state(list(record_source.records), sync_snapshot=False)
            return True
        except Exception as exc:
            logger.warning(
                "Falha ao atualizar sessão a partir do espelho local após mutação: %s",
                exc,
                exc_info=True,
            )
            self.window._local_session_source_status = self.local_record_queries.build_read_status(
                LocalRecordReadResult(
                    source="session",
                    records=tuple(projected_records),
                    strategy="session_filter",
                    workbook_path=self._current_session_path(),
                    session_records=len(projected_records),
                    issues=(f"Falha ao atualizar sessão após mutação: {exc}",),
                ),
                filtered_records=len(projected_records),
            )
            self._apply_loaded_runtime_state(list(projected_records), sync_snapshot=False)
            return True

    def _sync_workbook_snapshot(self):
        persistence_service = getattr(self.window, "persistence_service", None)
        self._bind_runtime_persistence_service()
        if not self.persistence.current_session_path():
            self.window._persistence_status_report = None
            self.window._dashboard_record_overview = None
            return
        if persistence_service is None:
            self.window._persistence_status_report = None
            self._refresh_dashboard_record_overview()
            return

        try:
            self.persistence.sync_workbook_snapshot(self.window.records)
            self._refresh_dashboard_record_overview()
        except Exception as exc:
            logger.warning("Falha ao sincronizar espelho local em SQLite: %s", exc, exc_info=True)
            self.window._persistence_status_report = None
            self.window._dashboard_record_overview = None

    def _refresh_dashboard_record_overview(self):
        if hasattr(self.window, "shell_controller"):
            self.window.shell_controller.resolved_dashboard_record_overview(
                refresh=True,
                top_microbacias_limit=3,
                sample_limit=0,
            )
            return

        workbook_path = self._current_session_path()
        if not workbook_path or self.persistence_use_cases is None:
            self.window._dashboard_record_overview = None
            return

        self._bind_runtime_persistence_service()
        self.window._dashboard_record_overview = self.persistence.resolve_dashboard_record_overview(
            workbook_path,
            cached_report=getattr(self.window, "_dashboard_record_overview", None),
            refresh=True,
            top_microbacias_limit=3,
            sample_limit=0,
        )

    def load_gis(self):
        self.window.gis = None
        empty_geojson = {"type": "FeatureCollection", "features": []}
        unavailable_message = "Microbacias indisponiveis no momento. O cadastro e as exportacoes continuam funcionando."
        if not os.path.isdir(self.window.MICROB_DIR):
            logger.warning(f"Diretorio de microbacias nao encontrado: {self.window.MICROB_DIR}")
            self.window.data_tab.set_map_notice(unavailable_message)
            self.window._run_map_js(
                f"if(window.setMicrobacias) window.setMicrobacias({json.dumps(empty_geojson)});",
                "clear-microbacias-missing-dir",
            )
            return False

        try:
            self.window.gis = GisService(self.window.MICROB_DIR, self.window.MICROB_NAME_FIELD)
            self.window.data_tab.set_map_notice("")
            self.window._load_microbacias_layer()
            self.window._update_filters_from_records()
            self.window._setup_dynamic_form_options_from_records()
            return True
        except Exception as exc:
            self.window.gis = None
            logger.warning(f"Falha ao carregar microbacias: {exc}", exc_info=True)
            self.window.data_tab.set_map_notice(unavailable_message)
            self.window._run_map_js(
                f"if(window.setMicrobacias) window.setMicrobacias({json.dumps(empty_geojson)});",
                "clear-microbacias-load-failure",
            )
            self.window._run_map_js(
                f"if(window.setStatus) window.setStatus({json.dumps('Mapa de microbacias indisponível no momento.')});",
                "gis-load-failure-status",
            )
            return False

    def update_dashboard_view(self, metrics: Dict[str, object]):
        return self.window.navigation_controller.update_dashboard(metrics)

    def on_tab_changed(self, _index: int):
        return self.window.navigation_controller.on_tab_changed(_index)

    def apply_filter(self):
        workbook_path = (
            self.window.shell_controller.current_session_path()
            if hasattr(self.window, "shell_controller")
            else self._current_session_path()
        )
        record_source = self.local_record_queries.resolve_filtered_record_source(
            workbook_path,
            fallback_records=self.window.records,
            text=self.window.search.text(),
            status=self.window.data_tab.filter_status.currentText(),
            selected_micros=self.window.data_tab.filter_micro.checked_items(),
            selected_eletronicos=self.window.data_tab.filter_eletronico.checked_items(),
            micro_all_selected=self.window.data_tab.filter_micro.is_all_selected(),
            eletronico_all_selected=self.window.data_tab.filter_eletronico.is_all_selected(),
            selected_year=self.window.data_tab.filter_year.currentText(),
            fallback_search_index=self.window._record_search_index,
        )
        self.window.filtered_records = list(record_source.records)
        self.window._filtered_metrics = dict(record_source.metrics or compute_metrics(self.window.filtered_records))
        self.window._local_record_read_status = self.local_record_queries.build_read_status(
            record_source,
            filtered_records=len(self.window.filtered_records),
        )
        self.window.data_tab.table_model.update_data(self.window.filtered_records)
        resize_records = list(self.window.filtered_records or self.window.records)
        self.window.data_tab.resize_table_columns_for_records(resize_records)
        metrics = (
            self.window.shell_controller.resolved_filtered_metrics()
            if hasattr(self.window, "shell_controller")
            else dict(self.window._filtered_metrics or compute_metrics(self.window.filtered_records))
        )
        self.update_dashboard_view(metrics)
        self.window.data_tab.update_totals_tables(metrics)
        if hasattr(self.window, "shell_controller"):
            self.window.data_tab.lbl_results.setText(self.window.shell_controller.current_results_label_text())
            self.window.statusBar().showMessage(self.window.shell_controller.current_filter_status_message_text())
        else:
            self.window.data_tab.lbl_results.setText(f"{len(self.window.filtered_records)} registros")
            self.window.statusBar().showMessage(f"Filtro aplicado: {len(self.window.filtered_records)} registros")
        self.window._refresh_window_chrome()
        self.window.toggle_heatmap()
        self.window.data_tab._sync_left_panel_heights()
        QTimer.singleShot(0, self.window.data_tab._sync_left_panel_heights)

    def clear_filters(self):
        self.window.search.clear()
        self.window.data_tab.filter_status.setCurrentIndex(0)
        self.window.data_tab.filter_year.setCurrentIndex(0)
        self.window.data_tab.filter_micro.select_all()
        self.window.data_tab.filter_eletronico.select_all()
        self.apply_filter()
        self.window.statusBar().showMessage("Filtros limpos")

    def reload(self, confirm_discard: bool = True):
        workbook_path = (
            self.window.shell_controller.current_session_path()
            if hasattr(self.window, "shell_controller")
            else self._current_session_path()
        )
        if workbook_path:
            if confirm_discard and not self.window.form_controller.confirm_discard_changes("recarregar a sessão"):
                return False
            return self.load_session(workbook_path, confirm_discard=False)
        return False

    def _restore_backup_file(
        self,
        selected_file: str,
        *,
        rollback_source: str,
        metadata: Dict[str, object],
        label: str,
    ) -> bool:
        workbook_path = (
            self.window.shell_controller.current_session_path()
            if hasattr(self.window, "shell_controller")
            else self._current_session_path()
        )
        if not workbook_path:
            return False

        try:
            self.persistence.restore_backup(
                selected_file,
                rollback_source=rollback_source,
                metadata=metadata,
                label=label,
            )
            self.reload(confirm_discard=False)
            self.window.refresh_operations_overview()
            QMessageBox.information(self.window, "Sucesso", "Backup restaurado com sucesso!")
            logger.info(f"Rollback executado usando arquivo {selected_file}")
            return True
        except Exception as exc:
            logger.error(f"Falha ao restaurar backup {selected_file}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "restaurar o backup")
            QMessageBox.critical(self.window, title, message)
            return False

    def show_operation_history(self):
        workbook_path = (
            self.window.shell_controller.current_session_path()
            if hasattr(self.window, "shell_controller")
            else self._current_session_path()
        )
        if not workbook_path:
            QMessageBox.warning(self.window, "Aviso", "O banco local ainda não está pronto para consultar o histórico.")
            return

        history_plan = self.persistence.build_operation_history_plan(workbook_path, limit=200)
        if not history_plan.events:
            QMessageBox.information(
                self.window,
                history_plan.empty_title,
                history_plan.empty_message,
            )
            return

        dialog = OperationHistoryDialog(self.window, history_plan.events)
        if not dialog.exec() or not dialog.restore_requested or dialog.selected_event is None:
            return

        request = self.persistence.build_restore_request_for_event(dialog.selected_event)
        if not msg_confirm(self.window, request.confirmation_title, request.confirmation_message):
            return

        self._restore_backup_file(
            request.backup_path,
            rollback_source=request.rollback_source,
            metadata=request.metadata,
            label=request.label,
        )

    def _ensure_singleton_database_entry(self):
        return self.persistence.ensure_singleton_session()

    def _bootstrap_singleton_database_from_legacy_source(self, source_path: str) -> bool:
        access_session = getattr(self.window, "access_session", None)
        if getattr(access_session, "environment", None) == AccessEnvironment.PRODUCTION:
            logger.info(
                "Bootstrap legado por planilha ignorado em producao para '%s'.",
                source_path,
            )
            return False

        normalized_source = self.window.settings_controller.restore_legacy_workbook_path() or str(source_path or "").strip()
        if not normalized_source:
            return False

        try:
            target_path = self.window.run_blocking_spec(
                BlockingJobSpec(
                    name="bootstrap_singleton_database",
                    busy_message="Migrando a última planilha para o banco local...",
                    operation=lambda: self.persistence.migrate_legacy_workbook_to_singleton(normalized_source),
                    success_message="Banco local inicializado.",
                    failure_message="Falha ao inicializar o banco local.",
                )
            )
        except Exception as exc:
            logger.warning(
                "Falha ao migrar a base legada '%s' para o banco local único: %s",
                normalized_source,
                exc,
                exc_info=True,
            )
            return False

        loaded = self.load_session(str(target_path or "").strip(), confirm_discard=False)
        if loaded:
            self.window.settings_controller.mark_singleton_bootstrap_completed(normalized_source)
        return loaded

    def _load_singleton_database(self, *, confirm_discard: bool, show_feedback: bool) -> bool:
        try:
            database_entry = self._ensure_singleton_database_entry()
        except Exception as exc:
            logger.error("Falha ao preparar o banco local único: %s", exc, exc_info=True)
            title, message = friendly_error_message(exc, "preparar o banco local")
            QMessageBox.critical(self.window, title, message)
            return False

        current_path = self._current_session_path()
        target_path = str(database_entry.session_path or "").strip()
        already_loaded = bool(
            target_path
            and current_path == target_path
            and (self.window.records or self.persistence.has_local_snapshot(target_path))
        )
        if already_loaded:
            self.refresh_production_snapshot_if_stale(force=True)
            loaded = True
        else:
            loaded = self.load_session(target_path, confirm_discard=confirm_discard)
        if loaded:
            self.window.settings_controller.save_last_session_path(target_path)
            if show_feedback:
                total_records = self._resolved_total_records()
                QMessageBox.information(self.window, "Banco local", f"Banco local pronto: {total_records} registros.")
        return loaded

    def _resolved_total_records(self) -> int:
        if hasattr(self.window, "shell_controller"):
            return int(self.window.shell_controller.resolved_total_records())
        return len(self.window.records)

    def refresh_production_snapshot_if_stale(self, *, force: bool = False) -> bool:
        access_session = getattr(self.window, "access_session", None)
        session_path = self._current_session_path()
        if (
            access_session is None
            or getattr(access_session, "environment", None) != AccessEnvironment.PRODUCTION
            or not session_path
        ):
            self._store_remote_snapshot_refresh_status(None)
            return False

        if self.window.form_controller.has_pending_changes():
            self._store_remote_snapshot_refresh_status(
                build_remote_snapshot_refresh_result(
                    status="deferred",
                    session_path=session_path,
                    issues=("Sincronização pausada: existem alterações pendentes no formulário.",),
                )
            )
            self._refresh_operational_surface()
            return False

        now = time.monotonic()
        if (
            not force
            and (now - float(self._last_remote_operational_refresh_monotonic or 0.0))
            < self.REMOTE_OPERATIONAL_REFRESH_INTERVAL_SECONDS
        ):
            return False

        self._bind_runtime_persistence_service()
        refresh_result = self.window.run_blocking_spec(
            BlockingJobSpec(
                name="refresh_remote_snapshot_if_production",
                busy_message="Sincronizando base oficial...",
                operation=lambda: self.persistence.refresh_remote_snapshot_if_production(session_path),
                success_message="Base oficial sincronizada.",
                failure_message="Falha ao sincronizar a base oficial.",
            )
        )
        self._store_remote_snapshot_refresh_status(refresh_result)
        self._last_remote_operational_refresh_monotonic = now

        if getattr(refresh_result, "refreshed", False):
            record_source = self.persistence.resolve_runtime_record_source(
                session_path,
                fallback_records=self.window.records,
            )
            self.window._local_session_source_status = self.local_record_queries.build_read_status(
                record_source,
                filtered_records=len(record_source.records),
            )
            self._apply_loaded_runtime_state(list(record_source.records), sync_snapshot=False)
            return True

        issues = tuple(getattr(refresh_result, "issues", ()) or ())
        if issues:
            logger.warning(
                "Atualização remota oficial da sessão concluiu com observações: %s",
                " | ".join(str(issue) for issue in issues if str(issue).strip()),
            )
            self.window.statusBar().showMessage(
                " | ".join(str(issue) for issue in issues if str(issue).strip())
            )
        self._refresh_operational_surface()
        return False

    def refresh_production_snapshot(self) -> bool:
        access_session = getattr(self.window, "access_session", None)
        if getattr(access_session, "environment", None) != AccessEnvironment.PRODUCTION:
            QMessageBox.information(
                self.window,
                "Sincronização",
                "A sincronização manual da base oficial só está disponível no ambiente de produção.",
            )
            return False

        if self.window.form_controller.has_pending_changes():
            message = (
                "Salve ou descarte as alterações pendentes antes de sincronizar a base oficial. "
                "Isso evita sobrescrever o formulário com dados mais novos da produção."
            )
            self.window.statusBar().showMessage(message)
            QMessageBox.information(self.window, "Sincronização pausada", message)
            self._store_remote_snapshot_refresh_status(
                build_remote_snapshot_refresh_result(
                    status="deferred",
                    session_path=self._current_session_path(),
                    issues=(message,),
                )
            )
            self._refresh_operational_surface()
            return False

        refreshed = self.refresh_production_snapshot_if_stale(force=True)
        remote_status = getattr(self.window, "_remote_snapshot_refresh_status", None)
        if refreshed:
            synced_at = str(getattr(remote_status, "synced_at", "") or "").strip()
            message = "Base oficial sincronizada com sucesso."
            if synced_at:
                message = f"{message} Última sincronização válida: {synced_at}."
            self.window.statusBar().showMessage(message)
        else:
            issues = tuple(getattr(remote_status, "issues", ()) or ())
            message = (
                " | ".join(str(issue) for issue in issues if str(issue).strip())
                if issues
                else "A sincronização da base oficial não trouxe mudanças novas nesta tentativa."
            )
            self.window.statusBar().showMessage(message)
            QMessageBox.information(self.window, "Sincronização", message)

        self._refresh_operational_surface()
        return refreshed

    def open_session(self):
        return self._load_singleton_database(confirm_discard=True, show_feedback=True)

    def new_session(self):
        return self._load_singleton_database(confirm_discard=True, show_feedback=True)

    def load_last_session(self):
        access_environment = getattr(
            getattr(self.window, "access_session", None),
            "environment",
            AccessEnvironment.LOCAL,
        )
        startup_session_path = str(
            getattr(getattr(self.window, "access_session", None), "local_session_path", "") or ""
        ).strip()
        plan = build_singleton_session_startup_plan(
            pending_legacy_source_path=self.window.settings_controller.pending_singleton_bootstrap_source_path(),
            singleton_session_path=self.window.settings_controller.restore_last_session_path() or startup_session_path,
            allow_legacy_bootstrap=access_environment != AccessEnvironment.PRODUCTION,
        )
        if plan.should_bootstrap_legacy and self._bootstrap_singleton_database_from_legacy_source(plan.source_path):
            return True
        self.window.settings_controller.clear_last_session_path()
        if plan.should_load_singleton:
            return bool(self.load_session(plan.singleton_path, confirm_discard=False))
        return self._load_singleton_database(confirm_discard=False, show_feedback=False)

    def import_external_data(self):
        QMessageBox.information(
            self.window,
            "Importação desativada",
            "A importação externa por planilha foi removida do app. Agora trabalhamos com um banco SQLite único e o Excel fica apenas na exportação de relatórios.",
        )
        self.window.statusBar().showMessage("Importação externa desativada; use o banco local único.")
        return False

    def show_rollback_dialog(self):
        workbook_path = (
            self.window.shell_controller.current_session_path()
            if hasattr(self.window, "shell_controller")
            else self._current_session_path()
        )
        if not workbook_path:
            QMessageBox.warning(self.window, "Aviso", "O banco local ainda não está pronto para mostrar backups.")
            return

        rollback_plan = self.persistence.build_rollback_dialog_plan(workbook_path)
        if not rollback_plan.choices:
            QMessageBox.information(self.window, "Backups", self.persistence.build_no_backup_message())
            return

        options = [choice.label for choice in rollback_plan.choices]

        item, ok = QInputDialog.getItem(
            self.window,
            "Maquina do Tempo",
            rollback_plan.prompt,
            options,
            0,
            False,
        )

        if ok and item:
            request = self.persistence.resolve_rollback_choice(rollback_plan, item)
            if request is not None and msg_confirm(
                self.window,
                request.confirmation_title,
                request.confirmation_message,
            ):
                self._restore_backup_file(
                    request.backup_path,
                    rollback_source=request.rollback_source,
                    metadata=request.metadata,
                    label=request.label,
                )
