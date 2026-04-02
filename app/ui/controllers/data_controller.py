import json
import os
from typing import Dict, List, Optional, Tuple, cast

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from app.application.use_cases.local_mutation_sync import LocalMutationSyncUseCases
from app.application.use_cases.workbook_commands import (
    WorkbookImportFlowUseCases,
    WorkbookRecoveryUseCases,
)
from app.application.use_cases.recovery_operations import RecoveryOperationsUseCases
from app.application.use_cases.local_record_queries import LocalRecordQueriesUseCases, LocalRecordReadResult
from app.application.use_cases.local_write_authority import LocalWriteAuthorityUseCases
from app.application.use_cases.workbook_session import WorkbookSessionUseCases
from app.config import SEARCH_FILTER_DEBOUNCE_MS
from app.models.compensacao import Compensacao
from app.services.error_service import friendly_error_message
from app.services.excel_service import ExcelService
from app.services.gis_service import GisService
from app.services.records_service import (
    build_record_search_index,
    compute_metrics,
    display_tipo_value,
)
from app.ui.components.dialogs import ImportPreviewDialog, OperationHistoryDialog
from app.ui.components.job_specs import BlockingJobSpec
from app.ui.components.ui_utils import msg_confirm
from app.utils.logger import get_logger


logger = get_logger("UI.Data")


class DataController:
    def __init__(self, window):
        self.window = window
        self.workbook_use_cases = WorkbookSessionUseCases(window.excel, loader_factory=ExcelService)
        self.import_use_cases = WorkbookImportFlowUseCases(
            self.workbook_use_cases,
            window.excel,
            window.audit_service,
        )
        self.recovery_use_cases = WorkbookRecoveryUseCases(window.excel, window.audit_service)
        self.recovery_operations = RecoveryOperationsUseCases(self.recovery_use_cases, window.audit_service)
        self.persistence_use_cases = getattr(window, "persistence_monitoring_use_cases", None)
        self.local_record_queries = LocalRecordQueriesUseCases(getattr(window, "persistence_service", None))
        self.local_mutation_sync = LocalMutationSyncUseCases(getattr(window, "persistence_service", None))
        self.local_write_authority = LocalWriteAuthorityUseCases(self.local_record_queries)
        self.filter_timer = QTimer(window)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self.apply_filter)

    def schedule_apply_filter(self):
        self.filter_timer.start(SEARCH_FILTER_DEBOUNCE_MS)

    def snapshot_excel_service_state(self) -> Dict[str, object]:
        return {
            "path": self.window.excel.path,
            "wb": self.window.excel.wb,
            "ws": self.window.excel.ws,
            "plantio_ws": self.window.excel.plantio_ws,
            "col_map": dict(self.window.excel.col_map),
            "plantio_col_map": dict(self.window.excel.plantio_col_map),
            "uid_to_row": dict(self.window.excel.uid_to_row),
            "last_backup_time": self.window.excel.last_backup_time,
            "merged_cells_warning": self.window.excel.merged_cells_warning,
        }

    def restore_excel_service_state(self, snapshot: Dict[str, object]):
        self.window.excel.path = snapshot["path"]
        self.window.excel.wb = snapshot["wb"]
        self.window.excel.ws = snapshot["ws"]
        self.window.excel.plantio_ws = snapshot.get("plantio_ws")
        self.window.excel.col_map = dict(cast(Dict[str, int], snapshot["col_map"]))
        self.window.excel.plantio_col_map = dict(cast(Dict[str, int], snapshot.get("plantio_col_map", {})))
        self.window.excel.uid_to_row = dict(cast(Dict[str, int], snapshot["uid_to_row"]))
        self.window.excel.last_backup_time = snapshot["last_backup_time"]
        self.window.excel.merged_cells_warning = snapshot["merged_cells_warning"]

    def snapshot_filter_state(self) -> Dict[str, object]:
        return {
            "search_text": self.window.search.text(),
            "status": self.window.data_tab.filter_status.currentText(),
            "year": self.window.data_tab.filter_year.currentText(),
            "micro_all_selected": self.window.data_tab.filter_micro.is_all_selected(),
            "selected_micros": list(self.window.data_tab.filter_micro.checked_items()),
            "eletronico_all_selected": self.window.data_tab.filter_eletronico.is_all_selected(),
            "selected_eletronicos": list(self.window.data_tab.filter_eletronico.checked_items()),
        }

    def restore_filter_state(self, state: Dict[str, object]):
        self.window.search.blockSignals(True)
        self.window.data_tab.filter_status.blockSignals(True)
        self.window.data_tab.filter_year.blockSignals(True)
        self.window.data_tab.filter_micro.blockSignals(True)
        self.window.data_tab.filter_eletronico.blockSignals(True)
        try:
            self.window.search.setText(str(state.get("search_text", "")))

            status = str(state.get("status", "Todos"))
            status_index = self.window.data_tab.filter_status.findText(status)
            self.window.data_tab.filter_status.setCurrentIndex(status_index if status_index >= 0 else 0)

            year = str(state.get("year", "Todos"))
            year_index = self.window.data_tab.filter_year.findText(year)
            self.window.data_tab.filter_year.setCurrentIndex(year_index if year_index >= 0 else 0)

            self.window.data_tab.filter_micro.set_checked_items(
                list(cast(List[str], state.get("selected_micros", []))),
                all_selected=bool(state.get("micro_all_selected", True)),
            )
            self.window.data_tab.filter_eletronico.set_checked_items(
                [display_tipo_value(value) for value in cast(List[str], state.get("selected_eletronicos", []))],
                all_selected=bool(state.get("eletronico_all_selected", True)),
            )
        finally:
            self.window.search.blockSignals(False)
            self.window.data_tab.filter_status.blockSignals(False)
            self.window.data_tab.filter_year.blockSignals(False)
            self.window.data_tab.filter_micro.blockSignals(False)
            self.window.data_tab.filter_eletronico.blockSignals(False)

    def clear_loaded_data_state(self):
        self.window.session_controller.clear_workbook_state()
        self.window.gis = None
        self.window._local_record_read_status = None
        self.window._local_session_source_status = None
        self.window._local_filter_facets_status = None
        self.window._local_mutation_sync_status = None
        self.window._filtered_metrics = None

        empty_metrics = compute_metrics([])
        self.window.data_tab.table.clearSelection()
        self.window.data_tab.table_model.update_data([])
        self.window.data_tab.update_totals_tables(empty_metrics)
        self.window.dash_tab.update_dashboard(
            empty_metrics,
            self.window.is_dark_mode,
            [],
            self.window._dashboard_record_overview,
            self.window._local_record_read_status,
        )
        self.window.data_tab.lbl_results.setText("0 registros")
        self.window._update_filters_from_records()
        self.window._setup_dynamic_form_options_from_records()
        self.window.clear_form(force=True)
        self.window.statusBar().showMessage("Nenhuma planilha carregada")
        self.window._refresh_window_chrome()
        self.window.refresh_operations_overview()

    def restore_previous_state(
        self,
        previous_records: List[Compensacao],
        previous_filtered: List[Compensacao],
        previous_selected: Optional[Compensacao],
        previous_marker: Optional[Tuple[float, float]],
        previous_filter_state: Dict[str, object],
    ):
        previous_snapshot = self.window.session_controller.snapshot()
        previous_snapshot.records = list(previous_records)
        previous_snapshot.filtered_records = list(previous_filtered)
        previous_snapshot.selected = previous_selected
        previous_snapshot.last_marker_coords = previous_marker
        previous_snapshot.record_search_index = build_record_search_index(previous_records)
        self.window.session_controller.restore(previous_snapshot)

        if self.window.records:
            self.update_ui_after_load()
            self.restore_filter_state(previous_filter_state)
            self.apply_filter()
            self.window._load_sort_settings()
            self.window._refresh_window_chrome()
            if self.window.selected is not None:
                self.window._fill_form(previous_selected)
                self.window._update_form_action_buttons()
                self.window._update_address_search_enabled()
        else:
            self.clear_loaded_data_state()

    def load_excel(self, path: str, confirm_discard: bool = True):
        if confirm_discard and self.window.excel.path and self.window.form_controller.has_pending_changes():
            if not self.window.form_controller.confirm_discard_changes("carregar outra planilha"):
                return False

        logger.info(f"Tentando carregar planilha: {path}")
        previous_session_snapshot = self.window.session_controller.snapshot()
        previous_records = list(previous_session_snapshot.records)
        previous_filtered = list(previous_session_snapshot.filtered_records)
        previous_selected = previous_session_snapshot.selected
        previous_marker = previous_session_snapshot.last_marker_coords
        previous_filter_state = self.snapshot_filter_state()
        previous_service_state = self.snapshot_excel_service_state()
        previous_recent_files = list(previous_session_snapshot.recent_files)

        try:
            load_result = self.window.run_blocking_spec(
                BlockingJobSpec(
                    name="load_workbook",
                    busy_message="Carregando planilha...",
                    operation=lambda: self.workbook_use_cases.load_workbook(path),
                    success_message="Planilha carregada.",
                    failure_message="Falha ao carregar planilha.",
                )
            )
            self.window.records = load_result.records
            self.window._record_search_index = build_record_search_index(self.window.records)
            logger.info(f"ExcelService.load retornou {len(self.window.records)} registros.")
            if not self.window.records:
                logger.warning("Atencao: A planilha foi lida mas retornou 0 registros.")

            self.window.settings_controller.save_last_excel_path(path)
            self.window.settings_controller.update_recent_files(path)
            self._sync_workbook_snapshot()
            self._hydrate_loaded_record_source(load_result.records)
            self._apply_loaded_runtime_state(self.window.records, sync_snapshot=False)
            self.window._load_sort_settings()
            logger.info("Interface atualizada com sucesso apos carga de dados.")
            return True
        except Exception as exc:
            self.restore_excel_service_state(previous_service_state)
            previous_session_snapshot.recent_files = list(previous_recent_files)
            self.window.session_controller.restore(previous_session_snapshot)
            self.window.settings_controller.restore_recent_files(previous_recent_files)
            self.window.settings_controller.clear_last_excel_path()
            self.restore_previous_state(
                previous_records,
                previous_filtered,
                previous_selected,
                previous_marker,
                previous_filter_state,
            )
            logger.error(f"Erro fatal ao carregar {path}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "abrir a planilha")
            QMessageBox.critical(self.window, title, message)
            return False

    def open_excel(self):
        initial_dir = self.window.settings_controller.preferred_excel_dialog_dir()
        path, _ = QFileDialog.getOpenFileName(self.window, "Abrir Excel", initial_dir, "Excel (*.xlsx)")
        if path and self.load_excel(path):
            QMessageBox.information(self.window, "Sucesso", f"Carregado: {len(self.window.records)} registros.")

    def load_last_excel(self):
        path = self.window.settings_controller.restore_last_excel_path()
        logger.info(f"Path recuperado do QSettings: {path}")
        if path and os.path.exists(path):
            if not self.load_excel(path, confirm_discard=False):
                self.window.settings_controller.clear_last_excel_path()
        else:
            if path:
                self.window.settings_controller.clear_last_excel_path()
            logger.warning("Nenhum path anterior encontrado ou arquivo inexistente.")

    def _hydrate_loaded_record_source(self, fallback_records: List[Compensacao]) -> None:
        record_source = self.local_record_queries.resolve_record_source(
            str(getattr(self.window.excel, "path", "") or ""),
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
        preparation = self.local_write_authority.prepare_base(
            str(getattr(self.window.excel, "path", "") or ""),
            fallback_records=self.window.records,
        )
        if preparation.issues:
            logger.warning(
                "Base autoritativa da importacao consultada com fallback/local issues: %s",
                " | ".join(preparation.issues),
            )
        return list(preparation.base_records)

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
            record_source = self.local_record_queries.resolve_record_source(
                str(getattr(self.window.excel, "path", "") or ""),
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
                "Falha ao atualizar sessao a partir do espelho local apos mutacao: %s",
                exc,
                exc_info=True,
            )
            self.window._local_session_source_status = self.local_record_queries.build_read_status(
                LocalRecordReadResult(
                    source="session",
                    records=tuple(projected_records),
                    strategy="session_filter",
                    workbook_path=str(getattr(self.window.excel, "path", "") or ""),
                    session_records=len(projected_records),
                    issues=(f"Falha ao atualizar sessao apos mutacao: {exc}",),
                ),
                filtered_records=len(projected_records),
            )
            self._apply_loaded_runtime_state(list(projected_records), sync_snapshot=False)
            return True

    def _sync_workbook_snapshot(self):
        persistence_service = getattr(self.window, "persistence_service", None)
        workbook_path = str(getattr(self.window.excel, "path", "") or "").strip()
        if not workbook_path:
            self.window._dashboard_record_overview = None
            return
        if persistence_service is None:
            self._refresh_dashboard_record_overview()
            return

        try:
            persistence_service.sync_workbook_snapshot(workbook_path, self.window.records)
            self._refresh_dashboard_record_overview()
        except Exception as exc:
            logger.warning("Falha ao sincronizar espelho local em SQLite: %s", exc, exc_info=True)
            self.window._dashboard_record_overview = None

    def _refresh_dashboard_record_overview(self):
        workbook_path = str(getattr(self.window.excel, "path", "") or "").strip()
        if not workbook_path or self.persistence_use_cases is None:
            self.window._dashboard_record_overview = None
            return

        try:
            self.window._dashboard_record_overview = self.persistence_use_cases.build_record_overview_report(
                workbook_path,
                top_microbacias_limit=3,
                sample_limit=0,
            )
        except Exception as exc:
            logger.warning("Falha ao montar resumo local do dashboard: %s", exc, exc_info=True)
            self.window._dashboard_record_overview = None

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
                f"if(window.setStatus) window.setStatus({json.dumps('Mapa de microbacias indisponivel no momento.')});",
                "gis-load-failure-status",
            )
            return False

    def update_dashboard_view(self, metrics: Dict[str, object]):
        return self.window.navigation_controller.update_dashboard(metrics)

    def on_tab_changed(self, _index: int):
        return self.window.navigation_controller.on_tab_changed(_index)

    def apply_filter(self):
        record_source = self.local_record_queries.resolve_filtered_record_source(
            str(getattr(self.window.excel, "path", "") or ""),
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
        self.window.data_tab._resize_column_to_texts(
            self.window.data_tab.OFICIO_COLUMN_INDEX,
            [record.oficio_processo for record in self.window.records],
        )
        self.window.data_tab._resize_column_to_texts(
            self.window.data_tab.TIPO_COLUMN_INDEX,
            ["Eletrônico", "Ofício", "Físico", "Nulo"]
            + [display_tipo_value(record.eletronico) for record in self.window.records],
        )
        metrics = dict(self.window._filtered_metrics or compute_metrics(self.window.filtered_records))
        self.update_dashboard_view(metrics)
        self.window.data_tab.update_totals_tables(metrics)
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
        if self.window.excel.path:
            if confirm_discard and not self.window.form_controller.confirm_discard_changes("recarregar a planilha"):
                return False
            return self.load_excel(self.window.excel.path, confirm_discard=False)
        return False

    def _build_import_validation_message(self, analysis) -> str:
        lines = [
            f"A importacao foi interrompida porque {analysis.total_invalid} registro(s) novo(s) apresentam problemas.",
            "",
        ]
        for issue in analysis.invalid_issues[:5]:
            identifier = issue.av_tec or issue.uid or "sem identificacao"
            lines.append(f"- Linha {issue.import_row}: {identifier} - {issue.message}")
        remaining = analysis.total_invalid - min(len(analysis.invalid_issues), 5)
        if remaining > 0:
            lines.append(f"- ... e mais {remaining} registro(s).")
        lines.extend(["", "Corrija a planilha de origem e tente novamente."])
        return "\n".join(lines)

    def _append_import_conflict_preview(self, lines: List[str], title: str, details) -> None:
        if not details:
            return
        lines.extend(["", title])
        for detail in list(details)[:3]:
            identifier = detail.av_tec or detail.uid or "sem identificacao"
            matched_suffix = f" (ja existe na linha {detail.matched_row})" if detail.matched_row else ""
            lines.append(f"- Linha {detail.import_row}: {identifier}{matched_suffix}")
        remaining = len(details) - min(len(details), 3)
        if remaining > 0:
            lines.append(f"- ... e mais {remaining} conflito(s).")

    def _build_import_preview_message(self, analysis) -> str:
        lines = [
            f"Foram analisados {analysis.total_incoming} registros da planilha selecionada.",
            "",
            f"Novos para importar: {analysis.total_new_records}",
            f"Ignorados por UID ja existente: {analysis.skipped_by_uid}",
            f"Ignorados por Av. Tec. ja existente: {analysis.skipped_by_av_tec}",
        ]
        self._append_import_conflict_preview(lines, "Exemplos de conflito por UID:", analysis.skipped_uid_details)
        self._append_import_conflict_preview(lines, "Exemplos de conflito por Av. Tec.:", analysis.skipped_av_tec_details)
        lines.extend(["", f"Deseja continuar com a importacao dos {analysis.total_new_records} registro(s) novo(s)?"])
        return "\n".join(lines)

    def _build_audited_rollback_options(self):
        if not self.window.excel.path:
            return [], {}, "Selecione uma operacao anterior para restaurar a planilha:"

        options: list[str] = []
        backup_map: dict[str, tuple[str, str, dict[str, object]]] = {}
        for option in self.recovery_use_cases.build_audited_rollback_options(self.window.excel.path):
            backup_map[option.label] = (
                option.backup_path,
                option.source_type,
                dict(option.metadata),
            )
            options.append(option.label)

        return options, backup_map, self.recovery_use_cases.AUDITED_PROMPT

    def _restore_backup_file(
        self,
        selected_file: str,
        *,
        rollback_source: str,
        metadata: Dict[str, object],
        label: str,
    ) -> bool:
        if not self.window.excel.path:
            return False

        try:
            self.recovery_use_cases.restore_backup(
                selected_file,
                rollback_source=rollback_source,
                metadata=metadata,
                label=label,
            )
            self.reload()
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
        if not self.window.excel.path:
            QMessageBox.warning(self.window, "Aviso", "Abra uma planilha primeiro para consultar o historico.")
            return

        history_plan = self.recovery_operations.build_operation_history_plan(self.window.excel.path, limit=200)
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

        request = self.recovery_operations.build_restore_request_for_event(dialog.selected_event)
        if not msg_confirm(self.window, request.confirmation_title, request.confirmation_message):
            return

        self._restore_backup_file(
            request.backup_path,
            rollback_source=request.rollback_source,
            metadata=request.metadata,
            label=request.label,
        )

    def import_excel_data(self):
        if not self.window.excel.path:
            QMessageBox.warning(self.window, "Aviso", "Abra a planilha base primeiro.")
            return

        initial_dir = self.window.settings_controller.preferred_excel_dialog_dir()
        path, _ = QFileDialog.getOpenFileName(self.window, "Importar Planilha", initial_dir, "Excel (*.xlsx)")
        if not path:
            return

        if path == self.window.excel.path:
            QMessageBox.warning(self.window, "Aviso", "Voce selecionou o mesmo arquivo ja aberto.")
            return

        try:
            self.window.excel.ensure_workbook_is_current()
            base_records = self._resolve_authoritative_import_base_records()
            analysis = self.window.run_blocking_spec(
                BlockingJobSpec(
                    name="analyze_import",
                    busy_message="Analisando arquivo para importacao...",
                    operation=lambda: self.workbook_use_cases.analyze_import(base_records, path),
                    success_message="Analise concluida.",
                    failure_message="Falha na analise da importacao.",
                )
            )

            if analysis.total_invalid:
                ImportPreviewDialog(self.window, analysis).exec()
                self.window.statusBar().showMessage("Importacao interrompida por registros invalidos")
                return
            if not analysis.records_to_add:
                skipped_message = ""
                if analysis.total_skipped:
                    skipped_message = f" ({analysis.total_skipped} ja existentes)"
                QMessageBox.information(
                    self.window,
                    "Importacao",
                    f"Nenhum registro novo encontrado para importar{skipped_message}.",
                )
                self.window.statusBar().showMessage("Importacao concluida sem adicoes")
                return
        except Exception as exc:
            logger.error(f"Erro na importacao de {path}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "importar a planilha")
            QMessageBox.critical(self.window, title, message)
            self.window.statusBar().showMessage("Falha na importacao")
            return

        to_add = analysis.records_to_add
        preview_dialog = ImportPreviewDialog(self.window, analysis)
        if not preview_dialog.exec():
            self.window.statusBar().showMessage("Importacao cancelada")
            return

        try:
            def on_progress(current: int, _total: int):
                self.window.update_busy_operation(current, f"Importando registros... {current}/{len(to_add)}")

            result = self.window.run_blocking_spec(
                BlockingJobSpec(
                    name="execute_import",
                    busy_message="Importando registros...",
                    operation=lambda: self.import_use_cases.execute_import(analysis, progress_callback=on_progress),
                    total=len(to_add),
                    success_message="Importacao concluida.",
                    failure_message="Falha na importacao.",
                )
            )
            mutation_result = self.local_mutation_sync.apply_after_import(
                workbook_path=str(getattr(self.window.excel, "path", "") or ""),
                existing_records=base_records,
                imported_records=result.imported_records,
            )
            self.window._local_mutation_sync_status = mutation_result.status
            if getattr(self.window._local_mutation_sync_status, "issues", ()):
                logger.warning(
                    "Falha ao sincronizar importacao no espelho local: %s",
                    " | ".join(self.window._local_mutation_sync_status.issues),
                )
            self.refresh_runtime_after_mutation(list(mutation_result.records))
            QMessageBox.information(
                self.window,
                "Sucesso",
                f"{result.imported_count} registros importados com sucesso!",
            )
            logger.info(f"Importados {result.imported_count} registros de {path}")
        except Exception as exc:
            logger.error(f"Erro na importacao de {path}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "importar a planilha")
            QMessageBox.critical(self.window, title, message)
            self.window.statusBar().showMessage("Falha na importacao")

    def show_rollback_dialog(self):
        if not self.window.excel.path:
            QMessageBox.warning(self.window, "Aviso", "Abra uma planilha primeiro para ver seus backups.")
            return

        rollback_plan = self.recovery_operations.build_rollback_dialog_plan(self.window.excel.path)
        if not rollback_plan.choices:
            QMessageBox.information(self.window, "Backups", self.recovery_operations.build_no_backup_message())
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
            request = self.recovery_operations.resolve_rollback_choice(rollback_plan, item)
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
