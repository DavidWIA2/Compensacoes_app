import os

from app import __version__ as APP_VERSION


APP_NAME = "Compensações"
APP_WINDOW_TITLE = "Compensações - Cadastro e Consulta"
APP_SETTINGS_ORG = "CompensacoesApp"
APP_SETTINGS_NAME = "CompensacoesDesktop"
APP_COMPANY_NAME = "CompensacoesApp"
APP_PRODUCT_DESCRIPTION = "Gestao de compensacoes ambientais"
APP_EXECUTABLE_NAME = "Compensacoes.exe"
APP_INSTALLER_ID = "CompensacoesApp.CompensacoesDesktop"
APP_INSTALLER_BASENAME = "Compensacoes-Setup"
APP_REPOSITORY_URL = "https://github.com/DavidWIA2/Compensacoes_app"
APP_RELEASES_URL = f"{APP_REPOSITORY_URL}/releases"

DEFAULT_MAP_LAYER = "Mapa Claro"
DEFAULT_THEME_DARK_MODE = False
UPDATE_URL_ENV_VAR = "COMPENSACOES_UPDATE_URL"
DEFAULT_UPDATE_MANIFEST_URL = f"{APP_RELEASES_URL}/latest/download/latest.json"

SEARCH_FILTER_DEBOUNCE_MS = 180


def resolve_update_manifest_url(explicit_url: str = "") -> str:
    return str(explicit_url or os.getenv(UPDATE_URL_ENV_VAR, "") or DEFAULT_UPDATE_MANIFEST_URL).strip()
