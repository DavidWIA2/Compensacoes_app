from __future__ import annotations

import importlib.machinery
import importlib.util
import site
import sys
import sysconfig
from pathlib import Path
from types import ModuleType


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _candidate_site_paths() -> list[str]:
    candidates: list[str] = []

    for getter in (getattr(site, "getsitepackages", None),):
        if not callable(getter):
            continue
        try:
            values = getter()
        except Exception:
            continue
        for value in values or ():
            if value:
                candidates.append(str(value))

    user_site = getattr(site, "getusersitepackages", lambda: "")()
    if user_site:
        candidates.append(str(user_site))

    for key in ("purelib", "platlib"):
        value = sysconfig.get_paths().get(key)
        if value:
            candidates.append(str(value))

    seen: set[Path] = set()
    normalized: list[str] = []
    for entry in candidates:
        try:
            resolved = Path(entry).resolve()
        except Exception:
            continue
        if not resolved.exists() or resolved in seen:
            continue
        seen.add(resolved)
        normalized.append(str(resolved))
    return normalized


def _module_is_external(module: ModuleType) -> bool:
    module_file = str(getattr(module, "__file__", "") or "").strip()
    if not module_file:
        return False
    try:
        resolved_module = Path(module_file).resolve()
    except Exception:
        return False
    try:
        resolved_project = _project_root()
        resolved_module.relative_to(resolved_project)
        return False
    except ValueError:
        return True


def load_supabase_create_client():
    existing = sys.modules.get("supabase")
    create_client = getattr(existing, "create_client", None) if existing is not None else None
    if existing is not None and callable(create_client) and _module_is_external(existing):
        return create_client

    search_paths = _candidate_site_paths()
    spec = importlib.machinery.PathFinder.find_spec("supabase", search_paths)
    if spec is None or spec.loader is None:
        raise ImportError("cannot import name 'create_client' from 'supabase'")

    module = None
    original_module = sys.modules.get("supabase")
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules["supabase"] = module
        spec.loader.exec_module(module)
    finally:
        if original_module is not None:
            sys.modules["supabase"] = original_module
        else:
            sys.modules.pop("supabase", None)

    create_client = getattr(module, "create_client", None)
    if not callable(create_client):
        raise ImportError("cannot import name 'create_client' from 'supabase'")
    return create_client
