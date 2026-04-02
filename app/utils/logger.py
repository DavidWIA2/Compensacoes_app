import logging
import os
import tempfile
from logging.handlers import RotatingFileHandler

from app.utils.app_paths import ensure_dir, resolve_logs_dir


def _resolve_safe_log_dir() -> str:
    candidates = [
        resolve_logs_dir(),
        os.path.join(tempfile.gettempdir(), "CompensacoesApp", "logs"),
    ]
    for candidate in candidates:
        try:
            return str(ensure_dir(candidate))
        except OSError:
            continue
    return tempfile.gettempdir()


LOG_DIR = _resolve_safe_log_dir()
LOG_FILE = os.path.join(LOG_DIR, "app.log")


def setup_logger():
    logger = logging.getLogger("CompensacoesApp")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)

        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger


logger = setup_logger()


def get_logger(component: str = ""):
    if not component:
        return logger
    clean_component = ".".join(part.strip() for part in str(component).split(".") if part.strip())
    return logger.getChild(clean_component)
