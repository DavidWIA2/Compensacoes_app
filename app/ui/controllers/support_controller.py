import os
import platform

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app import __version__ as APP_VERSION
from app.config import APP_NAME, UPDATE_URL_ENV_VAR
from app.services.diagnostics_service import (
    build_diagnostics_snapshot,
    default_diagnostics_filename,
    write_diagnostics_report,
)
from app.services.error_service import friendly_error_message
from app.ui.components.workers import UpdaterWorker
from app.utils.logger import LOG_DIR, logger


class SupportController:
    def __init__(self, window):
        self.window = window
        self._manual_updater = None

    def show_about_dialog(self):
        update_source = os.getenv(UPDATE_URL_ENV_VAR, "").strip() or "Nao configurado"
        lines = [
            f"{APP_NAME} {APP_VERSION}",
            "",
            "Gestao de compensacoes ambientais com cadastro, filtros, mapa e exportacoes.",
            f"Python {platform.python_version()}",
            f"Logs: {LOG_DIR}",
            f"Manifest de atualizacao: {update_source}",
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
        update_url = os.getenv(UPDATE_URL_ENV_VAR, "").strip()
        if not update_url:
            QMessageBox.information(
                self.window,
                "Atualizacoes",
                f"Defina a variavel {UPDATE_URL_ENV_VAR} apontando para um manifest JSON de release.",
            )
            return

        if self._manual_updater is not None and self._manual_updater.isRunning():
            self.window.statusBar().showMessage("Ja existe uma verificacao de atualizacao em andamento.")
            return

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

        lines = [f"Uma nova versao ({version}) esta disponivel."]
        if published_at:
            lines.append(f"Publicado em: {published_at}")
        lines.extend(["", "Novidades:", notes])
        if download_url:
            lines.extend(["", "Deseja abrir o link da atualizacao agora?"])
            reply = QMessageBox.question(
                self.window,
                "Atualizacao Disponivel",
                "\n".join(lines),
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(download_url))
                self.window.statusBar().showMessage("Link da atualizacao aberto no navegador.")
            else:
                self.window.statusBar().showMessage("Atualizacao disponivel, mas download adiado.")
            return

        QMessageBox.information(self.window, "Atualizacao Disponivel", "\n".join(lines))
        self.window.statusBar().showMessage("Atualizacao encontrada sem link de download configurado.")

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
