import os
import glob
import json
import re
import unicodedata
from typing import Dict, List, Optional

import geopandas as gpd
from shapely.geometry import Point
from shapely import force_2d

from app.utils.app_paths import resolve_resource_path
from app.utils.logger import get_logger


logger = get_logger("GIS")


class GisService:
    DE_PARA_NOMES = {
        "AGUA QUENTE": "Água Quente", "AGUA FRIA": "Água Fria", "GREGORIO": "Gregório",
        "PARAISO": "Paraíso", "TIJUCO PRETO": "Tijuco Preto",
        "SANTA MARIA DO LEME": "Santa Maria do Leme", "MONJOLINHO": "Monjolinho",
        "MINEIRINHO": "Mineirinho", "MEDEIROS": "Medeiros", "FAZZARI": "Fazzari",
        "JOCKEY": "Jockey", "ARACY": "Aracy", "CHIBARRO": "Chibarro"
    }

    def __init__(self, microbacias_dir: str, name_field: str):
        # Se for caminho absoluto (ex.: C:\...), usa direto
        if os.path.isabs(microbacias_dir):
            self.microbacias_dir = microbacias_dir
        else:
            # Se for relativo (ex: "data/microbacias"), resolve via PyInstaller/dev
            self.microbacias_dir = resolve_resource_path(microbacias_dir)

        self.name_field = name_field

        # Log de depuração essencial para ver o caminho final no executável
        if not os.path.isdir(self.microbacias_dir):
            logger.error(f"ERRO GIS: Pasta nao encontrada em: {self.microbacias_dir}")
            raise ValueError(f"Diretório de microbacias não encontrado: {self.microbacias_dir}")

        # Carrega os arquivos .shp encontrados na pasta resolvida
        self.gdf = self._load_folder(self.microbacias_dir)

        if self.gdf.crs is None:
            raise ValueError("Microbacias sem arquivo de projeção (.prj).")

        self.gdf = self.gdf.to_crs(epsg=4326)

        if self.name_field not in self.gdf.columns:
            raise ValueError(f"Campo '{name_field}' não existe nas microbacias.")

        self.sindex = self.gdf.sindex
        self.metric_crs = self.gdf.estimate_utm_crs()
        self.gdf_metric = self.gdf.to_crs(self.metric_crs)
        self._geojson_obj = None
        self._centroid_cache: Dict[str, tuple] = {}
        self._build_name_lookup_cache()

    def _padronizar_nome(self, nome_arquivo_raw: str) -> str:
        nome = nome_arquivo_raw.replace('.shp', '').replace('_', ' ')
        nome = re.sub(r'(?i)^microbacia\s+(?:do\s+|da\s+|de\s+)?', '', nome).strip()
        nome_upper = nome.upper()
        if nome_upper in self.DE_PARA_NOMES: return self.DE_PARA_NOMES[nome_upper]
        return nome.title()

    def _lookup_key(self, nome: str) -> str:
        if nome is None:
            return ""
        nome = unicodedata.normalize("NFKD", str(nome).strip())
        nome = "".join(ch for ch in nome if not unicodedata.combining(ch))
        return nome.upper()

    def _build_name_lookup_cache(self):
        nomes = self.gdf[self.name_field].fillna("").astype(str)
        self._name_field_keys = nomes.apply(self._lookup_key)
        self._known_names = {}
        for nome in nomes:
            key = self._lookup_key(nome)
            if key and key not in self._known_names:
                self._known_names[key] = nome
        if not hasattr(self, "_centroid_cache"):
            self._centroid_cache = {}

    def _load_folder(self, folder: str) -> gpd.GeoDataFrame:
        # A verificação agora é feita sobre o caminho absoluto resolvido
        if not os.path.isdir(folder):
            raise ValueError(f"Erro: Pasta {folder} não encontrada.")

        shp_files = sorted(glob.glob(os.path.join(folder, "*.shp")))
        if not shp_files:
            raise ValueError(f"Nenhum .shp encontrado na pasta: {folder}")

        gdfs: List[gpd.GeoDataFrame] = []
        crs_ref = None
        for shp in shp_files:
            g = gpd.read_file(shp, engine="pyogrio")
            if g.empty: continue
            filename = os.path.basename(shp)
            nome_oficial = self._padronizar_nome(filename)
            g['Nome_Do_Arquivo'] = nome_oficial
            if g.crs is None: raise ValueError(f"Shapefile sem CRS (.prj): {os.path.basename(shp)}")
            if crs_ref is None:
                crs_ref = g.crs
            else:
                if str(g.crs) != str(crs_ref): g = g.to_crs(crs_ref)
            gdfs.append(g)

        if not gdfs: raise ValueError("Nenhuma feição válida encontrada nos shapefiles.")
        import pandas as pd
        merged = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs=crs_ref)
        return merged

    def to_geojson_obj(self) -> dict:
        if self._geojson_obj is None:
            gdf_2d = self.gdf.copy()
            gdf_2d['geometry'] = gdf_2d['geometry'].apply(force_2d)
            self._geojson_obj = json.loads(gdf_2d.to_json())
        return self._geojson_obj

    def find_microbacia(self, lat: float, lng: float) -> str:
        pt = Point(lng, lat)
        candidate_idx = None
        try:
            if self.sindex is not None:
                candidate_idx = list(self.sindex.intersection(pt.bounds))
        except Exception:
            candidate_idx = None

        candidates = self.gdf.iloc[candidate_idx] if candidate_idx else self.gdf
        hit = candidates[candidates.contains(pt)]
        if not hit.empty:
            val = hit.iloc[0][self.name_field]
            return "" if val is None else str(val)

        pt_utm = gpd.GeoSeries([pt], crs="EPSG:4326").to_crs(self.metric_crs).iloc[0]

        distances = self.gdf_metric.distance(pt_utm)
        if distances.empty: return ""

        min_dist = distances.min()
        if min_dist < 500:
            closest_idx = distances.idxmin()
            val = self.gdf.loc[closest_idx, self.name_field]
            return "" if val is None else str(val)
        return ""

    def _resolve_name_field_value(self, nome: str) -> Optional[str]:
        if not hasattr(self, "_known_names") or not hasattr(self, "_name_field_keys"):
            self._build_name_lookup_cache()

        nome = (nome or "").strip()
        if not nome:
            return None

        direct = self._known_names.get(self._lookup_key(nome))
        if direct:
            return direct

        nome_limpo = re.sub(r'(?i)^microbacia\s+(?:do\s+|da\s+|de\s+)?', '', nome).strip()
        if not nome_limpo:
            return None

        alias = self.DE_PARA_NOMES.get(nome_limpo.upper())
        if alias:
            resolved_alias = self._known_names.get(self._lookup_key(alias))
            if resolved_alias:
                return resolved_alias

        return self._known_names.get(self._lookup_key(nome_limpo))

    def list_microbacias(self) -> list[str]:
        if not hasattr(self, "_known_names"):
            self._build_name_lookup_cache()
        return sorted(
            (str(nome).strip() for nome in self._known_names.values() if str(nome).strip()),
            key=self._lookup_key,
        )

    def normalize_microbacia_name(self, nome: str) -> str:
        nome_resolvido = self._resolve_name_field_value(nome)
        if nome_resolvido:
            return nome_resolvido
        return (nome or "").strip()

    def get_microbacia_centroid(self, nome: str) -> tuple:
        nome_resolvido = self._resolve_name_field_value(nome)
        if not nome_resolvido:
            return None

        if nome_resolvido in self._centroid_cache:
            return self._centroid_cache[nome_resolvido]

        mask = self._name_field_keys == self._lookup_key(nome_resolvido)
        if not mask.any():
            return None

        pt_metric = self.gdf_metric.loc[mask, "geometry"].centroid.iloc[0]
        pt = gpd.GeoSeries([pt_metric], crs=self.metric_crs).to_crs(epsg=4326).iloc[0]
        centroid = (pt.y, pt.x)
        self._centroid_cache[nome_resolvido] = centroid
        return centroid
