import json
import os
import time
from typing import Dict, Optional, Tuple, Any
from app.utils.logger import logger

# Resolve o caminho para o arquivo de cache na pasta data
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_FILE = os.path.join(BASE_DIR, "data", "geocode_cache.json")

# Expiração de 30 dias (30 * 24 * 60 * 60 segundos)
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
                for k, v in data.items():
                    # Formato antigo: { address: [lat, lon] }
                    if isinstance(v, list) and len(v) == 2:
                        self._cache[k] = {"coords": tuple(v), "timestamp": time.time()}
                    # Formato novo: { address: {"coords": [lat, lon], "timestamp": float} }
                    elif isinstance(v, dict) and "coords" in v and "timestamp" in v:
                        self._cache[k] = {"coords": tuple(v["coords"]), "timestamp": v["timestamp"]}
        except Exception as e:
            logger.error(f"[GeocodeCache] Erro ao carregar cache: {e}")
            self._cache = {}

    def _save(self):
        """Salva o cache no arquivo JSON."""
        try:
            # Garante que a pasta data existe
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[GeocodeCache] Erro ao salvar cache: {e}")

    def get(self, address: str) -> Optional[Tuple[float, float]]:
        """Busca um endereço no cache se não estiver expirado."""
        entry = self._cache.get(address)
        if not entry:
            return None
            
        if time.time() - entry["timestamp"] > EXPIRATION_SECONDS:
            del self._cache[address]
            return None
            
        return entry["coords"]

    def set(self, address: str, lat: float, lon: float):
        """Salva um endereço no cache e persiste no disco."""
        self._cache[address] = {"coords": (lat, lon), "timestamp": time.time()}
        self._save()

    def clear(self):
        """Limpa o cache em memória e no disco."""
        self._cache = {}
        if os.path.exists(self.cache_file):
            try:
                os.remove(self.cache_file)
            except Exception:
                pass

# Instância única global para o sistema
geocode_cache = GeocodeCache(CACHE_FILE)
