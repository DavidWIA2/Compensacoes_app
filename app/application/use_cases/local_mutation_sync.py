from __future__ import annotations

from copy import deepcopy
from typing import Sequence

from app.application.use_cases.local_mutation_sync_support import (
    LocalMutationApplyResult,
    LocalMutationSnapshotWriter,
    LocalMutationSyncStatus,
    build_apply_result,
    build_sync_status,
    clone_records,
    extend_status_issues,
    list_session_records_dispatch,
    normalized_workbook_path,
    project_records_after_add,
    project_records_after_delete,
    project_records_after_edit,
    project_records_after_import,
    resolve_incremental_method,
    sort_records,
    sync_snapshot_dispatch,
)
from app.models.compensacao import Compensacao


class LocalMutationSyncUseCases:
    def __init__(self, snapshot_writer: LocalMutationSnapshotWriter | None):
        self.snapshot_writer = snapshot_writer

    @staticmethod
    def _normalized_path(workbook_path: str) -> str:
        return normalized_workbook_path(workbook_path)

    @staticmethod
    def _sort_records(records: Sequence[Compensacao]) -> list[Compensacao]:
        return sort_records(records)

    def project_after_add(
        self,
        existing_records: Sequence[Compensacao],
        added_record: Compensacao,
    ) -> list[Compensacao]:
        return project_records_after_add(existing_records, added_record)

    def project_after_edit(
        self,
        existing_records: Sequence[Compensacao],
        updated_record: Compensacao,
    ) -> list[Compensacao]:
        return project_records_after_edit(existing_records, updated_record)

    def project_after_delete(
        self,
        existing_records: Sequence[Compensacao],
        deleted_record: Compensacao,
    ) -> list[Compensacao]:
        return project_records_after_delete(existing_records, deleted_record)

    def project_after_import(
        self,
        existing_records: Sequence[Compensacao],
        imported_records: Sequence[Compensacao],
    ) -> list[Compensacao]:
        return project_records_after_import(existing_records, imported_records)

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
        return clone_records(records)

    def _sync_snapshot(
        self,
        workbook_path: str,
        projected_records: Sequence[Compensacao],
    ):
        return sync_snapshot_dispatch(self.snapshot_writer, workbook_path, projected_records)

    def _list_session_records(self, workbook_path: str) -> list[Compensacao]:
        return list_session_records_dispatch(self.snapshot_writer, workbook_path)

    @staticmethod
    def _extend_status_issues(
        status: LocalMutationSyncStatus,
        *extra_issues: str,
    ) -> LocalMutationSyncStatus:
        return extend_status_issues(status, *extra_issues)

    def _build_apply_result(
        self,
        *,
        status: LocalMutationSyncStatus,
        projected_records: Sequence[Compensacao],
    ) -> LocalMutationApplyResult:
        normalized_path = self._normalized_path(status.workbook_path)
        writer = self.snapshot_writer
        if not status.uses_sqlite or writer is None or not normalized_path:
            return build_apply_result(status=status, projected_records=projected_records, source="projection")

        try:
            sqlite_records = tuple(self._list_session_records(normalized_path))
        except Exception as exc:
            return build_apply_result(
                status=self._extend_status_issues(
                    status,
                    f"Leitura pos-mutacao do espelho local falhou: {exc}",
                ),
                projected_records=projected_records,
                source="projection",
            )

        expected_count = int(status.record_count or 0)
        if expected_count and len(sqlite_records) != expected_count:
            return build_apply_result(
                status=self._extend_status_issues(
                    status,
                    (
                        f"Espelho local informou {expected_count} registro(s) apos a mutacao, "
                        f"mas retornou {len(sqlite_records)} na leitura."
                    ),
                ),
                projected_records=projected_records,
                source="projection",
            )

        return build_apply_result(
            status=status,
            projected_records=projected_records,
            sqlite_records=sqlite_records,
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
            return build_sync_status(
                status="indisponivel",
                operation=operation,
                workbook_path="",
                issues=("Nenhuma planilha ativa para sincronizar no SQLite.",),
            )
        if self.snapshot_writer is None:
            return build_sync_status(
                status="indisponivel",
                operation=operation,
                workbook_path=normalized_path,
                record_count=len(projected_records),
                issues=("Espelho local em SQLite indisponivel nesta sessao.",),
            )

        incremental_issue = ""
        try:
            incremental_method = resolve_incremental_method(self.snapshot_writer, incremental_method_name)
            if callable(incremental_method):
                summary = incremental_method(normalized_path, *incremental_args)
                return build_sync_status(
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
            summary = self._sync_snapshot(normalized_path, projected_records)
        except Exception as exc:
            issues = [f"Falha ao sincronizar mutacao no SQLite: {exc}"]
            if incremental_issue:
                issues.insert(0, incremental_issue)
            return build_sync_status(
                status="falha",
                operation=operation,
                workbook_path=normalized_path,
                record_count=len(projected_records),
                issues=tuple(issues),
            )

        return build_sync_status(
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
