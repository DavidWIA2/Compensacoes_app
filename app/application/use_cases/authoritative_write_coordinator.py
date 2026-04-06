from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Sequence, TypeVar

from app.application.use_cases.authoritative_write_support import (
    AuthoritativeWriteStatus,
    build_authoritative_only_status,
    build_write_status,
    clone_records,
    identity_signature,
    normalized_issues,
    resolve_finalized_records,
    status_uses_sqlite,
)
from app.application.use_cases.local_mutation_sync import (
    LocalMutationApplyResult,
    LocalMutationSyncStatus,
    LocalMutationSyncUseCases,
)
from app.models.compensacao import Compensacao
from app.utils.logger import get_logger


logger = get_logger("UseCases.AuthoritativeWrite")

TExcelResult = TypeVar("TExcelResult")


@dataclass(frozen=True)
class CoordinatedWriteResult(Generic[TExcelResult]):
    status: LocalMutationSyncStatus
    write_status: AuthoritativeWriteStatus
    records: tuple[Compensacao, ...]
    excel_result: TExcelResult | None = None
    rollback_issues: tuple[str, ...] = ()
    finalized: bool = False


class AuthoritativeWriteError(RuntimeError):
    def __init__(self, message: str, *, write_status: AuthoritativeWriteStatus):
        super().__init__(message)
        self.write_status = write_status


class AuthoritativeWriteCoordinator:
    def __init__(self, local_mutation_sync: LocalMutationSyncUseCases):
        self.local_mutation_sync = local_mutation_sync

    @staticmethod
    def _clone_records(records: Sequence[Compensacao]) -> tuple[Compensacao, ...]:
        return clone_records(records)

    @staticmethod
    def _identity_signature(records: Sequence[Compensacao]) -> tuple[tuple[str, int], ...]:
        return identity_signature(records)

    @staticmethod
    def _status_uses_sqlite(status: object) -> bool:
        return status_uses_sqlite(status)

    @staticmethod
    def _normalized_issues(*issue_groups: Sequence[str]) -> tuple[str, ...]:
        return normalized_issues(*issue_groups)

    def _build_write_status(
        self,
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
        return build_write_status(
            workbook_path=workbook_path,
            operation=operation,
            sqlite_status=sqlite_status,
            record_count=record_count,
            excel_mirrored=excel_mirrored,
            finalized=finalized,
            rollback_applied=rollback_applied,
            extra_issues=extra_issues,
        )

    def _rollback_sqlite(
        self,
        *,
        workbook_path: str,
        operation: str,
        base_records: Sequence[Compensacao],
    ) -> tuple[str, ...]:
        rollback_status = self.local_mutation_sync.sync_projected_records(
            workbook_path=workbook_path,
            records=base_records,
            operation=f"{operation}_rollback",
        )
        if rollback_status.issues:
            logger.warning(
                "Rollback do espelho SQLite apos falha na etapa em Excel (%s): %s",
                operation,
                " | ".join(rollback_status.issues),
            )
        return tuple(rollback_status.issues)

    def execute_sqlite_first(
        self,
        *,
        workbook_path: str,
        operation: str,
        base_records: Sequence[Compensacao],
        sqlite_apply: Callable[[], LocalMutationApplyResult],
        excel_write: Callable[[], TExcelResult],
        finalized_records_factory: Callable[[], Sequence[Compensacao]] | None = None,
    ) -> CoordinatedWriteResult[TExcelResult]:
        mutation_result = sqlite_apply()
        rollback_issues: tuple[str, ...] = ()
        try:
            excel_result = excel_write()
        except Exception as exc:
            if self._status_uses_sqlite(mutation_result.status):
                rollback_issues = self._rollback_sqlite(
                    workbook_path=workbook_path,
                    operation=operation,
                    base_records=base_records,
                )
            write_status = self._build_write_status(
                workbook_path=workbook_path,
                operation=operation,
                sqlite_status=mutation_result.status,
                record_count=len(mutation_result.records),
                excel_mirrored=False,
                finalized=False,
                rollback_applied=self._status_uses_sqlite(mutation_result.status),
                extra_issues=(
                    *rollback_issues,
                    f"Falha ao espelhar a operacao no Excel: {exc}",
                ),
            )
            raise AuthoritativeWriteError(str(exc), write_status=write_status) from exc

        status = mutation_result.status
        records = self._clone_records(mutation_result.records)
        records, finalized = resolve_finalized_records(
            current_records=records,
            finalized_records_factory=finalized_records_factory,
        )
        if finalized and self._status_uses_sqlite(status):
            status = self.local_mutation_sync.sync_projected_records(
                workbook_path=workbook_path,
                records=records,
                operation=f"{operation}_finalize",
            )

        write_status = self._build_write_status(
            workbook_path=workbook_path,
            operation=operation,
            sqlite_status=status,
            record_count=len(records),
            excel_mirrored=True,
            finalized=finalized,
            rollback_applied=False,
            extra_issues=rollback_issues,
        )
        return CoordinatedWriteResult(
            status=status,
            write_status=write_status,
            records=records,
            excel_result=excel_result,
            rollback_issues=rollback_issues,
            finalized=finalized,
        )

    def execute_sqlite_authoritative(
        self,
        *,
        workbook_path: str,
        operation: str,
        sqlite_apply: Callable[[], LocalMutationApplyResult],
        finalized_records_factory: Callable[[], Sequence[Compensacao]] | None = None,
    ) -> CoordinatedWriteResult[None]:
        mutation_result = sqlite_apply()
        status = mutation_result.status
        records = self._clone_records(mutation_result.records)
        records, finalized = resolve_finalized_records(
            current_records=records,
            finalized_records_factory=finalized_records_factory,
        )
        if finalized and self._status_uses_sqlite(status):
            status = self.local_mutation_sync.sync_projected_records(
                workbook_path=workbook_path,
                records=records,
                operation=f"{operation}_finalize",
            )

        write_status = build_authoritative_only_status(
            workbook_path=workbook_path,
            operation=operation,
            sqlite_status=status,
            record_count=len(records),
            finalized=finalized,
        )
        return CoordinatedWriteResult(
            status=status,
            write_status=write_status,
            records=records,
            excel_result=None,
            rollback_issues=(),
            finalized=finalized,
        )
