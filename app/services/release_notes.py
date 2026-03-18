from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence

from app import __version__ as APP_VERSION
from app.config import APP_NAME

GIT_LOG_FIELD_SEPARATOR = "\x1f"
DEFAULT_RELEASE_NOTE = "Melhorias internas e correcoes de estabilidade."


def default_release_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_release_entry(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    if text.startswith("- ") or text.startswith("* "):
        text = text[2:].strip()
    return text


def normalize_release_entries(entries: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        text = normalize_release_entry(entry)
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)

    if not normalized:
        normalized.append(DEFAULT_RELEASE_NOTE)
    return normalized


def parse_git_log_subjects(payload: str) -> list[str]:
    subjects: list[str] = []
    for raw_line in str(payload or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if GIT_LOG_FIELD_SEPARATOR in line:
            _, line = line.split(GIT_LOG_FIELD_SEPARATOR, 1)
        subjects.append(line)
    return normalize_release_entries(subjects)


def build_plain_release_notes(entries: Sequence[str]) -> str:
    normalized = normalize_release_entries(entries)
    return "\n".join(f"- {entry}" for entry in normalized)


def build_markdown_release_notes(
    *,
    version: str = APP_VERSION,
    entries: Sequence[str],
    published_at: str | None = None,
    app_name: str = APP_NAME,
) -> str:
    clean_version = str(version or "").strip()
    if not clean_version:
        raise ValueError("version is required")

    normalized = normalize_release_entries(entries)
    lines = [f"# {app_name} {clean_version}"]
    if published_at:
        lines.extend(["", f"Publicado em: {published_at}"])
    lines.extend(["", "## Novidades", ""])
    lines.extend(f"- {entry}" for entry in normalized)
    return "\n".join(lines).strip() + "\n"
