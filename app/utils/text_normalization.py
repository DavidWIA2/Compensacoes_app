from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "â€™", "â€œ", "â€“", "�")


def looks_like_mojibake(value: str) -> bool:
    text = str(value or "")
    return bool(text) and any(marker in text for marker in _MOJIBAKE_MARKERS)


def repair_mojibake_text(value: object) -> str:
    text = str(value or "")
    if not looks_like_mojibake(text):
        return text

    best = text
    best_score = _mojibake_score(best)
    for _ in range(2):
        candidate = _repair_once(best)
        candidate_score = _mojibake_score(candidate)
        if candidate == best or candidate_score >= best_score:
            break
        best = candidate
        best_score = candidate_score
        if best_score == 0:
            break
    return best


def repair_mojibake_object(value: Any) -> Any:
    if isinstance(value, str):
        return repair_mojibake_text(value)
    if isinstance(value, Mapping):
        return {key: repair_mojibake_object(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(repair_mojibake_object(item) for item in value)
    if isinstance(value, list):
        return [repair_mojibake_object(item) for item in value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return type(value)(repair_mojibake_object(item) for item in value)
    return value


def _mojibake_score(text: str) -> int:
    return sum(text.count(marker) for marker in _MOJIBAKE_MARKERS)


def _repair_once(text: str) -> str:
    for source_encoding in ("latin-1", "cp1252"):
        try:
            return text.encode(source_encoding).decode("utf-8")
        except UnicodeError:
            continue
    return text
