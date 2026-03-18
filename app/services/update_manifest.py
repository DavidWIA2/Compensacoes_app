import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app import __version__ as APP_VERSION


def default_manifest_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_release_notes(notes: str) -> str:
    lines = [line.rstrip() for line in str(notes or "").strip().splitlines()]
    return "\n".join(line for line in lines if line.strip())


def build_release_manifest(
    *,
    version: str = APP_VERSION,
    notes: str = "",
    download_url: str = "",
    sha256: str = "",
    published_at: Optional[str] = None,
    homepage_url: str = "",
    filename: str = "",
    channel: str = "stable",
    signed: Optional[bool] = None,
    signature_mode: str = "",
) -> Dict[str, Any]:
    clean_version = str(version or "").strip()
    if not clean_version:
        raise ValueError("version is required")

    payload: Dict[str, Any] = {
        "version": clean_version,
        "notes": normalize_release_notes(notes),
        "published_at": str(published_at or default_manifest_timestamp()).strip(),
        "channel": str(channel or "stable").strip() or "stable",
    }

    if download_url:
        payload["download_url"] = str(download_url).strip()
    if homepage_url:
        payload["homepage_url"] = str(homepage_url).strip()
    if filename:
        payload["filename"] = str(filename).strip()
    if sha256:
        payload["sha256"] = str(sha256).strip().lower()
    if signed is not None:
        payload["signed"] = bool(signed)
    if signature_mode:
        payload["signature_mode"] = str(signature_mode).strip()

    return payload


def read_sha256_value(path: str) -> str:
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return ""
    return text.split()[0].strip().lower()


def write_release_manifest(path: str, payload: Dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(target)
