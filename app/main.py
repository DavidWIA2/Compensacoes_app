import os
import sys
import time
import ctypes

# =====================================================================
# BLINDAGEM DE CAMINHOS
# =====================================================================
projeto_raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if projeto_raiz not in sys.path:
    sys.path.insert(0, projeto_raiz)

os.environ[
    "QTWEBENGINE_CHROMIUM_FLAGS"
] = "--ignore-certificate-errors --disable-quic --disable-gpu"

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QMovie, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QSplashScreen, QWidget

from app.config import APP_BRAND_TAGLINE, APP_INSTALLER_ID, APP_NAME, APP_SETTINGS_NAME, APP_SETTINGS_ORG
from app.services.access_service import SupabaseAccessService
from app.services.app_settings import AppSettings
from app.services.tile_scheme_handler import install_tile_scheme, register_tile_scheme
from app.ui.components.ui_utils import build_app_icon, resource_path
from app.ui.components.access_dialog import AccessDialog
from app.ui.main_window import MainWindow
from app.utils.logger import LOG_FILE, get_logger


logger = get_logger("Startup")


# =====================================================================
# CLASSE DO SPLASH ANIMADO (FLUIDA)
# =====================================================================
class AnimatedSplashScreen(QSplashScreen):
    def __init__(self, gif_path, splash_path):
        pixmap = QPixmap(splash_path)
        super().__init__(pixmap)

        self.label_gif = QLabel(self)
        self.movie = QMovie(gif_path)
        gif_size = QSize(92, 92)
        self.movie.setScaledSize(gif_size)
        self.label_gif.setMovie(self.movie)

        x_gif = (pixmap.width() - gif_size.width()) // 2
        y_gif = int(pixmap.height() * 0.69)
        self.label_gif.setGeometry(x_gif, y_gif, gif_size.width(), gif_size.height())

        self.label_status = QLabel(APP_BRAND_TAGLINE, self)
        self.label_status.setStyleSheet(
            "color: rgba(255, 255, 255, 0.96); font-weight: 600; background-color: transparent;"
        )
        self.label_status.setFont(QFont("Segoe UI", 10))
        self.label_status.setAlignment(Qt.AlignCenter)
        status_width = min(int(pixmap.width() * 0.72), 900)
        status_x = (pixmap.width() - status_width) // 2
        status_y = y_gif + gif_size.height() + 14
        self.label_status.setGeometry(status_x, status_y, status_width, 26)

        self.movie.start()

    def update_status(self, message, delay=0.1):
        """Atualiza o texto e processa eventos para manter o GIF rodando."""
        self.label_status.setText(message)
        for _ in range(10):
            QApplication.processEvents()
            time.sleep(delay / 10)


def resolve_startup_assets():
    gif_path = resource_path("assets", "loading.gif")
    splash_path = resource_path("assets", "Splash.png")
    if os.path.exists(gif_path) and os.path.exists(splash_path):
        return gif_path, splash_path
    return None, None


def create_startup_splash():
    gif_path, splash_path = resolve_startup_assets()
    if not gif_path or not splash_path:
        return None
    return AnimatedSplashScreen(gif_path, splash_path)


def create_startup_transition_guard() -> QWidget:
    guard = QWidget()
    guard.setObjectName("StartupTransitionGuard")
    guard.setWindowFlag(Qt.Tool, True)
    guard.setAttribute(Qt.WA_DontShowOnScreen, True)
    guard.setAttribute(Qt.WA_ShowWithoutActivating, True)
    guard.resize(1, 1)
    guard.move(-10000, -10000)
    guard.show()
    return guard


def release_startup_transition_guard(guard: QWidget | None) -> None:
    if guard is None:
        return
    guard.hide()
    guard.close()
    guard.deleteLater()


def request_app_access() -> object | None:
    settings = AppSettings()
    dialog = AccessDialog(
        settings=settings,
        access_service=SupabaseAccessService(),
    )
    if not dialog.exec():
        return None
    return dialog.access_session


def apply_windows_app_user_model_id(app_id: str = APP_INSTALLER_ID) -> None:
    if os.name != "nt":
        return

    normalized_app_id = str(app_id or "").strip()
    if not normalized_app_id:
        return

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(normalized_app_id)
    except Exception as exc:
        logger.warning(f"Falha ao definir AppUserModelID do Windows: {exc}")


# =====================================================================
# FUNCAO PRINCIPAL
# =====================================================================
def main() -> int:
    apply_windows_app_user_model_id()
    app = QApplication(sys.argv)
    if hasattr(app, "setQuitOnLastWindowClosed"):
        app.setQuitOnLastWindowClosed(False)
    about_to_quit = getattr(app, "aboutToQuit", None)
    if about_to_quit is not None and hasattr(about_to_quit, "connect"):
        about_to_quit.connect(
            lambda: logger.warning("QApplication.aboutToQuit disparado durante a transição de login.")
        )
    app.setOrganizationName(APP_SETTINGS_ORG)
    app.setApplicationName(APP_SETTINGS_NAME)
    app.setApplicationDisplayName(APP_NAME)
    if hasattr(app, "setWindowIcon"):
        app_icon = build_app_icon()
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)

    transition_guard = create_startup_transition_guard()
    access_session = request_app_access()
    if access_session is None:
        release_startup_transition_guard(transition_guard)
        return 0

    splash = create_startup_splash()
    if splash is not None:
        splash.show()
        splash.update_status("Preparando recursos...")

    register_tile_scheme()
    install_tile_scheme()

    if splash is not None:
        splash.update_status("Carregando interface...")

    try:
        window = MainWindow(access_session=access_session)

        if splash is not None:
            splash.update_status("Abrindo painel principal...")

        window.show()
        if hasattr(app, "setQuitOnLastWindowClosed"):
            app.setQuitOnLastWindowClosed(True)
        release_startup_transition_guard(transition_guard)
        if splash is not None:
            process_events = getattr(QApplication, "processEvents", None)
            if callable(process_events):
                process_events()
            splash.finish(window)
    except Exception as exc:
        logger.exception("Falha ao abrir a janela principal após o login.")
        if splash is not None:
            splash.close()
        release_startup_transition_guard(transition_guard)
        QMessageBox.critical(
            None,
            "Falha ao abrir o aplicativo",
            (
                "O login foi concluído, mas a janela principal não pôde ser aberta.\n\n"
                f"Erro: {exc}\n\n"
                f"Detalhes foram gravados em:\n{LOG_FILE}"
            ),
        )
        return 1

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
