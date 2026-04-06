from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Sequence

from app.models.compensacao import Compensacao


@dataclass(frozen=True)
class AuthoritativeWriteStatus:
    status: str
    operation: str
    workbook_path: str
    authority_source: str = "session"
    sqlite_status: str = ""
    sqlite_strategy: str = ""
    synced_at: str = ""
    record_count: int = 0
    excel_mirrored: bool = False
    finalized: bool = False
    rollback_applied: bool = False
    issues: tuple[str, ...] = ()

    @property
    def uses_sqlite(self) -> bool:
        return self.authority_source == "sqlite"

    @property
    def session_path(self) -> str:
        return self.workbook_path


def clone_records(records: Sequence[Compensacao]) -> tuple[Compensacao, ...]:
    return tuple(deepcopy(list(records)))


def identity_signature(records: Sequence[Compensacao]) -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(
            (
                str(getattr(record, "uid", "") or "").strip(),
                int(getattr(record, "excel_row", 0) or 0),
            )
            for record in records
        )
    )


def status_uses_sqlite(status: object) -> bool:
    return bool(getattr(status, "uses_sqlite", False))


def normalized_issues(*issue_groups: Sequence[str]) -> tuple[str, ...]:
    merged: list[str] = []
    for group in issue_groups:
        for issue in group:
            normalized = str(issue or "").strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
    return tuple(merged)


def build_write_status(
    *,
    workbook_path: str,
    operation: str,
    sqlite_status: object,
    record_count: int,
    excel_mirrored: bool,
    finalized: bool,
    rollback_applied: bool,
    extra_issues: Sequence[str] = (),
) -> AuthoritativeWriteStatus:
    authority_source = "sqlite" if status_uses_sqlite(sqlite_status) else "session"
    if rollback_applied:
        status_value = "rolled_back_after_excel_failure"
    elif excel_mirrored and authority_source == "sqlite":
        status_value = "sqlite_primary"
    elif excel_mirrored:
        status_value = "session_fallback"
    else:
        status_value = "excel_failure"

    return AuthoritativeWriteStatus(
        status=status_value,
        operation=operation,
        workbook_path=workbook_path,
        authority_source=authority_source,
        sqlite_status=str(getattr(sqlite_status, "status", "") or ""),
        sqlite_strategy=str(getattr(sqlite_status, "strategy", "") or ""),
        synced_at=str(getattr(sqlite_status, "synced_at", "") or ""),
        record_count=max(int(getattr(sqlite_status, "record_count", 0) or 0), int(record_count or 0)),
        excel_mirrored=bool(excel_mirrored),
        finalized=bool(finalized),
        rollback_applied=bool(rollback_applied),
        issues=normalized_issues(getattr(sqlite_status, "issues", ()) or (), extra_issues),
    )


def build_authoritative_only_status(
    *,
    workbook_path: str,
    operation: str,
    sqlite_status: object,
    record_count: int,
    finalized: bool,
) -> AuthoritativeWriteStatus:
    authority_source = "sqlite" if status_uses_sqlite(sqlite_status) else "session"
    status_value = "sqlite_authoritative" if authority_source == "sqlite" else "session_authoritative"
    return AuthoritativeWriteStatus(
        status=status_value,
        operation=operation,
        workbook_path=workbook_path,
        authority_source=authority_source,
        sqlite_status=str(getattr(sqlite_status, "status", "") or ""),
        sqlite_strategy=str(getattr(sqlite_status, "strategy", "") or ""),
        synced_at=str(getattr(sqlite_status, "synced_at", "") or ""),
        record_count=max(int(getattr(sqlite_status, "record_count", 0) or 0), int(record_count or 0)),
        excel_mirrored=False,
        finalized=bool(finalized),
        rollback_applied=False,
        issues=normalized_issues(getattr(sqlite_status, "issues", ()) or ()),
    )


def build_remote_authoritative_status(
    *,
    workbook_path: str,
    operation: str,
    sqlite_status: object,
    record_count: int,
    extra_issues: Sequence[str] = (),
) -> AuthoritativeWriteStatus:
    return AuthoritativeWriteStatus(
        status="remote_authoritative",
        operation=operation,
        workbook_path=workbook_path,
        authority_source="remote",
        sqlite_status=str(getattr(sqlite_status, "status", "") or ""),
        sqlite_strategy=str(getattr(sqlite_status, "strategy", "") or ""),
        synced_at=str(getattr(sqlite_status, "synced_at", "") or ""),
        record_count=max(int(getattr(sqlite_status, "record_count", 0) or 0), int(record_count or 0)),
        excel_mirrored=False,
        finalized=False,
        rollback_applied=False,
        issues=normalized_issues(getattr(sqlite_status, "issues", ()) or (), extra_issues),
    )


def resolve_finalized_records(
    *,
    current_records: Sequence[Compensacao],
    finalized_records_factory,
) -> tuple[tuple[Compensacao, ...], bool]:
    records = clone_records(current_records)
    finalized = False
    if finalized_records_factory is None:
        return records, finalized
    finalized_records = clone_records(finalized_records_factory())
    if not finalized_records:
        return records, finalized
    if identity_signature(finalized_records) != identity_signature(records):
        return finalized_records, True
    return finalized_records, False
