from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from app.application.use_cases.persistence_monitoring import PersistenceMonitoringUseCases
from app.application.use_cases.runtime_monitoring import RuntimeMonitoringUseCases
from app.services.audit_service import audit_backup_available, audit_backup_path, build_audit_overview


class OperationsController:
    def __init__(self, window):
        self.window = window
        self.persistence_use_cases = getattr(
            window,
            "persistence_monitoring_use_cases",
            PersistenceMonitoringUseCases(getattr(window, "persistence_service", None)),
        )
        self.runtime_use_cases = RuntimeMonitoringUseCases()
        if hasattr(window, "job_runner") and hasattr(window.job_runner, "subscribe_runtime_updates"):
            window.job_runner.subscribe_runtime_updates(self.refresh_runtime_overview)

    def refresh_overview(self, *, limit: int = 100):
        if not self.window.excel.path:
            self.window.operations_tab.clear_overview(
                "Abra uma planilha para acompanhar as operações recentes."
            )
            self.refresh_runtime_overview()
            return

        events = self.window.audit_service.list_events_for_workbook(self.window.excel.path, limit=limit)
        overview = build_audit_overview(events)
        persistence_report = self.persistence_use_cases.build_status_report(
            self.window.excel.path,
            expected_records=len(self.window.records),
            expected_audit_events=len(events),
        )
        record_overview_report = self.persistence_use_cases.build_record_overview_report(
            self.window.excel.path,
            top_microbacias_limit=3,
            sample_limit=3,
        )
        self.window.operations_tab.update_overview(
            self.window.excel.path,
            events,
            overview,
            persistence_report=persistence_report,
            record_overview_report=record_overview_report,
            session_source_status=getattr(self.window, "_local_session_source_status", None),
            mutation_sync_status=getattr(self.window, "_local_mutation_sync_status", None),
            record_read_status=getattr(self.window, "_local_record_read_status", None),
        )
        self.refresh_runtime_overview()

    def refresh_runtime_overview(self):
        jobs = self.window.list_runtime_jobs(limit=10) if hasattr(self.window, "list_runtime_jobs") else []
        report = self.runtime_use_cases.build_overview_report(jobs, recent_limit=5)
        self.window.operations_tab.update_runtime_overview(report)

    def on_tab_changed(self, _index: int):
        if self.window.navigation_controller.is_operations_tab_active():
            self.refresh_overview()

    def open_selected_backup(self):
        event = self.window.operations_tab.selected_event
        if event is None or not audit_backup_available(event):
            QMessageBox.information(
                self.window,
                "Operações",
                "O evento selecionado não possui um backup disponível para abrir.",
            )
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(audit_backup_path(event)))
