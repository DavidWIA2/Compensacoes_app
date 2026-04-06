from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol, Sequence

from app.models.compensacao import Compensacao
from app.services.sqlite_mirror_service import WorkbookSnapshotSummary


class LocalMutationSnapshotWriter(Protocol):
    def sync_workbook_snapshot(
        self,
        workbook_path: str,
        records: Sequence[Compensacao],
    ) -> WorkbookSnapshotSummary: ...

    def list_records_for_workbook(self, workbook_path: str) -> list[Compensacao]: ...


@dataclass(frozen=True)
class LocalMutationSyncStatus:
    status: str
    operation: str
    workbook_path: str
    strategy: str = "snapshot_rebuild"
    synced_at: str = ""
    record_count: int = 0
    issues: tuple[str, ...] = ()

    @property
    def uses_sqlite(self) -> bool:
        return self.status == "sqlite"

    @property
    def session_path(self) -> str:
        return self.workbook_path


@dataclass(frozen=True)
class LocalMutationApplyResult:
    status: LocalMutationSyncStatus
    records: tuple[Compensacao, ...]
    source: str = "projection"

    @property
    def uses_sqlite(self) -> bool:
        return self.source == "sqlite"


def normalized_workbook_path(workbook_path: str) -> str:
    return str(workbook_path or "").strip()


def clone_records(records: Sequence[Compensacao]) -> tuple[Compensacao, ...]:
    return tuple(deepcopy(list(records)))


def sort_records(records: Sequence[Compensacao]) -> list[Compensacao]:
    return sorted(
        list(records),
        key=lambda record: (
            int(getattr(record, "excel_row", 0) or 0),
            str(getattr(record, "uid", "") or ""),
        ),
    )


def project_records_after_add(
    existing_records: Sequence[Compensacao],
    added_record: Compensacao,
) -> list[Compensacao]:
    return sort_records([*(deepcopy(list(existing_records))), deepcopy(added_record)])


def project_records_after_edit(
    existing_records: Sequence[Compensacao],
    updated_record: Compensacao,
) -> list[Compensacao]:
    updated: list[Compensacao] = []
    matched = False
    for record in deepcopy(list(existing_records)):
        same_uid = bool(updated_record.uid) and record.uid == updated_record.uid
        same_row = int(record.excel_row or 0) == int(updated_record.excel_row or 0)
        if same_uid or same_row:
            updated.append(deepcopy(updated_record))
            matched = True
        else:
            updated.append(record)
    if not matched:
        updated.append(deepcopy(updated_record))
    return sort_records(updated)


def project_records_after_delete(
    existing_records: Sequence[Compensacao],
    deleted_record: Compensacao,
) -> list[Compensacao]:
    deleted_uid = str(getattr(deleted_record, "uid", "") or "").strip()
    deleted_row = int(getattr(deleted_record, "excel_row", 0) or 0)
    projected: list[Compensacao] = []
    for record in sort_records(deepcopy(list(existing_records))):
        same_uid = bool(deleted_uid) and record.uid == deleted_uid
        same_row = int(record.excel_row or 0) == deleted_row
        if same_uid or same_row:
            continue
        if deleted_row and int(record.excel_row or 0) > deleted_row:
            record.excel_row = max(int(record.excel_row or 0) - 1, 0)
        projected.append(record)
    return projected


def project_records_after_import(
    existing_records: Sequence[Compensacao],
    imported_records: Sequence[Compensacao],
) -> list[Compensacao]:
    return sort_records([*(deepcopy(list(existing_records))), *(deepcopy(list(imported_records)))])


def sync_snapshot_dispatch(
    snapshot_writer: LocalMutationSnapshotWriter | None,
    workbook_path: str,
    projected_records: Sequence[Compensacao],
) -> WorkbookSnapshotSummary:
    writer = snapshot_writer
    if writer is None:
        raise RuntimeError("Snapshot writer indisponivel.")
    if hasattr(writer, "sync_session_snapshot"):
        return writer.sync_session_snapshot(workbook_path, projected_records)
    return writer.sync_workbook_snapshot(workbook_path, projected_records)


def list_session_records_dispatch(
    snapshot_writer: LocalMutationSnapshotWriter | None,
    workbook_path: str,
) -> list[Compensacao]:
    writer = snapshot_writer
    if writer is None:
        return []
    if hasattr(writer, "list_records_for_session"):
        return writer.list_records_for_session(workbook_path)
    return writer.list_records_for_workbook(workbook_path)


def resolve_incremental_method(
    snapshot_writer: LocalMutationSnapshotWriter | None,
    incremental_method_name: str | None,
):
    if snapshot_writer is None or not incremental_method_name:
        return None
    incremental_method = getattr(snapshot_writer, incremental_method_name, None)
    if incremental_method is None:
        session_method_name = (
            incremental_method_name.replace("_to_workbook", "_to_session")
            .replace("_from_workbook", "_from_session")
        )
        incremental_method = getattr(snapshot_writer, session_method_name, None)
    return incremental_method if callable(incremental_method) else None


def extend_status_issues(
    status: LocalMutationSyncStatus,
    *extra_issues: str,
) -> LocalMutationSyncStatus:
    merged_issues = tuple([*status.issues, *(issue for issue in extra_issues if issue)])
    if merged_issues == status.issues:
        return status
    return LocalMutationSyncStatus(
        status=status.status,
        operation=status.operation,
        workbook_path=status.workbook_path,
        strategy=status.strategy,
        synced_at=status.synced_at,
        record_count=status.record_count,
        issues=merged_issues,
    )


def build_sync_status(
    *,
    status: str,
    operation: str,
    workbook_path: str,
    strategy: str = "snapshot_rebuild",
    synced_at: str = "",
    record_count: int = 0,
    issues: Sequence[str] = (),
) -> LocalMutationSyncStatus:
    return LocalMutationSyncStatus(
        status=status,
        operation=operation,
        workbook_path=workbook_path,
        strategy=strategy,
        synced_at=synced_at,
        record_count=record_count,
        issues=tuple(str(issue or "").strip() for issue in issues if str(issue or "").strip()),
    )


def build_apply_result(
    *,
    status: LocalMutationSyncStatus,
    projected_records: Sequence[Compensacao],
    sqlite_records: Sequence[Compensacao] | None = None,
    source: str = "projection",
) -> LocalMutationApplyResult:
    selected_records = sqlite_records if source == "sqlite" and sqlite_records is not None else projected_records
    return LocalMutationApplyResult(
        status=status,
        records=clone_records(selected_records),
        source=source,
    )

