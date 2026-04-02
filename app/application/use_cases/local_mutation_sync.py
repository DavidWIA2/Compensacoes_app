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


@dataclass(frozen=True)
class LocalMutationApplyResult:
    status: LocalMutationSyncStatus
    records: tuple[Compensacao, ...]
    source: str = "projection"

    @property
    def uses_sqlite(self) -> bool:
        return self.source == "sqlite"


class LocalMutationSyncUseCases:
    def __init__(self, snapshot_writer: LocalMutationSnapshotWriter | None):
        self.snapshot_writer = snapshot_writer

    @staticmethod
    def _normalized_path(workbook_path: str) -> str:
        return str(workbook_path or "").strip()

    @staticmethod
    def _sort_records(records: Sequence[Compensacao]) -> list[Compensacao]:
        return sorted(
            list(records),
            key=lambda record: (
                int(getattr(record, "excel_row", 0) or 0),
                str(getattr(record, "uid", "") or ""),
            ),
        )

    def project_after_add(
        self,
        existing_records: Sequence[Compensacao],
        added_record: Compensacao,
    ) -> list[Compensacao]:
        return self._sort_records([*(deepcopy(list(existing_records))), deepcopy(added_record)])

    def project_after_edit(
        self,
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
        return self._sort_records(updated)

    def project_after_delete(
        self,
        existing_records: Sequence[Compensacao],
        deleted_record: Compensacao,
    ) -> list[Compensacao]:
        deleted_uid = str(getattr(deleted_record, "uid", "") or "").strip()
        deleted_row = int(getattr(deleted_record, "excel_row", 0) or 0)
        projected: list[Compensacao] = []
        for record in self._sort_records(deepcopy(list(existing_records))):
            same_uid = bool(deleted_uid) and record.uid == deleted_uid
            same_row = int(record.excel_row or 0) == deleted_row
            if same_uid or same_row:
                continue
            if deleted_row and int(record.excel_row or 0) > deleted_row:
                record.excel_row = max(int(record.excel_row or 0) - 1, 0)
            projected.append(record)
        return projected

    def project_after_import(
        self,
        existing_records: Sequence[Compensacao],
        imported_records: Sequence[Compensacao],
    ) -> list[Compensacao]:
        return self._sort_records([*(deepcopy(list(existing_records))), *(deepcopy(list(imported_records)))])

    def sync_projected_records(
        self,
        *,
        workbook_path: str,
        records: Sequence[Compensacao],
        operation: str,
    ) -> LocalMutationSyncStatus:
        return self._sync_with_fallback(
            workbook_path=workbook_path,
            operation=operation,
            projected_records=records,
        )

    @staticmethod
    def _clone_records(records: Sequence[Compensacao]) -> tuple[Compensacao, ...]:
        return tuple(deepcopy(list(records)))

    @staticmethod
    def _extend_status_issues(
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

    def _build_apply_result(
        self,
        *,
        status: LocalMutationSyncStatus,
        projected_records: Sequence[Compensacao],
    ) -> LocalMutationApplyResult:
        normalized_path = self._normalized_path(status.workbook_path)
        writer = self.snapshot_writer
        if not status.uses_sqlite or writer is None or not normalized_path:
            return LocalMutationApplyResult(
                status=status,
                records=self._clone_records(projected_records),
                source="projection",
            )

        try:
            sqlite_records = tuple(writer.list_records_for_workbook(normalized_path))
        except Exception as exc:
            return LocalMutationApplyResult(
                status=self._extend_status_issues(
                    status,
                    f"Leitura pos-mutacao do espelho local falhou: {exc}",
                ),
                records=self._clone_records(projected_records),
                source="projection",
            )

        expected_count = int(status.record_count or 0)
        if expected_count and len(sqlite_records) != expected_count:
            return LocalMutationApplyResult(
                status=self._extend_status_issues(
                    status,
                    (
                        f"Espelho local informou {expected_count} registro(s) apos a mutacao, "
                        f"mas retornou {len(sqlite_records)} na leitura."
                    ),
                ),
                records=self._clone_records(projected_records),
                source="projection",
            )

        return LocalMutationApplyResult(
            status=status,
            records=self._clone_records(sqlite_records),
            source="sqlite",
        )

    def _sync_with_fallback(
        self,
        *,
        workbook_path: str,
        operation: str,
        projected_records: Sequence[Compensacao],
        incremental_method_name: str | None = None,
        incremental_args: Sequence[object] = (),
    ) -> LocalMutationSyncStatus:
        normalized_path = self._normalized_path(workbook_path)
        if not normalized_path:
            return LocalMutationSyncStatus(
                status="indisponivel",
                operation=operation,
                workbook_path="",
                issues=("Nenhuma planilha ativa para sincronizar no SQLite.",),
            )
        if self.snapshot_writer is None:
            return LocalMutationSyncStatus(
                status="indisponivel",
                operation=operation,
                workbook_path=normalized_path,
                record_count=len(projected_records),
                issues=("Espelho local em SQLite indisponivel nesta sessao.",),
            )

        incremental_issue = ""
        try:
            incremental_method = (
                getattr(self.snapshot_writer, incremental_method_name, None)
                if incremental_method_name
                else None
            )
            if callable(incremental_method):
                summary = incremental_method(normalized_path, *incremental_args)
                return LocalMutationSyncStatus(
                    status="sqlite",
                    operation=operation,
                    workbook_path=summary.workbook_path,
                    strategy="incremental",
                    synced_at=summary.synced_at,
                    record_count=summary.record_count,
                )
        except Exception as exc:
            incremental_issue = f"Sincronizacao incremental falhou: {exc}"

        try:
            summary = self.snapshot_writer.sync_workbook_snapshot(normalized_path, projected_records)
        except Exception as exc:
            issues = [f"Falha ao sincronizar mutacao no SQLite: {exc}"]
            if incremental_issue:
                issues.insert(0, incremental_issue)
            return LocalMutationSyncStatus(
                status="falha",
                operation=operation,
                workbook_path=normalized_path,
                record_count=len(projected_records),
                issues=tuple(issues),
            )

        return LocalMutationSyncStatus(
            status="sqlite",
            operation=operation,
            workbook_path=summary.workbook_path,
            strategy="snapshot_rebuild",
            synced_at=summary.synced_at,
            record_count=summary.record_count,
            issues=((incremental_issue,) if incremental_issue else ()),
        )

    def sync_after_add(
        self,
        *,
        workbook_path: str,
        existing_records: Sequence[Compensacao],
        added_record: Compensacao,
    ) -> LocalMutationSyncStatus:
        projected_records = self.project_after_add(existing_records, added_record)
        return self._sync_with_fallback(
            workbook_path=workbook_path,
            operation="add",
            projected_records=projected_records,
            incremental_method_name="append_record_to_workbook",
            incremental_args=(deepcopy(added_record),),
        )

    def apply_after_add(
        self,
        *,
        workbook_path: str,
        existing_records: Sequence[Compensacao],
        added_record: Compensacao,
    ) -> LocalMutationApplyResult:
        projected_records = self.project_after_add(existing_records, added_record)
        status = self.sync_after_add(
            workbook_path=workbook_path,
            existing_records=existing_records,
            added_record=added_record,
        )
        return self._build_apply_result(status=status, projected_records=projected_records)

    def sync_after_edit(
        self,
        *,
        workbook_path: str,
        existing_records: Sequence[Compensacao],
        updated_record: Compensacao,
    ) -> LocalMutationSyncStatus:
        projected_records = self.project_after_edit(existing_records, updated_record)
        return self._sync_with_fallback(
            workbook_path=workbook_path,
            operation="edit",
            projected_records=projected_records,
            incremental_method_name="update_record_in_workbook",
            incremental_args=(deepcopy(updated_record),),
        )

    def apply_after_edit(
        self,
        *,
        workbook_path: str,
        existing_records: Sequence[Compensacao],
        updated_record: Compensacao,
    ) -> LocalMutationApplyResult:
        projected_records = self.project_after_edit(existing_records, updated_record)
        status = self.sync_after_edit(
            workbook_path=workbook_path,
            existing_records=existing_records,
            updated_record=updated_record,
        )
        return self._build_apply_result(status=status, projected_records=projected_records)

    def sync_after_delete(
        self,
        *,
        workbook_path: str,
        existing_records: Sequence[Compensacao],
        deleted_record: Compensacao,
    ) -> LocalMutationSyncStatus:
        projected_records = self.project_after_delete(existing_records, deleted_record)
        return self._sync_with_fallback(
            workbook_path=workbook_path,
            operation="delete",
            projected_records=projected_records,
            incremental_method_name="delete_record_from_workbook",
            incremental_args=(deepcopy(deleted_record),),
        )

    def apply_after_delete(
        self,
        *,
        workbook_path: str,
        existing_records: Sequence[Compensacao],
        deleted_record: Compensacao,
    ) -> LocalMutationApplyResult:
        projected_records = self.project_after_delete(existing_records, deleted_record)
        status = self.sync_after_delete(
            workbook_path=workbook_path,
            existing_records=existing_records,
            deleted_record=deleted_record,
        )
        return self._build_apply_result(status=status, projected_records=projected_records)

    def sync_after_import(
        self,
        *,
        workbook_path: str,
        existing_records: Sequence[Compensacao],
        imported_records: Sequence[Compensacao],
    ) -> LocalMutationSyncStatus:
        projected_records = self.project_after_import(existing_records, imported_records)
        return self._sync_with_fallback(
            workbook_path=workbook_path,
            operation="import",
            projected_records=projected_records,
            incremental_method_name="append_records_to_workbook",
            incremental_args=(deepcopy(list(imported_records)),),
        )

    def apply_after_import(
        self,
        *,
        workbook_path: str,
        existing_records: Sequence[Compensacao],
        imported_records: Sequence[Compensacao],
    ) -> LocalMutationApplyResult:
        projected_records = self.project_after_import(existing_records, imported_records)
        status = self.sync_after_import(
            workbook_path=workbook_path,
            existing_records=existing_records,
            imported_records=imported_records,
        )
        return self._build_apply_result(status=status, projected_records=projected_records)
