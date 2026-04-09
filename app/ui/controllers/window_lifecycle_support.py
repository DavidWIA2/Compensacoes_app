from __future__ import annotations

from dataclasses import dataclass

from app.ui.components.ui_utils import _setup_i18n


@dataclass(frozen=True)
class UpdatePromptContent:
    title: str
    question_message: str
    accepted_status_message: str
    accepted_info_title: str
    accepted_info_message: str


def build_update_prompt_content(version: str, notes: str) -> UpdatePromptContent:
    return UpdatePromptContent(
        title="Atualização Disponível",
        question_message=(
            f"Uma nova versão do aplicativo ({version}) está disponível!\n\n"
            f"Novidades:\n{notes}\n\nDeseja atualizar agora?"
        ),
        accepted_status_message="Baixando atualização em segundo plano...",
        accepted_info_title="Atualizador",
        accepted_info_message="A atualização será baixada. O aplicativo será reiniciado em breve.",
    )


def build_update_disconnect_callbacks(window, updater):
    disconnect_callbacks = []
    if hasattr(updater, "update_ready"):
        updater.update_ready.connect(window.present_update_offer)
        disconnect_callbacks.append(
            lambda updater=updater: updater.update_ready.disconnect(window.present_update_offer)
        )
    elif hasattr(updater, "update_available"):
        updater.update_available.connect(window._prompt_update)
        disconnect_callbacks.append(
            lambda updater=updater: updater.update_available.disconnect(window._prompt_update)
        )
    return disconnect_callbacks


def stop_active_timer(timer) -> None:
    if timer is not None and timer.isActive():
        timer.stop()


def run_startup_sequence(window) -> None:
    window._setup_menus()
    window._load_settings()
    window._connect_signals()
    window._setup_shortcuts()
    window.form_controller.setup_form_state_ui()
    window._startup_window_timer.start(0)

    _setup_i18n()
    window._load_last_session()
    window._apply_theme()

    window._update_form_action_buttons()
    window._update_address_search_enabled()
    window._refresh_window_chrome()
    window.setWindowModified(False)
    window.statusBar().showMessage("Pronto")
