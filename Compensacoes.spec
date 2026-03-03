# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    copy_metadata
)
import importlib.util
from PyInstaller.building.datastruct import Tree


def has_module(modname: str) -> bool:
    return importlib.util.find_spec(modname) is not None


def _normalize_pairs(items):
    """PyInstaller sometimes returns (src, dest, typecode). Analysis expects only (src, dest)."""
    out = []
    for it in items or []:
        try:
            if len(it) == 2:
                out.append((it[0], it[1]))
            elif len(it) == 3:
                out.append((it[0], it[1]))
        except Exception:
            pass
    return out


def safe_collect_data_files(modname: str):
    try:
        return _normalize_pairs(collect_data_files(modname))
    except Exception:
        return []


def safe_collect_dynamic_libs(modname: str):
    try:
        return _normalize_pairs(collect_dynamic_libs(modname))
    except Exception:
        return []


def safe_copy_metadata(distname: str):
    try:
        return _normalize_pairs(copy_metadata(distname))
    except Exception:
        return []


# --------------------------------------------------------------------
# Arquivos do projeto
# --------------------------------------------------------------------
# No seu arquivo .spec, substitua a linha Tree(...) por:
datas = [
    ('app/ui/map_leaflet.html', 'app/ui'),
    ('app/ui/vendor', 'app/ui/vendor'),
    ('assets', 'assets'),
    ('data', 'data'), # ✅ Isso coloca a pasta 'data' na raiz do executável
]

binaries = []
hiddenimports = ['reportlab']

# --------------------------------------------------------------------
# Geo stack (GeoPandas no Windows)
# --------------------------------------------------------------------
if has_module('pyproj'):
    datas += safe_collect_data_files('pyproj')
    datas += safe_copy_metadata('pyproj')
    binaries += safe_collect_dynamic_libs('pyproj')
    hiddenimports += ['pyproj']

if has_module('shapely'):
    datas += safe_copy_metadata('shapely')
    binaries += safe_collect_dynamic_libs('shapely')
    hiddenimports += ['shapely', 'shapely.geometry']

if has_module('geopandas'):
    datas += safe_copy_metadata('geopandas')
    hiddenimports += ['geopandas']

if has_module('fiona'):
    # Fiona (metadata) - depende do build, tentamos ambos
    datas += safe_copy_metadata('Fiona')
    datas += safe_copy_metadata('fiona')
    binaries += safe_collect_dynamic_libs('fiona')
    hiddenimports += ['fiona']

if has_module('pyogrio'):
    from PyInstaller.utils.hooks import collect_submodules, collect_data_files
    datas += safe_collect_data_files('pyogrio')
    binaries += safe_collect_dynamic_libs('pyogrio')
    hiddenimports += collect_submodules('pyogrio')
    hiddenimports += ['pyogrio._err', 'pyogrio._geometry', 'pyogrio._io', 'pyogrio._ogr']


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