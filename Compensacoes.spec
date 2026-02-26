# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    copy_metadata
)
import importlib.util

def has_module(modname: str) -> bool:
    return importlib.util.find_spec(modname) is not None

def safe_collect_data_files(modname: str):
    try:
        return collect_data_files(modname)
    except Exception:
        return []

def safe_collect_dynamic_libs(modname: str):
    try:
        return collect_dynamic_libs(modname)
    except Exception:
        return []

def safe_copy_metadata(distname: str):
    try:
        return copy_metadata(distname)
    except Exception:
        return []

# --------------------------------------------------------------------
# Arquivos do seu projeto
# --------------------------------------------------------------------
datas = [
    ('app/ui/map_leaflet.html', 'app/ui'),
    ('app/ui/vendor', 'app/ui/vendor'),
    ('assets', 'assets'),
    ('data', 'data'),
]

binaries = []
hiddenimports = ['reportlab']

# --------------------------------------------------------------------
# Geo stack (GeoPandas no Windows)
# --------------------------------------------------------------------
# pyproj quase sempre precisa de data files (PROJ)
if has_module('pyproj'):
    datas += safe_collect_data_files('pyproj')
    datas += safe_copy_metadata('pyproj')
    binaries += safe_collect_dynamic_libs('pyproj')
    hiddenimports += ['pyproj']

# shapely (binário, às vezes precisa de libs)
if has_module('shapely'):
    datas += safe_copy_metadata('shapely')
    binaries += safe_collect_dynamic_libs('shapely')
    hiddenimports += ['shapely', 'shapely.geometry']

# geopandas (python puro)
if has_module('geopandas'):
    datas += safe_copy_metadata('geopandas')
    hiddenimports += ['geopandas']

# Fiona: o dist geralmente é "Fiona" (F maiúsculo).
# Além disso, fiona nem sempre é um "package" para coletar data_files.
if has_module('fiona'):
    datas += safe_copy_metadata('Fiona')
    datas += safe_copy_metadata('fiona')   # fallback se existir
    binaries += safe_collect_dynamic_libs('fiona')
    hiddenimports += ['fiona']

# Alternativa moderna (muitos setups usam pyogrio em vez de fiona)
if has_module('pyogrio'):
    datas += safe_copy_metadata('pyogrio')
    binaries += safe_collect_dynamic_libs('pyogrio')
    hiddenimports += ['pyogrio']

# --------------------------------------------------------------------
# Build
# --------------------------------------------------------------------
a = Analysis(
    ['app\\main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Compensacoes',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\app.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Compensacoes',
)