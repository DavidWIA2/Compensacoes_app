from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from app.ui.components.job_specs import BackgroundJobSpec
from app.ui.controllers.settings_support import ensure_window_fits_available_geometry
from app.ui.controllers.window_lifecycle_support import (
    build_update_disconnect_callbacks,
    build_update_prompt_content,
    run_startup_sequence,
    stop_active_timer,
)


class WindowLifecycleController:
    def __init__(self, window):
        self.window = window
        self._timers_bound = False
        self._post_show_fit_scheduled = False

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
        bridge = getattr(self.window.data_tab, "bridge", None)
        if bridge is not None:
            bridge._on_clicked = self.window._on_map_click
            bridge._on_layer_changed = self.window.save_map_layer_preference

    def finalize_initialization(self):
        run_startup_sequence(self.window)
        self.start_background_update_check()

    def start_background_update_check(self):
        updater = self.window._updater_cls()
        self.window._updater = updater
        disconnect_callbacks = build_update_disconnect_callbacks(self.window, updater)
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

    def schedule_post_show_fit(self):
        if self._post_show_fit_scheduled:
            return
        self._post_show_fit_scheduled = True
        QTimer.singleShot(0, self._fit_window_after_show)
        QTimer.singleShot(180, self._fit_window_after_show)

    def _fit_window_after_show(self):
        if not self.window.isVisible() or self.window.isMinimized():
            return
        ensure_window_fits_available_geometry(self.window)

    def prompt_update(self, version: str, notes: str):
        prompt = build_update_prompt_content(version, notes)
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        reply = QMessageBox.question(self.window, prompt.title, prompt.question_message, buttons)
        if reply == QMessageBox.StandardButton.Yes:
            self.window.statusBar().showMessage(prompt.accepted_status_message)
            QMessageBox.information(
                self.window,
                prompt.accepted_info_title,
                prompt.accepted_info_message,
            )

    def prepare_close(self, event) -> bool:
        form_controller = getattr(self.window, "form_controller", None)
        should_confirm_discard = (
            not getattr(self.window, "_skip_close_discard_confirmation", False)
            and form_controller is not None
        )
        if should_confirm_discard and not form_controller.confirm_discard_changes("fechar a janela"):
            event.ignore()
            return False

        self.stop_owned_timers()
        settings_controller = getattr(self.window, "settings_controller", None)
        if settings_controller is not None:
            settings_controller.save_before_close()

        if hasattr(self.window, "support_controller"):
            self.window.support_controller.shutdown()

        if hasattr(self.window, "job_runner"):
            self.window.job_runner.shutdown_all_workers()

        return True

    def stop_owned_timers(self):
        stop_active_timer(getattr(self.window, "_startup_window_timer", None))
        stop_active_timer(getattr(self.window, "_initial_map_sync_timer", None))
