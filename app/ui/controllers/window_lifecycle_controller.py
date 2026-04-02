from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from app.ui.components.job_specs import BackgroundJobSpec
from app.ui.components.ui_utils import _setup_i18n


class WindowLifecycleController:
    def __init__(self, window):
        self.window = window
        self._timers_bound = False

    def initialize_timers(self):
        self.window._startup_window_timer = QTimer(self.window)
        self.window._startup_window_timer.setSingleShot(True)

        self.window._initial_map_sync_timer = QTimer(self.window)
        self.window._initial_map_sync_timer.setSingleShot(True)

    def _rewire_timers(self):
        self._reconnect_timeout(self.window._startup_window_timer, self.window._apply_startup_window_state)
        self._reconnect_timeout(self.window._initial_map_sync_timer, self.window._initial_map_sync)

    @staticmethod
    def _reconnect_timeout(timer: QTimer, handler):
        try:
            timer.timeout.disconnect()
        except Exception:
            pass
        timer.timeout.connect(handler)

    def bind_runtime_hooks(self):
        if not self._timers_bound:
            self.window._startup_window_timer.timeout.connect(self.window._apply_startup_window_state)
            self.window._initial_map_sync_timer.timeout.connect(self.window._initial_map_sync)
            self._timers_bound = True
        else:
            self._rewire_timers()
        self.window.data_tab.bridge._on_clicked = self.window._on_map_click
        self.window.data_tab.bridge._on_layer_changed = self.window.save_map_layer_preference

    def finalize_initialization(self):
        self.window._setup_menus()
        self.window._load_settings()
        self.window._connect_signals()
        self.window._setup_shortcuts()
        self.window.form_controller.setup_form_state_ui()
        self.window._startup_window_timer.start(0)

        _setup_i18n()
        self.window._load_last_excel()
        self.window._apply_theme()

        self.window._update_form_action_buttons()
        self.window._update_address_search_enabled()
        self.window._refresh_window_chrome()
        self.window.refresh_operations_overview()
        self.window.setWindowModified(False)
        self.window.statusBar().showMessage("Pronto")

        self.start_background_update_check()

    def start_background_update_check(self):
        updater = self.window._updater_cls()
        self.window._updater = updater
        disconnect_callbacks = []
        if hasattr(updater, "update_ready"):
            updater.update_ready.connect(self.window.present_update_offer)
            disconnect_callbacks.append(
                lambda updater=updater: updater.update_ready.disconnect(self.window.present_update_offer)
            )
        elif hasattr(updater, "update_available"):
            updater.update_available.connect(self.window._prompt_update)
            disconnect_callbacks.append(
                lambda updater=updater: updater.update_available.disconnect(self.window._prompt_update)
            )
        self.window.start_background_job(
            BackgroundJobSpec(
                name="startup_update_check",
                worker=updater,
                disconnect_callbacks=disconnect_callbacks,
                wait_ms=500,
                on_tracked=lambda worker: setattr(self.window, "_updater", worker),
            )
        )

    def handle_resize(self):
        if self.window._startup_layout_pending and not self.window.isMinimized():
            self.window._startup_layout_pending = False
            self.window._finalize_startup_layout()

    def prompt_update(self, version: str, notes: str):
        msg = (
            f"Uma nova vers\u00e3o do aplicativo ({version}) est\u00e1 dispon\u00edvel!\n\n"
            f"Novidades:\n{notes}\n\nDeseja atualizar agora?"
        )
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        reply = QMessageBox.question(self.window, "Atualiza\u00e7\u00e3o Dispon\u00edvel", msg, buttons)
        if reply == QMessageBox.StandardButton.Yes:
            self.window.statusBar().showMessage("Baixando atualiza\u00e7\u00e3o em segundo plano...")
            QMessageBox.information(
                self.window,
                "Atualizador",
                "A atualiza\u00e7\u00e3o ser\u00e1 baixada. O aplicativo ser\u00e1 reiniciado em breve.",
            )

    def prepare_close(self, event) -> bool:
        if not self.window._skip_close_discard_confirmation and not self.window.form_controller.confirm_discard_changes(
            "fechar a janela"
        ):
            event.ignore()
            return False

        self.stop_owned_timers()
        self.window.settings_controller.save_before_close()

        if hasattr(self.window, "support_controller"):
            self.window.support_controller.shutdown()

        if hasattr(self.window, "job_runner"):
            self.window.job_runner.shutdown_all_workers()

        return True

    def stop_owned_timers(self):
        if getattr(self.window, "_startup_window_timer", None) is not None and self.window._startup_window_timer.isActive():
            self.window._startup_window_timer.stop()
        if (
            getattr(self.window, "_initial_map_sync_timer", None) is not None
            and self.window._initial_map_sync_timer.isActive()
        ):
            self.window._initial_map_sync_timer.stop()
