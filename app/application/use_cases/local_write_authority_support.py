from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Sequence

from app.models.compensacao import Compensacao


@dataclass(frozen=True)
class LocalWritePreparation:
    source: str
    workbook_path: str
    base_records: tuple[Compensacao, ...]
    synced_at: str = ""
    mirrored_records: int = 0
    session_records: int = 0
    issues: tuple[str, ...] = ()

    @property
    def uses_sqlite(self) -> bool:
        return self.source == "sqlite"


@dataclass(frozen=True)
class LocalCreatePreparation(LocalWritePreparation):
    duplicate_row: int | None = None


@dataclass(frozen=True)
class LocalUpdatePreparation(LocalWritePreparation):
    selected_record: Compensacao | None = None
    effective_record: Compensacao | None = None
    duplicate_row: int | None = None


@dataclass(frozen=True)
class LocalDeletePreparation(LocalWritePreparation):
    selected_record: Compensacao | None = None


def normalized_workbook_path(workbook_path: str) -> str:
    return str(workbook_path or "").strip()


def clone_records(records: Sequence[Compensacao]) -> tuple[Compensacao, ...]:
    return tuple(deepcopy(list(records)))


def same_record_identity(left: Compensacao, right: Compensacao) -> bool:
    left_uid = str(getattr(left, "uid", "") or "").strip()
    right_uid = str(getattr(right, "uid", "") or "").strip()
    if left_uid and right_uid and left_uid == right_uid:
        return True
    left_row = int(getattr(left, "excel_row", 0) or 0)
    right_row = int(getattr(right, "excel_row", 0) or 0)
    return left_row > 0 and right_row > 0 and left_row == right_row


def merge_issues(*issue_groups: Sequence[str]) -> tuple[str, ...]:
    merged: list[str] = []
    for group in issue_groups:
        for issue in group:
            normalized_issue = str(issue or "").strip()
            if normalized_issue and normalized_issue not in merged:
                merged.append(normalized_issue)
    return tuple(merged)


def combined_source(*results: object) -> str:
    relevant = [result for result in results if result is not None]
    if relevant and all(bool(getattr(result, "uses_sqlite", False)) for result in relevant):
        return "sqlite"
    return "session"


def build_write_preparation(
    *,
    workbook_path: str,
    base_result,
    selected_result=None,
    duplicate_result=None,
) -> LocalWritePreparation:
    synced_at = (
        str(getattr(base_result, "synced_at", "") or "")
        or str(getattr(selected_result, "synced_at", "") or "")
        or str(getattr(duplicate_result, "synced_at", "") or "")
    )
    mirrored_records = max(
        int(getattr(base_result, "mirrored_records", 0) or 0),
        int(getattr(selected_result, "mirrored_records", 0) or 0),
        int(getattr(duplicate_result, "mirrored_records", 0) or 0),
    )
    session_records = max(
        int(getattr(base_result, "session_records", 0) or 0),
        int(getattr(selected_result, "session_records", 0) or 0),
        int(getattr(duplicate_result, "session_records", 0) or 0),
    )
    return LocalWritePreparation(
        source=combined_source(base_result, selected_result, duplicate_result),
        workbook_path=normalized_workbook_path(workbook_path or getattr(base_result, "workbook_path", "")),
        base_records=clone_records(base_result.records),
        synced_at=synced_at,
        mirrored_records=mirrored_records,
        session_records=session_records,
        issues=merge_issues(
            getattr(base_result, "issues", ()),
            getattr(selected_result, "issues", ()),
            getattr(duplicate_result, "issues", ()),
        ),
    )


def build_create_preparation(
    *,
    base_preparation: LocalWritePreparation,
    duplicate_result,
) -> LocalCreatePreparation:
    return LocalCreatePreparation(
        source=combined_source(base_preparation, duplicate_result),
        workbook_path=base_preparation.workbook_path,
        base_records=base_preparation.base_records,
        synced_at=base_preparation.synced_at or str(getattr(duplicate_result, "synced_at", "") or ""),
        mirrored_records=max(
            base_preparation.mirrored_records,
            int(getattr(duplicate_result, "mirrored_records", 0) or 0),
        ),
        session_records=max(
            base_preparation.session_records,
            int(getattr(duplicate_result, "session_records", 0) or 0),
        ),
        issues=merge_issues(base_preparation.issues, getattr(duplicate_result, "issues", ())),
        duplicate_row=duplicate_result.duplicate_row,
    )


def build_update_preparation(
    *,
    base_preparation: LocalWritePreparation,
    selected_result,
    duplicate_result,
    draft_record: Compensacao,
) -> LocalUpdatePreparation:
    selected_record = selected_result.record
    effective_record = None
    if selected_record is not None:
        effective_record = deepcopy(draft_record)
        effective_record.uid = selected_record.uid
        effective_record.excel_row = selected_record.excel_row

    return LocalUpdatePreparation(
        source=combined_source(base_preparation, selected_result, duplicate_result),
        workbook_path=base_preparation.workbook_path,
        base_records=base_preparation.base_records,
        synced_at=base_preparation.synced_at or str(getattr(selected_result, "synced_at", "") or ""),
        mirrored_records=max(
            base_preparation.mirrored_records,
            int(getattr(selected_result, "mirrored_records", 0) or 0),
            int(getattr(duplicate_result, "mirrored_records", 0) or 0),
        ),
        session_records=max(
            base_preparation.session_records,
            int(getattr(selected_result, "session_records", 0) or 0),
            int(getattr(duplicate_result, "session_records", 0) or 0),
        ),
        issues=merge_issues(
            base_preparation.issues,
            getattr(selected_result, "issues", ()),
            getattr(duplicate_result, "issues", ()),
        ),
        selected_record=deepcopy(selected_record) if selected_record is not None else None,
        effective_record=effective_record,
        duplicate_row=duplicate_result.duplicate_row,
    )


def build_delete_preparation(
    *,
    base_preparation: LocalWritePreparation,
    selected_result,
) -> LocalDeletePreparation:
    return LocalDeletePreparation(
        source=combined_source(base_preparation, selected_result),
        workbook_path=base_preparation.workbook_path,
        base_records=base_preparation.base_records,
        synced_at=base_preparation.synced_at or str(getattr(selected_result, "synced_at", "") or ""),
        mirrored_records=max(
            base_preparation.mirrored_records,
            int(getattr(selected_result, "mirrored_records", 0) or 0),
        ),
        session_records=max(
            base_preparation.session_records,
            int(getattr(selected_result, "session_records", 0) or 0),
        ),
        issues=merge_issues(base_preparation.issues, getattr(selected_result, "issues", ())),
        selected_record=deepcopy(selected_result.record) if selected_result.record is not None else None,
    )


def merge_fallback_records(
    fallback_records: Sequence[Compensacao],
    fallback_selected: Compensacao | None,
) -> list[Compensacao]:
    combined = list(fallback_records)
    if fallback_selected is not None and not any(
        same_record_identity(existing_record, fallback_selected) for existing_record in combined
    ):
        combined.append(fallback_selected)
    return combined
