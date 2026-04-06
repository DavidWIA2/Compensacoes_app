import os
import platform
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app import __version__ as APP_VERSION
from app.application.use_cases.support_operations import SupportOperationsUseCases
from app.config import APP_NAME, UPDATE_URL_ENV_VAR, resolve_update_manifest_url
from app.services.auto_update_service import (
    launch_update_installer,
    supports_automatic_update,
)
from app.services.diagnostics_service import (
    build_diagnostics_snapshot,
    default_diagnostics_filename,
    write_diagnostics_report,
)
from app.services.error_service import friendly_error_message
from app.ui.components.job_specs import BackgroundJobSpec, build_disconnect_callback
from app.ui.components.workers import UpdateInstallerWorker, UpdaterWorker
from app.ui.controllers.support_controller_support import (
    apply_support_job_outcome,
    build_diagnostics_export_dialog_spec,
    build_diagnostics_success_message,
    create_update_progress_dialog,
    mark_window_job_state,
    start_window_background_job,
)
from app.utils.logger import LOG_DIR, logger

MANUAL_UPDATE_JOB_NAME = "manual_update_check"
AUTO_UPDATE_JOB_NAME = "automatic_update"


class SupportController:
    def __init__(self, window):
        self.window = window
        self.support_use_cases = SupportOperationsUseCases(
            app_name=APP_NAME,
            app_version=APP_VERSION,
            log_dir=LOG_DIR,
            update_url_env_var=UPDATE_URL_ENV_VAR,
            manifest_url_resolver=resolve_update_manifest_url,
            default_diagnostics_filename_builder=default_diagnostics_filename,
            diagnostics_snapshot_builder=build_diagnostics_snapshot,
            diagnostics_report_writer=write_diagnostics_report,
            python_version_resolver=platform.python_version,
        )
        self.updater_worker_factory = None
        self.update_installer_worker_factory = None
        self._manual_updater = None
        self._auto_update_worker = None
        self._update_progress_dialog = None
        self._manual_update_cancel_requested = False
        self._manual_update_active = False
        self._auto_update_active = False

    def show_about_dialog(self):
        about_dialog = self.support_use_cases.build_about_dialog_data()
        QMessageBox.information(self.window, about_dialog.title, about_dialog.message)

    def open_logs_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(LOG_DIR))

    def export_diagnostics(self):
        dialog_spec = build_diagnostics_export_dialog_spec(
            preferred_export_dir=self.window.settings_controller.preferred_export_dir() or "",
            fallback_dir=LOG_DIR,
            default_path_builder=self.support_use_cases.build_diagnostics_default_path,
        )
        path, _ = QFileDialog.getSaveFileName(
            self.window,
            dialog_spec.title,
            dialog_spec.default_path,
            dialog_spec.name_filter,
        )
        if not path:
            return

        try:
            self.support_use_cases.export_diagnostics_snapshot(self.window, path)
            self.window.settings_controller.save_last_export_dir(path)
            QMessageBox.information(self.window, "Sucesso", build_diagnostics_success_message(path))
        except Exception as exc:
            logger.error(f"Falha ao exportar diagnostico para {path}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "exportar o diagnostico")
            QMessageBox.critical(self.window, title, message)

    def check_for_updates(self):
        if self._manual_updater is not None and self._manual_updater.isRunning():
            self.window.statusBar().showMessage("Ja existe uma verificacao de atualizacao em andamento.")
            return

        update_url = resolve_update_manifest_url()
        worker = self._create_manual_update_worker(update_url)
        worker.update_ready.connect(self.present_update_offer)
        worker.no_update.connect(self._show_no_update_message)
        worker.check_failed.connect(self._show_update_failure)
        worker.finished.connect(self._on_manual_updater_finished)

        self._manual_update_cancel_requested = False
        self._manual_update_active = True
        self._start_background_job(self._build_manual_update_job_spec(worker))

    def present_update_offer(self, details):
        presentation = self.support_use_cases.build_update_offer_presentation(
            details,
            can_automatically_apply_update=self._can_automatically_apply_update,
        )
        runtime_message = self.support_use_cases.build_update_offer_runtime_message(presentation)

        if presentation.action_kind == "automatic_update":
            self._mark_job_completed(MANUAL_UPDATE_JOB_NAME, runtime_message)
            reply = QMessageBox.question(
                self.window,
                presentation.title,
                presentation.message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self.begin_automatic_update(presentation.payload)
            else:
                self.window.statusBar().showMessage("Atualizacao disponivel, mas instalacao adiada.")
            return

        if presentation.action_kind == "open_download":
            self._mark_job_completed(MANUAL_UPDATE_JOB_NAME, runtime_message)
            reply = QMessageBox.question(
                self.window,
                presentation.title,
                presentation.message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(presentation.download_url))
                self.window.statusBar().showMessage("Link da atualizacao aberto no navegador.")
            else:
                self.window.statusBar().showMessage("Atualizacao disponivel, mas download adiado.")
            return

        self._mark_job_completed(MANUAL_UPDATE_JOB_NAME, runtime_message)
        QMessageBox.information(self.window, presentation.title, presentation.message)
        self.window.statusBar().showMessage("Atualizacao encontrada sem link de download configurado.")

    def begin_automatic_update(self, details):
        payload = dict(details or {})
        if not self._can_automatically_apply_update(payload):
            self._open_update_link(payload)
            return

        if self._auto_update_worker is not None and self._auto_update_worker.isRunning():
            self.window.statusBar().showMessage("Ja existe uma atualizacao automatica em andamento.")
            return

        self._update_progress_dialog = self._create_update_progress_dialog()
        worker = self._create_update_installer_worker(
            payload,
            current_pid=os.getpid(),
            current_executable=sys.executable,
        )
        worker.progress.connect(self._on_auto_update_progress)
        worker.staged.connect(self._on_auto_update_staged)
        worker.failed.connect(self._on_auto_update_failed)
        worker.cancelled.connect(self._on_auto_update_cancelled)
        worker.finished.connect(self._on_auto_update_worker_finished)
        self._auto_update_active = True
        self._start_background_job(self._build_automatic_update_job_spec(worker))
        self._update_progress_dialog.show()

    def _build_manual_update_job_spec(self, worker) -> BackgroundJobSpec:
        return BackgroundJobSpec(
            name=MANUAL_UPDATE_JOB_NAME,
            worker=worker,
            disconnect_callbacks=[
                build_disconnect_callback(worker.update_ready, self.present_update_offer),
                build_disconnect_callback(worker.no_update, self._show_no_update_message),
                build_disconnect_callback(worker.check_failed, self._show_update_failure),
                build_disconnect_callback(worker.finished, self._on_manual_updater_finished),
            ],
            wait_ms=500,
            busy_message="Verificando atualizacoes...",
            cancellable=True,
            cancel_callback=self._cancel_manual_update_check,
            on_tracked=self._track_manual_updater,
        )

    def _build_automatic_update_job_spec(self, worker) -> BackgroundJobSpec:
        return BackgroundJobSpec(
            name=AUTO_UPDATE_JOB_NAME,
            worker=worker,
            disconnect_callbacks=[
                build_disconnect_callback(worker.progress, self._on_auto_update_progress),
                build_disconnect_callback(worker.staged, self._on_auto_update_staged),
                build_disconnect_callback(worker.failed, self._on_auto_update_failed),
                build_disconnect_callback(worker.cancelled, self._on_auto_update_cancelled),
                build_disconnect_callback(worker.finished, self._on_auto_update_worker_finished),
            ],
            wait_ms=5000,
            busy_message="Baixando atualizacao automatica...",
            total=100,
            cancellable=True,
            cancel_callback=self._cancel_automatic_update,
            on_tracked=self._track_automatic_update_worker,
        )

    def _track_manual_updater(self, worker) -> None:
        self._manual_updater = worker

    def _track_automatic_update_worker(self, worker) -> None:
        self._auto_update_worker = worker

    def _start_background_job(self, spec: BackgroundJobSpec):
        return start_window_background_job(self.window, spec)

    def _create_manual_update_worker(self, update_url: str):
        factory = self.updater_worker_factory or UpdaterWorker
        return factory(update_url=update_url, current_version=APP_VERSION)

    def _create_update_installer_worker(
        self,
        payload: dict[str, object],
        *,
        current_pid: int,
        current_executable: str,
    ):
        factory = self.update_installer_worker_factory or UpdateInstallerWorker
        return factory(
            payload,
            current_pid=current_pid,
            current_executable=current_executable,
        )

    def shutdown(self):
        self._close_update_progress_dialog()

    def _can_automatically_apply_update(self, details):
        return supports_automatic_update(details)

    def _open_update_link(self, details):
        download_url = str(details.get("download_url") or details.get("homepage_url") or "").strip()
        if not download_url:
            QMessageBox.information(
                self.window,
                "Atualizacao Disponivel",
                "A atualizacao foi encontrada, mas o manifest nao informou um link valido.",
            )
            self.window.statusBar().showMessage("Atualizacao sem link de download configurado.")
            return

        QDesktopServices.openUrl(QUrl(download_url))
        self.window.statusBar().showMessage("Link da atualizacao aberto no navegador.")

    def _create_update_progress_dialog(self):
        return create_update_progress_dialog(self.window, self._cancel_automatic_update)

    def _cancel_manual_update_check(self):
        if self._manual_updater is None or not self._manual_updater.isRunning():
            return
        self._manual_update_cancel_requested = True
        self.window.statusBar().showMessage("Cancelando verificacao de atualizacoes...")
        self._manual_updater.requestInterruption()

    def _cancel_automatic_update(self):
        if self._auto_update_worker is None or not self._auto_update_worker.isRunning():
            return
        self.window.statusBar().showMessage("Cancelando download da atualizacao...")
        self._auto_update_worker.requestInterruption()

    def _on_auto_update_progress(self, percent: int, message: str):
        progress = self.support_use_cases.normalize_update_progress(percent, message)
        if self._update_progress_dialog is not None:
            self._update_progress_dialog.setLabelText(progress.message)
            self._update_progress_dialog.setValue(progress.percent)
        self.window.update_busy_operation(progress.percent, progress.message)
        self.window.statusBar().showMessage(progress.message)

    def _on_auto_update_staged(self, payload):
        outcome = self.support_use_cases.build_auto_update_ready_outcome()
        self._apply_job_outcome(AUTO_UPDATE_JOB_NAME, outcome)
        self._complete_auto_update_job(outcome.busy_message)
        self._close_update_progress_dialog()
        if not self.window.form_controller.confirm_discard_changes("instalar a atualizacao"):
            self.window.statusBar().showMessage("Atualizacao pronta, mas instalacao cancelada pelo usuario.")
            return

        try:
            launch_update_installer(payload["launcher_path"])
        except Exception as exc:
            logger.error(f"Falha ao iniciar instalador da atualizacao: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "iniciar a instalacao da atualizacao")
            QMessageBox.critical(self.window, title, message)
            self.window.statusBar().showMessage("Falha ao iniciar a atualizacao automatica.")
            return

        self.window._skip_close_discard_confirmation = True
        self.window.statusBar().showMessage("Atualizacao pronta. Fechando o aplicativo para instalar...")
        self.window.close()

    def _on_auto_update_failed(self, message: str):
        outcome = self.support_use_cases.build_auto_update_failed_outcome(message)
        self._apply_job_outcome(AUTO_UPDATE_JOB_NAME, outcome, dialog_kind="warning")
        self._complete_auto_update_job(outcome.busy_message)
        self._close_update_progress_dialog()
        logger.warning(f"Falha na atualizacao automatica: {message}")

    def _on_auto_update_cancelled(self, message: str):
        outcome = self.support_use_cases.build_auto_update_cancelled_outcome(message)
        self._apply_job_outcome(AUTO_UPDATE_JOB_NAME, outcome, dialog_kind="information")
        self._complete_auto_update_job(outcome.busy_message)
        self._close_update_progress_dialog()

    def _show_no_update_message(self, current_version: str):
        outcome = self.support_use_cases.build_no_update_outcome(current_version)
        self._apply_job_outcome(MANUAL_UPDATE_JOB_NAME, outcome, dialog_kind="information")

    def _show_update_failure(self, message: str):
        outcome = self.support_use_cases.build_update_check_failure_outcome(message)
        self._apply_job_outcome(MANUAL_UPDATE_JOB_NAME, outcome, dialog_kind="warning")

    def _on_manual_updater_finished(self):
        if self._manual_update_cancel_requested:
            outcome = self.support_use_cases.build_manual_update_cancel_outcome()
            self._apply_job_outcome(MANUAL_UPDATE_JOB_NAME, outcome)
        if self._manual_update_active:
            final_message = self.support_use_cases.build_manual_update_completion_message(
                self._manual_update_cancel_requested
            )
            self.window.end_busy_operation(final_message)
            self._manual_update_active = False
        self.window.release_background_worker(MANUAL_UPDATE_JOB_NAME)
        self._clear_manual_updater()

    def _clear_manual_updater(self):
        self._manual_updater = None
        self._manual_update_cancel_requested = False

    def _clear_auto_update_worker(self):
        self._auto_update_worker = None
        self._auto_update_active = False

    def _on_auto_update_worker_finished(self):
        if self._auto_update_active:
            self.window.end_busy_operation("Atualizacao automatica encerrada.")
        self.window.release_background_worker(AUTO_UPDATE_JOB_NAME)
        self._clear_auto_update_worker()

    def _complete_auto_update_job(self, final_message: str):
        if self._auto_update_active:
            self.window.end_busy_operation(final_message)
            self._auto_update_active = False

    def _close_update_progress_dialog(self):
        if self._update_progress_dialog is None:
            return
        self._update_progress_dialog.close()
        self._update_progress_dialog.deleteLater()
        self._update_progress_dialog = None

    def _mark_job_completed(self, name: str, message: str = "Pronto") -> None:
        mark_window_job_state(self.window, name, "completed", message)

    def _mark_job_failed(self, name: str, message: str) -> None:
        mark_window_job_state(self.window, name, "failed", message)

    def _mark_job_cancelled(self, name: str, message: str) -> None:
        mark_window_job_state(self.window, name, "cancelled", message)

    def _apply_job_outcome(self, name: str, outcome, *, dialog_kind: str = "") -> None:
        apply_support_job_outcome(self.window, name, outcome, dialog_kind=dialog_kind)

    @staticmethod
    def _shutdown_worker(worker, *, wait_ms: int):
        if worker is None:
            return
        if hasattr(worker, "isRunning") and worker.isRunning():
            if hasattr(worker, "requestInterruption"):
                worker.requestInterruption()
            if hasattr(worker, "quit"):
                worker.quit()
            if hasattr(worker, "wait"):
                worker.wait(wait_ms)
