from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.application.use_cases.import_preview_presenter import ImportPreviewRowView


@dataclass(frozen=True)
class ImportPreviewButtonPlan:
    allows_import: bool
    accept_label: str


def build_import_preview_button_plan(*, total_invalid: int) -> ImportPreviewButtonPlan:
    if int(total_invalid or 0) > 0:
        return ImportPreviewButtonPlan(allows_import=False, accept_label="")
    return ImportPreviewButtonPlan(allows_import=True, accept_label="Importar")


def build_import_preview_row_values(row_data: ImportPreviewRowView) -> tuple[str, str, str, str, str]:
    return (
        row_data.line_number,
        row_data.uid,
        row_data.av_tec,
        row_data.status,
        row_data.detail,
    )


def resolve_import_preview_current_key(
    visible_rows: Sequence[ImportPreviewRowView],
    *,
    current_row: int,
) -> tuple[str, str, str, str, str] | None:
    if 0 <= current_row < len(visible_rows):
        return visible_rows[current_row].key()
    return None


def resolve_import_preview_target_index(
    visible_rows: Sequence[ImportPreviewRowView],
    *,
    current_key: tuple[str, str, str, str, str] | None,
) -> int:
    if not visible_rows:
        return 0
    if current_key is None:
        return 0
    for index, row_data in enumerate(visible_rows):
        if row_data.key() == current_key:
            return index
    return 0
