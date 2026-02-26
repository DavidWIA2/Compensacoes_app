import os
import sys

# Corrige os caminhos do GeoPandas/Fiona/PyProj dentro do executável
if getattr(sys, 'frozen', False):
    exe_dir = os.path.dirname(sys.executable)
    internal_dir = os.path.join(exe_dir, "_internal")

    # Aponta as variáveis de ambiente para as pastas coletadas pelo PyInstaller
    os.environ["PROJ_LIB"] = os.path.join(internal_dir, "pyproj", "proj_dir", "share", "proj")
    os.environ["GDAL_DATA"] = os.path.join(internal_dir, "fiona", "gdal_data")

from app.main import main

if __name__ == '__main__':
    sys.exit(main())