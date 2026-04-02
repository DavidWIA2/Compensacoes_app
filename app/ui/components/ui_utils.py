import os
import sys
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QLibraryInfo, QTranslator
from app.utils.app_paths import resolve_resource_path
from app.utils.logger import logger

def _ajustar_ambiente_pyinstaller():
    """Garante que no executável as DLLs e dados possam ser encontrados."""
    try:
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(sys.executable)
            internal_dir = os.path.join(exe_dir, "_internal")
            os.environ["PATH"] = internal_dir + os.pathsep + exe_dir + os.pathsep + os.environ.get("PATH", "")
            if hasattr(sys, "_MEIPASS"):
                os.environ["PATH"] = sys._MEIPASS + os.pathsep + os.environ.get("PATH", "")
    except Exception as exc:
        logger.error(f"[BOOT] Falha ao ajustar ambiente do executavel: {exc}")

def resource_path(*partes: str) -> str:
    """Resolve caminhos em desenvolvimento e no executavel PyInstaller."""
    return resolve_resource_path(*partes)

def _setup_i18n():
    """Configura a tradução global para Português nos diálogos do sistema."""
    app = QApplication.instance()
    if not app:
        return
    path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    translator = QTranslator(app)
    if translator.load("qtbase_pt_BR", path):
        app.installTranslator(translator)

def msg_confirm(parent, title: str, text: str) -> bool:
    """Exibe um diálogo de confirmação com botões em português."""
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(QMessageBox.Question)
    btn_sim = msg.addButton("Sim", QMessageBox.YesRole)
    btn_nao = msg.addButton("Não", QMessageBox.NoRole)
    msg.setDefaultButton(btn_sim)
    msg.setEscapeButton(btn_nao)
    msg.exec()
    return msg.clickedButton() == btn_sim
