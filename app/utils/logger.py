import logging
import os
from logging.handlers import RotatingFileHandler

# Resolve o diretório raiz do projeto
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(BASE_DIR, "logs")

# Garante que o diretório de logs exista
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "app.log")

def setup_logger():
    logger = logging.getLogger("CompensacoesApp")
    logger.setLevel(logging.DEBUG)

    # Evita duplicação de handlers se for chamado várias vezes
    if not logger.handlers:
        # Formatador
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        # Handler de Console
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        # Handler de Arquivo (Rotativo: max 5MB, mantém 3 backups)
        file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)

        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger

# Instância global do logger
logger = setup_logger()
