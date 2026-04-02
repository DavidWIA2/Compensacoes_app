import os
from typing import List

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from app.application.use_cases.export_operations import (
    ExportFilterState,
    ExportReportingUseCases,
)
from app.application.use_cases.persistence_monitoring import PersistenceRecordOverviewReport
from app.services.error_service import friendly_error_message
from app.services.ficha_report_service import export_individual_pdf
from app.services.records_service import compute_metrics
from app.services.report_service import (
    export_csv,
    export_dashboard_pdf,
    export_excel_two_sheets,
    export_pdf,
)
from app.ui.components.job_specs import BlockingJobSpec
from app.utils.logger import get_logger


logger = get_logger("UI.Export")


class ExportController:
    def __init__(self, window):
        self.window = window
        self.persistence_use_cases = getattr(window, "persistence_monitoring_use_cases", None)
        self.reporting_use_cases = ExportReportingUseCases(self.persistence_use_cases)

    def _perform_export(
        self,
        *,
        job_name: str,
        path: str,
        busy_message: str,
        success_message: str,
        error_action: str,
        operation,
    ) -> bool:
        try:
            self.window.run_blocking_spec(
                BlockingJobSpec(
                    name=job_name,
                    busy_message=busy_message,
                    operation=operation,
                    success_message=success_message,
                    failure_message=f"Falha ao {error_action}.",
                )
            )
        except Exception as exc:
            logger.error(f"Falha ao {error_action} para {path}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, error_action)
            QMessageBox.critical(self.window, title, message)
            return False

        QMessageBox.information(self.window, "Sucesso", success_message)
        return True

    def _current_filter_state(self) -> ExportFilterState:
        return ExportFilterState(
            search_text=self.window.search.text(),
            status=self.window.data_tab.filter_status.currentText(),
            selected_micros=tuple(self.window.data_tab.filter_micro.checked_items()),
            micro_all_selected=self.window.data_tab.filter_micro.is_all_selected(),
            selected_eletronicos=tuple(self.window.data_tab.filter_eletronico.checked_items()),
            eletronico_all_selected=self.window.data_tab.filter_eletronico.is_all_selected(),
            year=self.window.data_tab.filter_year.currentText(),
        )

    def metrics_to_kpi_rows(self, metrics):
        return self.reporting_use_cases.build_metrics_kpi_rows(metrics)

    def _current_filtered_metrics(self):
        cached_metrics = getattr(self.window, "_filtered_metrics", None)
        if cached_metrics is not None:
            return dict(cached_metrics)
        return compute_metrics(self.window.filtered_records)

    def _current_dashboard_record_overview(self) -> PersistenceRecordOverviewReport | None:
        cached_report = getattr(self.window, "_dashboard_record_overview", None)
        workbook_path = str(getattr(getattr(self.window, "excel", None), "path", "") or "").strip()
        try:
            report = self.reporting_use_cases.resolve_dashboard_record_overview(
                workbook_path=workbook_path,
                cached_report=cached_report,
                top_microbacias_limit=3,
                sample_limit=0,
            )
        except Exception as exc:
            logger.warning("Falha ao montar resumo local para exportacao do painel: %s", exc, exc_info=True)
            return None

        if cached_report is None and report is not None:
            self.window._dashboard_record_overview = report
        return report

    def build_dashboard_persistence_lines(self) -> List[str]:
        return self.reporting_use_cases.build_dashboard_persistence_lines(
            self._current_dashboard_record_overview()
        )

    def build_filter_summary(self) -> str:
        return self.reporting_use_cases.build_filter_summary(self._current_filter_state())

    def get_save_path(self, title: str, file_filter: str) -> str:
        initial_dir = self.window.settings_controller.preferred_export_dir()
        path, _ = QFileDialog.getSaveFileName(self.window, title, initial_dir, file_filter)
        if path:
            self.window.settings_controller.save_last_export_dir(os.path.dirname(path))
        return path

    def export_csv_clicked(self):
        path = self.window._get_save_path("Salvar CSV", "CSV (*.csv)")
        if not path:
            return
        self._perform_export(
            job_name="export_csv",
            path=path,
            busy_message="Exportando CSV...",
            success_message="CSV exportado com sucesso.",
            error_action="exportar o CSV",
            operation=lambda: export_csv(
                path,
                self.window.filtered_records,
                self.window._get_visible_column_attrs(),
            ),
        )

    def export_excel_clicked(self):
        path = self.window._get_save_path("Salvar Excel", "Excel (*.xlsx)")
        if not path:
            return
        metrics = self._current_filtered_metrics()
        self._perform_export(
            job_name="export_excel",
            path=path,
            busy_message="Exportando Excel...",
            success_message="Excel exportado com sucesso.",
            error_action="exportar o Excel",
            operation=lambda: export_excel_two_sheets(
                path,
                self.window.filtered_records,
                self.build_filter_summary(),
                self.window._get_visible_column_attrs(),
                self.metrics_to_kpi_rows(metrics),
                metrics["pend_micro_sorted"],
                metrics["pend_ele_sorted"],
            ),
        )

    def export_pdf_clicked(self):
        path = self.window._get_save_path("Salvar PDF", "PDF (*.pdf)")
        if not path:
            return
        metrics = self._current_filtered_metrics()
        self._perform_export(
            job_name="export_pdf",
            path=path,
            busy_message="Exportando PDF...",
            success_message="PDF exportado com sucesso.",
            error_action="exportar o PDF",
            operation=lambda: export_pdf(
                path,
                self.window.filtered_records,
                self.build_filter_summary(),
                self.window._get_visible_column_attrs(),
                self.metrics_to_kpi_rows(metrics),
                metrics["pend_micro_sorted"],
            ),
        )

    def export_ficha_pdf(self):
        if not self.window.selected:
            return
        path = self.window._get_save_path("Salvar Ficha PDF", "PDF (*.pdf)")
        if not path:
            return
        observacao, ok = QInputDialog.getMultiLineText(
            self.window,
            "Observacao da Ficha",
            "Observacao (opcional):",
            "",
        )
        if not ok:
            return
        self._perform_export(
            job_name="export_ficha_pdf",
            path=path,
            busy_message="Gerando ficha em PDF...",
            success_message="Ficha PDF gerada com sucesso.",
            error_action="exportar a ficha em PDF",
            operation=lambda: export_individual_pdf(path, self.window.selected, observacao.strip()),
        )

    def export_dashboard_pdf_clicked(self):
        path = self.window._get_save_path("Salvar PDF", "PDF (*.pdf)")
        if not path:
            return
        metrics = self._current_filtered_metrics()
        pie, bar = self.window.dash_tab.export_images()
        payload = self.reporting_use_cases.build_dashboard_export_payload(
            metrics=metrics,
            filter_state=self._current_filter_state(),
            chart_images=[pie, bar],
            workbook_path=str(getattr(getattr(self.window, "excel", None), "path", "") or ""),
            cached_report=getattr(self.window, "_dashboard_record_overview", None),
            record_read_status=getattr(self.window, "_local_record_read_status", None),
        )
        if payload.record_overview is not None:
            self.window._dashboard_record_overview = payload.record_overview
        self._perform_export(
            job_name="export_dashboard_pdf",
            path=path,
            busy_message="Gerando relatorio do painel...",
            success_message="Relatorio de Painel exportado.",
            error_action="exportar o painel em PDF",
            operation=lambda: export_dashboard_pdf(
                path,
                "Painel Geral",
                list(payload.kpi_lines),
                payload.filter_summary,
                list(payload.chart_images),
            ),
        )
