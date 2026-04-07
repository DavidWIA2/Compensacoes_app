from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from app.application.use_cases.operations_overview_use_cases import OperationsOverviewUseCases
from app.application.use_cases.persistence_monitoring import PersistenceMonitoringUseCases
from app.application.use_cases.runtime_monitoring import RuntimeMonitoringUseCases
from app.services.audit_service import audit_backup_available, audit_backup_path


class OperationsController:
    def __init__(self, window):
        self.window = window
        self.persistence = getattr(window, "authoritative_persistence", None)
        self.persistence_use_cases = getattr(
            window,
            "persistence_monitoring_use_cases",
            PersistenceMonitoringUseCases(getattr(window, "persistence_service", None)),
        )
        self.overview_use_cases = OperationsOverviewUseCases(self.persistence_use_cases)
        self.runtime_use_cases = RuntimeMonitoringUseCases()
        if hasattr(window, "job_runner") and hasattr(window.job_runner, "subscribe_runtime_updates"):
            window.job_runner.subscribe_runtime_updates(self.refresh_runtime_overview)

    def _current_session_path(self) -> str:
        if hasattr(self.window, "shell_controller"):
            return self.window.shell_controller.current_session_path()
        runtime = getattr(self.window, "session_runtime", None)
        if runtime is None:
            return ""
        return str(getattr(runtime, "session_path", getattr(runtime, "path", "")) or "").strip()

    @staticmethod
    def _empty_overview_message() -> str:
        return "O banco local ainda não está pronto para acompanhar as operações recentes."

    def _resolved_expected_records(self) -> int:
        if hasattr(self.window, "shell_controller"):
            return int(self.window.shell_controller.resolved_total_records() or 0)
        return len(getattr(self.window, "records", ()))

    def refresh_overview(self, *, limit: int = 100):
        session_path = (
            self.window.shell_controller.current_session_path()
            if hasattr(self.window, "shell_controller")
            else self._current_session_path()
        )
        snapshot = self.overview_use_cases.resolve_snapshot(
            session_path=session_path,
            audit_service=self.window.audit_service,
            expected_records=self._resolved_expected_records(),
            shell_controller=getattr(self.window, "shell_controller", None),
            persistence=self.persistence,
            runtime_window=self.window,
            access_session=getattr(self.window, "access_session", None),
            remote_sync_status=getattr(self.window, "_remote_snapshot_refresh_status", None),
            session_source_status=getattr(self.window, "_local_session_source_status", None),
            authoritative_write_status=getattr(self.window, "_authoritative_write_status", None),
            mutation_sync_status=getattr(self.window, "_local_mutation_sync_status", None),
            record_read_status=getattr(self.window, "_local_record_read_status", None),
            limit=limit,
        )
        if snapshot is None:
            self.window.operations_tab.clear_overview(self._empty_overview_message())
            self.refresh_runtime_overview()
            return

        self.window.operations_tab.update_overview(
            snapshot.session_path,
            snapshot.events,
            snapshot.overview,
            access_session=snapshot.access_session,
            persistence_report=snapshot.persistence_report,
            record_overview_report=snapshot.record_overview_report,
            remote_sync_status=snapshot.remote_sync_status,
            session_source_status=snapshot.session_source_status,
            authoritative_write_status=snapshot.authoritative_write_status,
            mutation_sync_status=snapshot.mutation_sync_status,
            record_read_status=snapshot.record_read_status,
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

    def refresh_production_snapshot(self):
        return self.window.data_controller.refresh_production_snapshot()
