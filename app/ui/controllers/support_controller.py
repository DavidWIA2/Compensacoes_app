import os
import platform
import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

from app import __version__ as APP_VERSION
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
from app.ui.components.workers import UpdateInstallerWorker, UpdaterWorker
from app.utils.logger import LOG_DIR, logger


class SupportController:
    def __init__(self, window):
        self.window = window
        self._manual_updater = None
        self._auto_update_worker = None
        self._update_progress_dialog = None

    def show_about_dialog(self):
        update_source = resolve_update_manifest_url()
        lines = [
            f"{APP_NAME} {APP_VERSION}",
            "",
            "Gestao de compensacoes ambientais com cadastro, filtros, mapa e exportacoes.",
            f"Python {platform.python_version()}",
            f"Logs: {LOG_DIR}",
            f"Manifest de atualizacao: {update_source}",
            f"Variavel de override: {UPDATE_URL_ENV_VAR}",
        ]
        QMessageBox.information(self.window, f"Sobre o {APP_NAME}", "\n".join(lines))

    def open_logs_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(LOG_DIR))

    def export_diagnostics(self):
        initial_dir = self.window.settings_controller.preferred_export_dir() or LOG_DIR
        default_path = os.path.join(initial_dir, default_diagnostics_filename())
        path, _ = QFileDialog.getSaveFileName(self.window, "Exportar Diagnostico", default_path, "JSON (*.json)")
        if not path:
            return

        try:
            snapshot = build_diagnostics_snapshot(self.window)
            write_diagnostics_report(path, snapshot)
            self.window.settings_controller.save_last_export_dir(path)
            QMessageBox.information(self.window, "Sucesso", f"Diagnostico exportado para:\n{path}")
        except Exception as exc:
            logger.error(f"Falha ao exportar diagnostico para {path}: {exc}", exc_info=True)
            title, message = friendly_error_message(exc, "exportar o diagnostico")
            QMessageBox.critical(self.window, title, message)

    def check_for_updates(self):
        if self._manual_updater is not None and self._manual_updater.isRunning():
            self.window.statusBar().showMessage("Ja existe uma verificacao de atualizacao em andamento.")
            return

        update_url = resolve_update_manifest_url()
        self.window.statusBar().showMessage("Verificando atualizacoes...")
        self._manual_updater = UpdaterWorker(update_url=update_url, current_version=APP_VERSION)
        self._manual_updater.update_ready.connect(self.present_update_offer)
        self._manual_updater.no_update.connect(self._show_no_update_message)
        self._manual_updater.check_failed.connect(self._show_update_failure)
        self._manual_updater.finished.connect(self._clear_manual_updater)
        self._manual_updater.start()

    def present_update_offer(self, details):
        payload = dict(details or {})
        version = str(payload.get("version") or "").strip()
        notes = str(payload.get("notes") or "Sem notas de versao.").strip() or "Sem notas de versao."
        download_url = str(payload.get("download_url") or payload.get("homepage_url") or "").strip()
        published_at = str(payload.get("published_at") or "").strip()
        filename = str(payload.get("filename") or "").strip()
        sha256 = str(payload.get("sha256") or "").strip().lower()
        signed = payload.get("signed")
        signature_mode = str(payload.get("signature_mode") or "").strip()
        can_auto_update = self._can_automatically_apply_update(payload)

        lines = [f"Uma nova versao ({version}) esta disponivel."]
        if published_at:
            lines.append(f"Publicado em: {published_at}")
        if filename:
            lines.append(f"Arquivo: {filename}")
        if sha256:
            lines.append(f"SHA-256: {sha256}")
        if signed is True:
            mode_text = f" ({signature_mode})" if signature_mode else ""
            lines.append(f"Assinatura digital: presente{mode_text}.")
        elif signed is False:
            lines.append("Assinatura digital: ausente nesta release.")
        lines.extend(["", "Novidades:", notes])

        if can_auto_update:
            lines.extend(["", "Deseja baixar e instalar a atualizacao agora?"])
            reply = QMessageBox.question(
                self.window,
                "Atualizacao Disponivel",
                "\n".join(lines),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self.begin_automatic_update(payload)
            else:
                self.window.statusBar().showMessage("Atualizacao disponivel, mas instalacao adiada.")
            return

        if download_url:
            lines.extend(["", "Deseja abrir o link da atualizacao agora?"])
            reply = QMessageBox.question(
                self.window,
                "Atualizacao Disponivel",
                "\n".join(lines),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(download_url))
                self.window.statusBar().showMessage("Link da atualizacao aberto no navegador.")
            else:
                self.window.statusBar().showMessage("Atualizacao disponivel, mas download adiado.")
            return

        QMessageBox.information(self.window, "Atualizacao Disponivel", "\n".join(lines))
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
        self._auto_update_worker = UpdateInstallerWorker(
            payload,
            current_pid=os.getpid(),
            current_executable=sys.executable,
        )
        self._auto_update_worker.progress.connect(self._on_auto_update_progress)
        self._auto_update_worker.staged.connect(self._on_auto_update_staged)
        self._auto_update_worker.failed.connect(self._on_auto_update_failed)
        self._auto_update_worker.cancelled.connect(self._on_auto_update_cancelled)
        self._auto_update_worker.finished.connect(self._clear_auto_update_worker)
        self._auto_update_worker.start()
        self.window.statusBar().showMessage("Baixando atualizacao automatica...")
        self._update_progress_dialog.show()

    def shutdown(self):
        self._shutdown_worker(self._manual_updater, wait_ms=500)
        self._shutdown_worker(self._auto_update_worker, wait_ms=5000)
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
        dialog = QProgressDialog("Baixando atualizacao...", "Cancelar", 0, 100, self.window)
        dialog.setWindowTitle("Atualizacao Automatica")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(self._cancel_automatic_update)
        return dialog

    def _cancel_automatic_update(self):
        if self._auto_update_worker is None or not self._auto_update_worker.isRunning():
            return
        self.window.statusBar().showMessage("Cancelando download da atualizacao...")
        self._auto_update_worker.requestInterruption()

    def _on_auto_update_progress(self, percent: int, message: str):
        if self._update_progress_dialog is not None:
            self._update_progress_dialog.setLabelText(message)
            self._update_progress_dialog.setValue(max(0, min(percent, 100)))
        self.window.statusBar().showMessage(message)

    def _on_auto_update_staged(self, payload):
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
        self._close_update_progress_dialog()
        logger.warning(f"Falha na atualizacao automatica: {message}")
        QMessageBox.warning(self.window, "Atualizacao Automatica", message)
        self.window.statusBar().showMessage("Falha ao baixar/preparar a atualizacao.")

    def _on_auto_update_cancelled(self, message: str):
        self._close_update_progress_dialog()
        QMessageBox.information(self.window, "Atualizacao Automatica", message or "Atualizacao cancelada.")
        self.window.statusBar().showMessage("Atualizacao automatica cancelada.")

    def _show_no_update_message(self, current_version: str):
        QMessageBox.information(
            self.window,
            "Atualizacoes",
            f"Voce ja esta na versao mais recente disponivel ({current_version}).",
        )
        self.window.statusBar().showMessage("Nenhuma atualizacao encontrada.")

    def _show_update_failure(self, message: str):
        QMessageBox.warning(self.window, "Atualizacoes", message)
        self.window.statusBar().showMessage("Falha ao verificar atualizacoes.")

    def _clear_manual_updater(self):
        self._manual_updater = None

    def _clear_auto_update_worker(self):
        self._auto_update_worker = None

    def _close_update_progress_dialog(self):
        if self._update_progress_dialog is None:
            return
        self._update_progress_dialog.close()
        self._update_progress_dialog.deleteLater()
        self._update_progress_dialog = None

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
