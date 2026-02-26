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
    "QTWEBENGINE_CHROMIUM_FLAGS"] = "--ignore-certificate-errors --disable-quic --disable-gpu --disable-web-security --no-sandbox"
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"

from PySide6.QtWidgets import QApplication, QSplashScreen, QLabel
from PySide6.QtGui import QMovie, QPixmap, QFont
from PySide6.QtCore import Qt, QSize, QTimer
from app.ui.main_window import MainWindow, resource_path


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
            "color: #FFD700; font-weight: bold; background-color: rgba(0, 0, 0, 80); border-radius: 5px;")
        self.label_status.setFont(QFont("Segoe UI", 10))
        self.label_status.setAlignment(Qt.AlignCenter)
        self.label_status.setGeometry(0, pixmap.height() - 45, pixmap.width(), 30)

        self.movie.start()

    def update_status(self, message, delay=0.1):
        """Atualiza o texto e processa eventos para manter o GIF rodando"""
        self.label_status.setText(message)
        # O segredo da fluidez: processar eventos várias vezes
        for _ in range(10):
            QApplication.processEvents()
            time.sleep(delay / 10)


# =====================================================================
# FUNÇÃO PRINCIPAL
# =====================================================================
def main() -> int:
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(u'pmsc.compensacoes.v1')

    app = QApplication(sys.argv)

    splash_img = resource_path("assets", "splash.png")
    loading_gif = resource_path("assets", "loading.gif")

    splash = None
    start_time = time.time()

    if os.path.exists(splash_img) and os.path.exists(loading_gif):
        splash = AnimatedSplashScreen(loading_gif, splash_img)
        splash.show()

    # Processa eventos iniciais
    QApplication.processEvents()

    if splash: splash.update_status("Carregando base de dados...", 0.2)

    # --- CARREGAMENTO REAL ---
    # Criamos a window. Se o carregamento no __init__ da MainWindow for muito longo,
    # o GIF pode dar micro-travadas. Reduzimos o delay aqui para compensar.
    window = MainWindow()

    if splash: splash.update_status("Sincronizando mapas...", 0.2)

    # Garante que o usuário veja a animação por pelo menos 4 segundos
    while time.time() - start_time < 4.0:
        QApplication.processEvents()  # Mantém o GIF vivo enquanto espera
        time.sleep(0.1)

    if splash:
        splash.finish(window)

    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())