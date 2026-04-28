from __future__ import annotations

import os
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from app.utils.app_paths import ensure_dir, resolve_data_path
from app.config import MAPBOX_TOKEN_ENV_VAR as CONFIGURED_MAPBOX_TOKEN_ENV_VAR


MAPBOX_LAYER_NAME = "Mapbox Satelite"
MAPBOX_ACCESS_TOKEN_ENV_VAR = "MAPBOX_ACCESS_TOKEN"
MAPBOX_TOKEN_ENV_VAR = CONFIGURED_MAPBOX_TOKEN_ENV_VAR
COMP_MAPBOX_ACCESS_TOKEN_ENV_VAR = "COMP_MAPBOX_ACCESS_TOKEN"
MAPBOX_TOKEN_FILE_ENV_VAR = "COMP_MAPBOX_TOKEN_FILE"
MAPBOX_TILE_LIMIT_ENV_VAR = "COMP_MAPBOX_TILE_LIMIT"
DEFAULT_MAPBOX_TOKEN_FILE_NAME = "mapbox_token.txt"
DEFAULT_MAPBOX_USAGE_FILE_NAME = "mapbox_usage.json"
DEFAULT_MAPBOX_MONTHLY_TILE_LIMIT = 5000
MAX_MAPBOX_MONTHLY_TILE_LIMIT = 200000


@dataclass(frozen=True)
class MapboxUsage:
    month: str
    tiles_used: int
    monthly_limit: int

    @property
    def remaining(self) -> int:
        return max(self.monthly_limit - self.tiles_used, 0)

    @property
    def limit_reached(self) -> bool:
        return self.monthly_limit > 0 and self.tiles_used >= self.monthly_limit


def clean_mapbox_access_token(raw_token: str | None) -> str:
    token = str(raw_token or "").strip()
    if not token:
        return ""
    return token.splitlines()[0].strip()


def normalize_mapbox_tile_limit(value: object, default: int = DEFAULT_MAPBOX_MONTHLY_TILE_LIMIT) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = int(default)
    if parsed <= 0:
        return int(default)
    return min(parsed, MAX_MAPBOX_MONTHLY_TILE_LIMIT)


def resolve_mapbox_token_file_path() -> Path:
    explicit_path = clean_mapbox_access_token(os.getenv(MAPBOX_TOKEN_FILE_ENV_VAR))
    if explicit_path:
        return Path(explicit_path).expanduser()
    return resolve_data_path(DEFAULT_MAPBOX_TOKEN_FILE_NAME)


def resolve_mapbox_usage_file_path() -> Path:
    return resolve_data_path(DEFAULT_MAPBOX_USAGE_FILE_NAME)


def current_mapbox_usage_month(today: date | None = None) -> str:
    current_date = today or date.today()
    return current_date.strftime("%Y-%m")


def read_saved_mapbox_access_token() -> str:
    path = resolve_mapbox_token_file_path()
    if not path.exists():
        return ""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            token = clean_mapbox_access_token(line)
            if token and not token.startswith("#"):
                return token
    except OSError:
        return ""
    return ""


def resolve_mapbox_access_token() -> str:
    for env_var in (MAPBOX_TOKEN_ENV_VAR, MAPBOX_ACCESS_TOKEN_ENV_VAR, COMP_MAPBOX_ACCESS_TOKEN_ENV_VAR):
        token = clean_mapbox_access_token(os.getenv(env_var))
        if token:
            return token
    return read_saved_mapbox_access_token()


def _read_mapbox_usage_payload() -> dict:
    path = resolve_mapbox_usage_file_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_mapbox_usage_payload(payload: dict) -> None:
    path = resolve_mapbox_usage_file_path()
    ensure_dir(path.parent)
    safe_payload = dict(payload or {})
    safe_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(safe_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_mapbox_monthly_tile_limit() -> int:
    env_limit = os.getenv(MAPBOX_TILE_LIMIT_ENV_VAR)
    if env_limit:
        return normalize_mapbox_tile_limit(env_limit)
    payload = _read_mapbox_usage_payload()
    saved_limit = payload.get("monthly_limit")
    if saved_limit:
        return normalize_mapbox_tile_limit(saved_limit)
    return DEFAULT_MAPBOX_MONTHLY_TILE_LIMIT


def save_mapbox_monthly_tile_limit(limit: object) -> MapboxUsage:
    usage = read_mapbox_usage()
    monthly_limit = normalize_mapbox_tile_limit(limit)
    payload = {
        "month": usage.month,
        "tiles_used": min(int(usage.tiles_used), monthly_limit),
        "monthly_limit": monthly_limit,
    }
    _write_mapbox_usage_payload(payload)
    return MapboxUsage(
        month=str(payload["month"]),
        tiles_used=int(payload["tiles_used"]),
        monthly_limit=monthly_limit,
    )


def read_mapbox_usage(month: str | None = None) -> MapboxUsage:
    target_month = str(month or current_mapbox_usage_month())
    payload = _read_mapbox_usage_payload()
    monthly_limit = resolve_mapbox_monthly_tile_limit()
    saved_month = str(payload.get("month") or target_month)
    tiles_used = int(payload.get("tiles_used") or 0) if saved_month == target_month else 0
    return MapboxUsage(
        month=target_month,
        tiles_used=max(tiles_used, 0),
        monthly_limit=monthly_limit,
    )


def record_mapbox_tile_requests(count: int, *, month: str | None = None) -> MapboxUsage:
    usage = read_mapbox_usage(month=month)
    increment = max(int(count or 0), 0)
    tiles_used = min(usage.tiles_used + increment, usage.monthly_limit)
    payload = {
        "month": usage.month,
        "tiles_used": tiles_used,
        "monthly_limit": usage.monthly_limit,
    }
    _write_mapbox_usage_payload(payload)
    return MapboxUsage(
        month=usage.month,
        tiles_used=tiles_used,
        monthly_limit=usage.monthly_limit,
    )


def save_mapbox_access_token(token: str | None) -> Path:
    path = resolve_mapbox_token_file_path()
    cleaned_token = clean_mapbox_access_token(token)
    if not cleaned_token:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return path

    ensure_dir(path.parent)
    path.write_text(f"{cleaned_token}\n", encoding="utf-8")
    return path


def redact_mapbox_access_token(token: str | None) -> str:
    cleaned_token = clean_mapbox_access_token(token)
    if not cleaned_token:
        return ""
    if len(cleaned_token) <= 12:
        return "*" * len(cleaned_token)
    return f"{cleaned_token[:6]}...{cleaned_token[-4:]}"
