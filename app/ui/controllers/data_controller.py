import json
import os
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from app.config import SEARCH_FILTER_DEBOUNCE_MS
from app.services.error_service import friendly_error_message
from app.models.compensacao import Compensacao
from app.services.excel_service import ExcelService
from app.services.gis_service import GisService
from app.services.records_service import (
    build_record_search_index,
    compute_metrics,
    extract_year,
    filter_records,
    unique_non_empty,
)
from app.ui.components.ui_utils import msg_confirm
from app.utils.logger import logger


class DataController:
    def __init__(self, window):
        self.window = window
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
        self.window.excel.col_map = dict(snapshot["col_map"])
        self.window.excel.plantio_col_map = dict(snapshot.get("plantio_col_map", {}))
        self.window.excel.uid_to_row = dict(snapshot["uid_to_row"])
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
                list(state.get("selected_micros", [])),
                all_selected=bool(state.get("micro_all_selected", True)),
            )
            self.window.data_tab.filter_eletronico.set_checked_items(
                list(state.get("selected_eletronicos", [])),
                all_selected=bool(state.get("eletronico_all_selected", True)),
            )
        finally:
            self.window.search.blockSignals(False)
            self.window.data_tab.filter_status.blockSignals(False)
            self.window.data_tab.filter_year.blockSignals(False)
            self.window.data_tab.filter_micro.blockSignals(False)
            self.window.data_tab.filter_eletronico.blockSignals(False)

    def clear_loaded_data_state(self):
        self.window.records = []
        self.window.filtered_records = []
        self.window.selected = None
        self.window.gis = None
        self.window.last_marker_coords = None
        self.window._record_search_index = {}

        empty_metrics = compute_metrics([])
        self.window.data_tab.table.clearSelection()
        self.window.data_tab.table_model.update_data([])
        self.window.data_tab.update_totals_tables(empty_metrics)
        self.window.dash_tab.update_dashboard(empty_metrics, self.window.is_dark_mode, [])
        self.window.data_tab.lbl_results.setText("0 registros")
        self.window._update_filters_from_records()
        self.window._setup_dynamic_form_options_from_records()
        self.window.clear_form(force=True)
        self.window.statusBar().showMessage("Nenhuma planilha carregada")
        self.window._refresh_window_chrome()

    def restore_previous_state(
        self,
        previous_records: List[Compensacao],
        previous_filtered: List[Compensacao],
        previous_selected: Optional[Compensacao],
        previous_marker: Optional[Tuple[float, float]],
        previous_filter_state: Dict[str, object],
    ):
        self.window.records = list(previous_records)
        self.window.filtered_records = list(previous_filtered)
        self.window.last_marker_coords = previous_marker
        self.window._record_search_index = build_record_search_index(self.window.records)

        if self.window.records:
            self.update_ui_after_load()
            self.restore_filter_state(previous_filter_state)
            self.apply_filter()
            self.window._load_sort_settings()
            self.window._refresh_window_chrome()
            if previous_selected is not None:
                self.window.selected = previous_selected
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
        previous_records = list(self.window.records)
        previous_filtered = list(self.window.filtered_records)
        previous_selected = self.window.selected
        previous_marker = self.window.last_marker_coords
        previous_filter_state = self.snapshot_filter_state()
        previous_service_state = self.snapshot_excel_service_state()
        previous_recent_files = list(self.window.recent_files)

        try:
            self.window.records = self.window.excel.load(path)
            self.window._record_search_index = build_record_search_index(self.window.records)
            logger.info(f"ExcelService.load retornou {len(self.window.records)} registros.")
            if not self.window.records:
                logger.warning("Atenção: A planilha foi lida mas retornou 0 registros.")

            self.window.settings_controller.save_last_excel_path(path)
            self.window.settings_controller.update_recent_files(path)
            self.update_ui_after_load()
            self.window._load_sort_settings()
            logger.info("Interface atualizada com sucesso após carga de dados.")
            return True
        except Exception as exc:
            self.restore_excel_service_state(previous_service_state)
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

    def update_ui_after_load(self):
        self.window._update_filters_from_records()
        self.window._setup_dynamic_form_options_from_records()
        self.load_gis()
        self.apply_filter()
        self.window.data_tab.align_splitter_to_table_width()
        QTimer.singleShot(0, self.window.data_tab.align_splitter_to_table_width)
        self.window.data_tab.table.clearSelection()
        self.window.clear_form(force=True)

    def load_gis(self):
        if os.path.isdir(self.window.MICROB_DIR):
            self.window.gis = GisService(self.window.MICROB_DIR, self.window.MICROB_NAME_FIELD)
            self.window._load_microbacias_layer()

    def update_dashboard_view(self, metrics: Dict[str, object]):
        self.window._pending_dashboard_metrics = dict(metrics)
        if self.window.tabs.currentWidget() is self.window.dash_tab:
            self.window.dash_tab.update_dashboard(metrics, self.window.is_dark_mode, [r.microbacia for r in self.window.records])
            self.window._dashboard_dirty = False
        else:
            self.window._dashboard_dirty = True

    def on_tab_changed(self, _index: int):
        if self.window.tabs.currentWidget() is self.window.dash_tab and self.window._dashboard_dirty and self.window._pending_dashboard_metrics is not None:
            self.window.dash_tab.update_dashboard(
                self.window._pending_dashboard_metrics,
                self.window.is_dark_mode,
                [r.microbacia for r in self.window.records],
            )
            self.window._dashboard_dirty = False

    def apply_filter(self):
        self.window.filtered_records = filter_records(
            self.window.records,
            text=self.window.search.text(),
            status=self.window.data_tab.filter_status.currentText(),
            selected_micros=self.window.data_tab.filter_micro.checked_items(),
            selected_eletronicos=self.window.data_tab.filter_eletronico.checked_items(),
            micro_all_selected=self.window.data_tab.filter_micro.is_all_selected(),
            eletronico_all_selected=self.window.data_tab.filter_eletronico.is_all_selected(),
            selected_year=self.window.data_tab.filter_year.currentText(),
            search_index=self.window._record_search_index,
        )
        self.window.data_tab.table_model.update_data(self.window.filtered_records)
        self.window.data_tab._resize_column_to_texts(
            self.window.data_tab.OFICIO_COLUMN_INDEX,
            [record.oficio_processo for record in self.window.records],
        )
        metrics = compute_metrics(self.window.filtered_records)
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

    def import_excel_data(self):
        if not self.window.excel.path:
            QMessageBox.warning(self.window, "Aviso", "Abra a planilha base primeiro.")
            return

        initial_dir = self.window.settings_controller.preferred_excel_dialog_dir()
        path, _ = QFileDialog.getOpenFileName(self.window, "Importar Planilha", initial_dir, "Excel (*.xlsx)")
        if not path:
            return

        if path == self.window.excel.path:
            QMessageBox.warning(self.window, "Aviso", "Você selecionou o mesmo arquivo já aberto.")
            return

        self.window.statusBar().showMessage("Analisando arquivo para importação...")

        try:
            temp_service = ExcelService()
            incoming_records = temp_service.load(path)

            current_av_tecs = {record.av_tec.strip().upper(): record for record in self.window.records if record.av_tec}
            current_uids = {record.uid: record for record in self.window.records if record.uid}

            to_add = []
            for incoming in incoming_records:
                if incoming.uid in current_uids:
                    continue
                if incoming.av_tec and incoming.av_tec.strip().upper() in current_av_tecs:
                    continue
                to_add.append(incoming)

            if not to_add:
                QMessageBox.information(self.window, "Importação", "Nenhum registro novo encontrado para importar.")
                self.window.statusBar().showMessage("Importação concluída sem adições")
                return

            msg = f"Encontrados {len(to_add)} registros novos.\nDeseja incorporá-los à sua planilha atual?"
            if msg_confirm(self.window, "Mesclar Dados", msg):
                self.window.progress_bar.setVisible(True)
                self.window.progress_bar.setMaximum(len(to_add))

                for index, record in enumerate(to_add):
                    self.window.excel.add_new(record)
                    self.window.progress_bar.setValue(index + 1)
                    QApplication.processEvents()

                self.window.progress_bar.setVisible(False)
                self.reload()
                QMessageBox.information(self.window, "Sucesso", f"{len(to_add)} registros importados com sucesso!")
                logger.info(f"Importados {len(to_add)} registros de {path}")
            else:
                self.window.statusBar().showMessage("Importação cancelada")
        except Exception as exc:
            logger.error(f"Erro na importação de {path}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "importar a planilha")
            QMessageBox.critical(self.window, title, message)
            self.window.statusBar().showMessage("Falha na importação")

    def show_rollback_dialog(self):
        if not self.window.excel.path:
            QMessageBox.warning(self.window, "Aviso", "Abra uma planilha primeiro para ver seus backups.")
            return

        base_dir = os.path.dirname(self.window.excel.path)
        backup_dir = os.path.join(base_dir, "backups_historico")
        if not os.path.exists(backup_dir):
            QMessageBox.information(self.window, "Backups", "Nenhum backup encontrado ainda para este arquivo.")
            return

        import glob
        import shutil
        from datetime import datetime

        files = glob.glob(os.path.join(backup_dir, "*.xlsx"))
        files.sort(key=os.path.getmtime, reverse=True)
        if not files:
            QMessageBox.information(self.window, "Backups", "Nenhum backup encontrado ainda para este arquivo.")
            return

        options = []
        file_map = {}
        for file_path in files:
            mtime = os.path.getmtime(file_path)
            dt_str = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M:%S")
            label = f"{dt_str} - {os.path.basename(file_path)}"
            options.append(label)
            file_map[label] = file_path

        item, ok = QInputDialog.getItem(
            self.window,
            "Máquina do Tempo",
            "Selecione uma versão anterior para restaurar (O arquivo atual será substituído):",
            options,
            0,
            False,
        )

        if ok and item:
            selected_file = file_map[item]
            if msg_confirm(self.window, "ATENÇÃO", f"Tem certeza que deseja restaurar a versão de {item.split(' - ')[0]}? As alterações atuais serão perdidas!"):
                try:
                    self.window.excel._create_rotating_backup()
                    shutil.copy2(selected_file, self.window.excel.path)
                    self.reload()
                    QMessageBox.information(self.window, "Sucesso", "Backup restaurado com sucesso!")
                    logger.info(f"Rollback executado usando arquivo {selected_file}")
                except Exception as exc:
                    logger.error(f"Falha ao restaurar backup {selected_file}: {exc}", exc_info=True)
                    title, message = friendly_error_message(exc, "restaurar o backup")
                    QMessageBox.critical(self.window, title, message)
