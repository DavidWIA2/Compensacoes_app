from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Iterable

from app.services.records_service import remove_accents

def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_session_path(path: str, *, session_scheme: str = "session://") -> bool:
    return str(path or "").strip().lower().startswith(session_scheme)


def normalize_session_path(path: str, *, session_scheme: str = "session://") -> str:
    clean = str(path or "").strip()
    if not clean:
        return ""
    if is_session_path(clean, session_scheme=session_scheme):
        return clean
    return os.path.normcase(os.path.abspath(clean))


def stringify(value: object) -> str:
    return str(value or "").strip()


def microbacia_key(value: object) -> str:
    return stringify(value).upper()


def session_slug(value: str) -> str:
    normalized = remove_accents(stringify(value)).lower()
    slug = "".join(char.lower() if char.isalnum() else "-" for char in normalized).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "sessao"


def read_source_file_identity(workbook_path: str, *, session_scheme: str = "session://") -> tuple[int, int]:
    normalized_path = normalize_session_path(workbook_path, session_scheme=session_scheme)
    if not normalized_path or not os.path.exists(normalized_path):
        return 0, 0
    try:
        stat_result = os.stat(normalized_path)
    except OSError:
        return 0, 0
    return int(getattr(stat_result, "st_mtime_ns", 0) or 0), int(getattr(stat_result, "st_size", 0) or 0)


def display_name_for_path(workbook_path: str, *, session_scheme: str = "session://") -> str:
    normalized_path = normalize_session_path(workbook_path, session_scheme=session_scheme)
    if is_session_path(normalized_path, session_scheme=session_scheme):
        return normalized_path.removeprefix(session_scheme) or normalized_path
    return os.path.basename(normalized_path) or normalized_path


def build_unique_session_path(
    session_name: str,
    *,
    existing_paths: Iterable[str],
    session_scheme: str = "session://",
) -> str:
    slug = session_slug(session_name)
    existing = {normalize_session_path(path, session_scheme=session_scheme) for path in existing_paths}
    candidate = f"{session_scheme}{slug}"
    suffix = 2
    while candidate in existing:
        candidate = f"{session_scheme}{slug}-{suffix}"
        suffix += 1
    return candidate


def decode_json_value(raw_value: object) -> Any:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def decode_json_object(raw_value: object) -> dict[str, Any]:
    decoded = decode_json_value(raw_value)
    if isinstance(decoded, dict):
        return decoded
    return {}
