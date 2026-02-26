from pathlib import Path
import geopandas as gpd

# raiz do projeto (ajuste se necessário)
# __file__ = .../app/tools/inspecionar_shp.py
# parents[0]=tools, [1]=app, [2]=projeto
PROJECT_ROOT = Path(__file__).resolve().parents[2]

SHP_NAME = "Microbacia_do_Agua_Quente.shp"  # <-- confira o nome exato do arquivo
shp_path = PROJECT_ROOT / "data" / "microbacias" / SHP_NAME

print("Projeto:", PROJECT_ROOT)
print("Tentando abrir:", shp_path)

if not shp_path.exists():
    print("\n❌ Arquivo não encontrado.")
    print("Arquivos .shp disponíveis na pasta:")
    for p in sorted((PROJECT_ROOT / "data" / "microbacias").glob("*.shp")):
        print(" -", p.name)
    raise SystemExit(1)

gdf = gpd.read_file(shp_path)

print("\n✅ OK! CRS:", gdf.crs)
print("Colunas:", list(gdf.columns))
print("\nAmostra:")
print(gdf.head(3))

