import os
import sys
from pathlib import Path

from app.config import APP_SETTINGS_NAME, APP_SETTINGS_ORG


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_app_data_dir(
    *,
    frozen: bool | None = None,
    project_root: str | Path | None = None,
    local_app_data: str | Path | None = None,
) -> Path:
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))

    if not frozen:
        return Path(project_root or PROJECT_ROOT)

    local_root = local_app_data or os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    if not local_root:
        local_root = Path.home() / "AppData" / "Local"

    return Path(local_root) / APP_SETTINGS_ORG / APP_SETTINGS_NAME


def resolve_logs_dir(
    *,
    frozen: bool | None = None,
    project_root: str | Path | None = None,
    local_app_data: str | Path | None = None,
) -> Path:
    base_dir = resolve_app_data_dir(
        frozen=frozen,
        project_root=project_root,
        local_app_data=local_app_data,
    )
    return base_dir / "logs"


def resolve_data_path(
    *parts: str,
    frozen: bool | None = None,
    project_root: str | Path | None = None,
    local_app_data: str | Path | None = None,
) -> Path:
    base_dir = resolve_app_data_dir(
        frozen=frozen,
        project_root=project_root,
        local_app_data=local_app_data,
    )
    return base_dir / "data" / Path(*parts)


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target
