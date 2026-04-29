import os


APP_NAME = "Plataforma de Gestão Ambiental"
APP_WINDOW_TITLE = APP_NAME
APP_BRAND_TAGLINE = "Gestão territorial e monitoramento ambiental"
APP_SETTINGS_ORG = "CompensacoesApp"
APP_SETTINGS_NAME = "CompensacoesDesktop"
APP_COMPANY_NAME = "CompensacoesApp"
APP_PRODUCT_DESCRIPTION = "Gestão territorial e monitoramento ambiental"
APP_EXECUTABLE_NAME = "Compensacoes.exe"
APP_INSTALLER_ID = "CompensacoesApp.CompensacoesDesktop"
APP_INSTALLER_BASENAME = "Compensacoes-Setup"
APP_REPOSITORY_URL = "https://github.com/DavidWIA2/Compensacoes_app"
APP_RELEASES_URL = f"{APP_REPOSITORY_URL}/releases"

DEFAULT_MAP_LAYER = "Satelite"
DEFAULT_THEME_DARK_MODE = False
MAP_ENGINE = os.getenv("COMP_MAP_ENGINE", "maplibre").strip().lower() or "maplibre"
MAP_FALLBACK_ENGINE = os.getenv("COMP_MAP_FALLBACK_ENGINE", "leaflet").strip().lower() or "leaflet"
MAP_DEFAULT_BASE_LAYER = os.getenv("COMP_MAP_DEFAULT_BASE_LAYER", "satellite").strip().lower() or "satellite"
MAP_PROVIDER = os.getenv("COMP_MAP_PROVIDER", "osm_esri").strip().lower() or "osm_esri"
GEOCODER_PROVIDER = os.getenv("COMP_GEOCODER_PROVIDER", "nominatim").strip().lower() or "nominatim"
GEOCODER_FALLBACK_PROVIDER = os.getenv("COMP_GEOCODER_FALLBACK_PROVIDER", "arcgis").strip().lower() or "arcgis"
GEOCODER_RATE_LIMIT_SECONDS = float(os.getenv("COMP_GEOCODER_RATE_LIMIT_SECONDS", "1.0") or 1.0)
GEOCODER_USER_AGENT = "PlataformaGestaoAmbiental/1.0 (contato: davidwilian2014@gmail.com)"
UPDATE_URL_ENV_VAR = "COMPENSACOES_UPDATE_URL"
DEFAULT_UPDATE_MANIFEST_URL = f"{APP_RELEASES_URL}/latest/download/latest.json"
SUPABASE_PRODUCTION_URL_ENV_VAR = "COMPENSACOES_SUPABASE_PROD_URL"
SUPABASE_PRODUCTION_KEY_ENV_VAR = "COMPENSACOES_SUPABASE_PROD_PUBLISHABLE_KEY"
SUPABASE_DEMO_URL_ENV_VAR = "COMPENSACOES_SUPABASE_DEMO_URL"
SUPABASE_DEMO_KEY_ENV_VAR = "COMPENSACOES_SUPABASE_DEMO_PUBLISHABLE_KEY"
DEFAULT_SUPABASE_PRODUCTION_URL = "https://yonvcnnkewzoqwnnmcdx.supabase.co"
DEFAULT_SUPABASE_PRODUCTION_PUBLISHABLE_KEY = "sb_publishable_89kyRD3GfnaLBZmwnlkA_g_4a_k5_5R"
DEFAULT_CORPORATE_EMAIL_DOMAIN = "saocarlos.sp.gov.br"
DEFAULT_CORPORATE_EMAIL_SUFFIX = f"@{DEFAULT_CORPORATE_EMAIL_DOMAIN}"

SEARCH_FILTER_DEBOUNCE_MS = 180


def resolve_update_manifest_url(explicit_url: str = "") -> str:
    return str(explicit_url or os.getenv(UPDATE_URL_ENV_VAR, "") or DEFAULT_UPDATE_MANIFEST_URL).strip()


def normalize_corporate_email(
    email: str,
    *,
    default_domain: str = DEFAULT_CORPORATE_EMAIL_DOMAIN,
) -> str:
    normalized = str(email or "").strip()
    if not normalized:
        return ""
    if "@" not in normalized:
        normalized = f"{normalized}@{default_domain}"
    return normalized.lower()


def display_corporate_email_local_part(
    email: str,
    *,
    default_domain: str = DEFAULT_CORPORATE_EMAIL_DOMAIN,
) -> str:
    normalized = str(email or "").strip()
    if not normalized:
        return ""
    suffix = f"@{default_domain}".lower()
    if normalized.lower().endswith(suffix):
        return normalized[: -len(suffix)]
    return normalized
