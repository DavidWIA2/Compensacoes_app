import os
from typing import Dict, List, Tuple

from PySide6.QtWidgets import QFileDialog, QMessageBox

from app.models.display_columns import DISPLAY_COLUMN_ATTRS
from app.services.error_service import friendly_error_message
from app.services.records_service import compute_metrics
from app.services.report_service import (
    export_csv,
    export_dashboard_pdf,
    export_excel_two_sheets,
    export_individual_pdf,
    export_pdf,
)
from app.utils.logger import logger


class ExportController:
    def __init__(self, window):
        self.window = window

    def metrics_to_kpi_rows(self, metrics: Dict[str, object]) -> List[Tuple[str, str]]:
        return [
            ("Total de Registros", str(metrics["count_total"])),
            ("Total de Mudas", f"{metrics['total_geral']:g}"),
            ("Pendentes", f"{metrics['total_pendente']:g}"),
            ("Compensadas", f"{metrics['total_compensado']:g}"),
        ]

    def build_filter_summary(self) -> str:
        parts = []
        search_text = self.window.search.text().strip()
        if search_text:
            parts.append(f"Busca: {search_text}")

        status = self.window.data_tab.filter_status.currentText()
        if status != "Todos":
            parts.append(f"Status: {status}")

        if not self.window.data_tab.filter_micro.is_all_selected():
            micros = ", ".join(self.window.data_tab.filter_micro.checked_items())
            parts.append(f"Microbacias: {micros or 'Nenhuma'}")

        if not self.window.data_tab.filter_eletronico.is_all_selected():
            eletronicos = ", ".join(self.window.data_tab.filter_eletronico.checked_items())
            parts.append(f"Eletrônico: {eletronicos or 'Nenhum'}")

        year = self.window.data_tab.filter_year.currentText()
        if year and year != "Todos":
            parts.append(f"Ano: {year}")

        return "Sem filtros aplicados" if not parts else " | ".join(parts)

    def get_save_path(self, title: str, file_filter: str) -> str:
        initial_dir = self.window.settings_controller.preferred_export_dir()
        path, _ = QFileDialog.getSaveFileName(self.window, title, initial_dir, file_filter)
        if path:
            self.window.settings_controller.save_last_export_dir(os.path.dirname(path))
        return path

    def _main_window_module(self):
        from app.ui import main_window as main_window_module

        return main_window_module

    def export_csv_clicked(self):
        path = self.window._get_save_path("Salvar CSV", "CSV (*.csv)")
        if not path:
            return
        main_window_module = self._main_window_module()
        try:
            main_window_module.export_csv(path, self.window.filtered_records, self.window._get_visible_column_attrs())
        except Exception as exc:
            logger.error(f"Falha ao exportar CSV para {path}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "exportar o CSV")
            QMessageBox.critical(self.window, title, message)
            return
        QMessageBox.information(self.window, "Sucesso", "CSV exportado com sucesso.")

    def export_excel_clicked(self):
        path = self.window._get_save_path("Salvar Excel", "Excel (*.xlsx)")
        if not path:
            return
        main_window_module = self._main_window_module()
        metrics = main_window_module.compute_metrics(self.window.filtered_records)
        try:
            main_window_module.export_excel_two_sheets(
                path,
                self.window.filtered_records,
                self.build_filter_summary(),
                self.window._get_visible_column_attrs(),
                self.metrics_to_kpi_rows(metrics),
                metrics["pend_micro_sorted"],
                metrics["pend_ele_sorted"],
            )
        except Exception as exc:
            logger.error(f"Falha ao exportar Excel para {path}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "exportar o Excel")
            QMessageBox.critical(self.window, title, message)
            return
        QMessageBox.information(self.window, "Sucesso", "Excel exportado com sucesso.")

    def export_pdf_clicked(self):
        path = self.window._get_save_path("Salvar PDF", "PDF (*.pdf)")
        if not path:
            return
        main_window_module = self._main_window_module()
        metrics = main_window_module.compute_metrics(self.window.filtered_records)
        try:
            main_window_module.export_pdf(
                path,
                self.window.filtered_records,
                self.build_filter_summary(),
                self.window._get_visible_column_attrs(),
                self.metrics_to_kpi_rows(metrics),
                metrics["pend_micro_sorted"],
            )
        except Exception as exc:
            logger.error(f"Falha ao exportar PDF para {path}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "exportar o PDF")
            QMessageBox.critical(self.window, title, message)
            return
        QMessageBox.information(self.window, "Sucesso", "PDF exportado com sucesso.")

    def export_ficha_pdf(self):
        if not self.window.selected:
            return
        path = self.window._get_save_path("Salvar Ficha PDF", "PDF (*.pdf)")
        if not path:
            return
        main_window_module = self._main_window_module()
        try:
            main_window_module.export_individual_pdf(path, self.window.selected)
        except Exception as exc:
            logger.error(f"Falha ao exportar ficha em PDF para {path}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "exportar a ficha em PDF")
            QMessageBox.critical(self.window, title, message)
            return
        QMessageBox.information(self.window, "Sucesso", "Ficha PDF gerada com sucesso.")

    def export_dashboard_pdf_clicked(self):
        path = self.window._get_save_path("Salvar PDF", "PDF (*.pdf)")
        if not path:
            return
        main_window_module = self._main_window_module()
        metrics = main_window_module.compute_metrics(self.window.filtered_records)
        pie, bar = self.window.dash_tab.export_images()
        chart_images = [img for img in [pie, bar] if img]
        kpi_lines = [
            f"Total de registros: {metrics['count_total']}",
            f"Total de mudas: {metrics['total_geral']:g}",
            f"Pendentes: {metrics['total_pendente']:g}",
            f"Compensadas: {metrics['total_compensado']:g}",
        ]
        try:
            main_window_module.export_dashboard_pdf(
                path,
                "Painel Geral",
                kpi_lines,
                self.build_filter_summary(),
                chart_images,
            )
        except Exception as exc:
            logger.error(f"Falha ao exportar painel em PDF para {path}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "exportar o painel em PDF")
            QMessageBox.critical(self.window, title, message)
            return
        QMessageBox.information(self.window, "Sucesso", "Relatório de Painel exportado.")
