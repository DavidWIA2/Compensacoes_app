import os
import sys
import glob
import json
import re
from typing import List

import geopandas as gpd
from shapely.geometry import Point
from shapely import force_2d


# =====================================================================
# UTILITÁRIO DE CAMINHO PARA PYINSTALLER
# =====================================================================
def resource_path(relative_path):
    """ Retorna o caminho absoluto para o recurso, compatível com PyInstaller """
    try:
        # Quando o PyInstaller empacota o app, ele usa sys._MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


class GisService:
    DE_PARA_NOMES = {
        "AGUA QUENTE": "Água Quente", "AGUA FRIA": "Água Fria", "GREGORIO": "Gregório",
        "PARAISO": "Paraíso", "TIJUCO PRETO": "Tijuco Preto",
        "SANTA MARIA DO LEME": "Santa Maria do Leme", "MONJOLINHO": "Monjolinho",
        "MINEIRINHO": "Mineirinho", "MEDEIROS": "Medeiros", "FAZZARI": "Fazzari",
        "JOCKEY": "Jockey", "ARACY": "Aracy", "CHIBARRO": "Chibarro"
    }

    def __init__(self, microbacias_dir: str, name_field: str):
        # 1) Se já veio um caminho válido, usa direto
        if os.path.isdir(microbacias_dir):
            self.microbacias_dir = os.path.abspath(microbacias_dir)

        else:
            # 2) Se for caminho absoluto (ex.: C:\... ), NÃO faça resource_path()
            #    (evita virar "_MEIPASS\\C:\\...")
            if os.path.isabs(microbacias_dir):
                self.microbacias_dir = microbacias_dir
            else:
                # 3) Se for relativo, resolve via PyInstaller/dev
                self.microbacias_dir = resource_path(microbacias_dir)

        self.name_field = name_field

        # Log de depuração (ajuda a ver onde ele está procurando no erro)
        if not os.path.isdir(self.microbacias_dir):
            print(f"DEBUG: Tentativa falhou em: {self.microbacias_dir}")

        # Agora o _load_folder recebe o caminho validado
        self.gdf = self._load_folder(self.microbacias_dir)

        if self.gdf.crs is None: raise ValueError("Microbacias sem CRS (.prj).")
        self.gdf = self.gdf.to_crs(epsg=4326)
        if self.name_field not in self.gdf.columns:
            raise ValueError(f"Campo '{name_field}' não existe nas microbacias.")
        self.sindex = self.gdf.sindex

    def _padronizar_nome(self, nome_arquivo_raw: str) -> str:
        nome = nome_arquivo_raw.replace('.shp', '').replace('_', ' ')
        nome = re.sub(r'(?i)^microbacia\s+(?:do\s+|da\s+|de\s+)?', '', nome).strip()
        nome_upper = nome.upper()
        if nome_upper in self.DE_PARA_NOMES: return self.DE_PARA_NOMES[nome_upper]
        return nome.title()

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
        self.gdf['geometry'] = self.gdf['geometry'].apply(force_2d)
        return json.loads(self.gdf.to_json())

    def find_microbacia(self, lat: float, lng: float) -> str:
        pt = Point(lng, lat)
        hit = self.gdf[self.gdf.contains(pt)]
        if not hit.empty:
            val = hit.iloc[0][self.name_field]
            return "" if val is None else str(val)

        gdf_utm = self.gdf.to_crs(epsg=31982)
        pt_utm = gpd.GeoSeries([pt], crs="EPSG:4326").to_crs(epsg=31982).iloc[0]

        distances = gdf_utm.distance(pt_utm)
        if distances.empty: return ""

        min_dist = distances.min()
        if min_dist < 500:
            closest_idx = distances.idxmin()
            val = self.gdf.loc[closest_idx, self.name_field]
            return "" if val is None else str(val)
        return ""

    def get_microbacia_centroid(self, nome: str) -> tuple:
        if not nome: return None
        nome = nome.strip()
        hit = self.gdf[self.gdf['Nome_Do_Arquivo'].str.upper() == nome.upper()]
        if hit.empty:
            nome_limpo = re.sub(r'(?i)^microbacia\s+(?:do\s+|da\s+|de\s+)?', '', nome).strip()
            if nome_limpo.upper() in self.DE_PARA_NOMES:
                nome_alvo = self.DE_PARA_NOMES[nome_limpo.upper()]
                hit = self.gdf[self.gdf['Nome_Do_Arquivo'] == nome_alvo]
            else:
                hit = self.gdf[self.gdf['Nome_Do_Arquivo'].str.upper() == nome_limpo.upper()]
        if hit.empty: return None
        pt = hit.geometry.centroid.iloc[0]
        return pt.y, pt.x