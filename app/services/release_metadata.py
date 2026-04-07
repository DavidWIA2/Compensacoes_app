from typing import Tuple

from app import __version__ as APP_VERSION
from app.config import APP_COMPANY_NAME, APP_EXECUTABLE_NAME, APP_NAME, APP_PRODUCT_DESCRIPTION

PRERELEASE_MARKERS = ("alpha", "beta", "rc", "preview", "pre")


def normalize_version_tuple(version: str) -> Tuple[int, int, int, int]:
    chunks = []
    for part in str(version or "").replace("-", ".").split("."):
        digits = "".join(char for char in part if char.isdigit())
        chunks.append(int(digits) if digits else 0)
        if len(chunks) >= 4:
            break

    while len(chunks) < 4:
        chunks.append(0)
    return tuple(chunks[:4])


def is_prerelease_version(version: str = APP_VERSION) -> bool:
    normalized = str(version or "").strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in PRERELEASE_MARKERS)


def release_channel_for_version(version: str = APP_VERSION) -> str:
    return "beta" if is_prerelease_version(version) else "stable"


def build_release_version_label(version: str = APP_VERSION) -> str:
    clean_version = str(version or "").strip()
    if not clean_version:
        return ""
    if is_prerelease_version(clean_version):
        return f"{clean_version} (BETA)"
    return clean_version


def build_release_display_name(version: str = APP_VERSION, *, app_name: str = APP_NAME) -> str:
    version_label = build_release_version_label(version)
    if not version_label:
        return str(app_name or "").strip()
    return f"{app_name} v{version_label}"


def build_windows_version_info(
    version: str = APP_VERSION,
    *,
    company_name: str = APP_COMPANY_NAME,
    product_name: str = APP_NAME,
    product_description: str = APP_PRODUCT_DESCRIPTION,
    original_filename: str = APP_EXECUTABLE_NAME,
) -> str:
    major, minor, patch, build = normalize_version_tuple(version)
    version_text = f"{major}.{minor}.{patch}.{build}"
    display_version = str(version or "").strip() or version_text
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, {build}),
    prodvers=({major}, {minor}, {patch}, {build}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040904B0',
        [
        StringStruct('CompanyName', '{company_name}'),
        StringStruct('FileDescription', '{product_description}'),
        StringStruct('FileVersion', '{version_text}'),
        StringStruct('InternalName', '{product_name}'),
        StringStruct('OriginalFilename', '{original_filename}'),
        StringStruct('ProductName', '{product_name}'),
        StringStruct('ProductVersion', '{display_version}')
        ])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)"""
