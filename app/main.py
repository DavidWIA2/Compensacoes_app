import os
import sys
import time

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
from PySide6.QtWidgets import QApplication, QLabel, QSplashScreen

from app.config import APP_NAME, APP_SETTINGS_NAME, APP_SETTINGS_ORG
from app.services.access_service import SupabaseAccessService
from app.services.app_settings import AppSettings
from app.services.tile_scheme_handler import install_tile_scheme, register_tile_scheme
from app.ui.components.ui_utils import resource_path
from app.ui.components.access_dialog import AccessDialog
from app.ui.main_window import MainWindow


# =====================================================================
# CLASSE DO SPLASH ANIMADO (FLUIDA)
# =====================================================================
class AnimatedSplashScreen(QSplashScreen):
    def __init__(self, gif_path, splash_path):
        pixmap = QPixmap(splash_path)
        super().__init__(pixmap)

        self.label_gif = QLabel(self)
        self.movie = QMovie(gif_path)
        gif_size = QSize(60, 60)
        self.movie.setScaledSize(gif_size)
        self.label_gif.setMovie(self.movie)

        x_gif = ((pixmap.width() - gif_size.width()) // 2) + 80
        y_gif = (pixmap.height() // 2) + 80
        self.label_gif.setGeometry(x_gif, y_gif, gif_size.width(), gif_size.height())

        self.label_status = QLabel("Iniciando sistema...", self)
        self.label_status.setStyleSheet(
            "color: #FFD700; font-weight: bold; background-color: rgba(0, 0, 0, 80); border-radius: 5px;"
        )
        self.label_status.setFont(QFont("Segoe UI", 10))
        self.label_status.setAlignment(Qt.AlignCenter)
        self.label_status.setGeometry(0, pixmap.height() - 45, pixmap.width(), 30)

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


def request_app_access() -> object | None:
    settings = AppSettings()
    dialog = AccessDialog(
        settings=settings,
        access_service=SupabaseAccessService(),
    )
    if not dialog.exec():
        return None
    return dialog.access_session


# =====================================================================
# FUNCAO PRINCIPAL
# =====================================================================
def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName(APP_SETTINGS_ORG)
    app.setApplicationName(APP_SETTINGS_NAME)
    app.setApplicationDisplayName(APP_NAME)

    access_session = request_app_access()
    if access_session is None:
        return 0

    splash = create_startup_splash()
    if splash is not None:
        splash.show()
        splash.update_status("Preparando recursos...")

    register_tile_scheme()
    install_tile_scheme()

    if splash is not None:
        splash.update_status("Carregando interface...")

    window = MainWindow(access_session=access_session)

    if splash is not None:
        splash.update_status("Abrindo painel principal...")

    window.show()
    if splash is not None:
        process_events = getattr(QApplication, "processEvents", None)
        if callable(process_events):
            process_events()
        splash.finish(window)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
