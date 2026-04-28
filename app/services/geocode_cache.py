import json
import os
import time
from typing import Any, Dict, Optional, Tuple

from app.utils.app_paths import resolve_data_path
from app.utils.logger import logger

CACHE_FILE = str(resolve_data_path("geocode_cache.json"))

# Expiracao de 30 dias (30 * 24 * 60 * 60 segundos)
EXPIRATION_SECONDS = 2592000


class GeocodeCache:
    def __init__(self, cache_file: str):
        self.cache_file = cache_file
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        """Carrega o cache do arquivo JSON com suporte a retrocompatibilidade."""
        if not os.path.exists(self.cache_file):
            return

        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._cache = {}
                for key, value in data.items():
                    # Formato antigo: { address: [lat, lon] }
                    if isinstance(value, list) and len(value) == 2:
                        self._cache[key] = {
                            "coords": tuple(value),
                            "timestamp": time.time(),
                            "confirmed": False,
                            "label": "",
                        }
                    # Formato novo: { address: {"coords": [lat, lon], "timestamp": float} }
                    elif isinstance(value, dict) and "coords" in value and "timestamp" in value:
                        self._cache[key] = {
                            "coords": tuple(value["coords"]),
                            "timestamp": value["timestamp"],
                            "confirmed": bool(value.get("confirmed", False)),
                            "label": str(value.get("label", "") or ""),
                        }
        except Exception as exc:
            logger.error(f"[GeocodeCache] Erro ao carregar cache: {exc}")
            self._cache = {}

    def _save(self):
        """Salva o cache no arquivo JSON."""
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=4, ensure_ascii=False)
        except Exception as exc:
            logger.error(f"[GeocodeCache] Erro ao salvar cache: {exc}")

    def get(self, address: str) -> Optional[Tuple[float, float]]:
        """Busca um endereco no cache se nao estiver expirado."""
        entry = self._cache.get(address)
        if not entry:
            return None

        if not entry.get("confirmed") and time.time() - entry["timestamp"] > EXPIRATION_SECONDS:
            del self._cache[address]
            return None

        return entry["coords"]

    def set(self, address: str, lat: float, lon: float, *, confirmed: bool = False, label: str = ""):
        """Salva um endereco no cache e persiste no disco."""
        self._cache[address] = {
            "coords": (lat, lon),
            "timestamp": time.time(),
            "confirmed": bool(confirmed),
            "label": str(label or ""),
        }
        self._save()

    def clear(self):
        """Limpa o cache em memoria e no disco."""
        self._cache = {}
        if os.path.exists(self.cache_file):
            try:
                os.remove(self.cache_file)
            except Exception:
                pass


# Instancia unica global para o sistema
geocode_cache = GeocodeCache(CACHE_FILE)
