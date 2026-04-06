from __future__ import annotations

from typing import Sequence

from app.application.use_cases.local_record_queries import (
    LocalDuplicateCheckResult,
    LocalRecordQueriesUseCases,
    LocalRecordReadResult,
    LocalSelectedRecordResult,
)
from app.application.use_cases.local_write_authority_support import (
    LocalCreatePreparation,
    LocalDeletePreparation,
    LocalUpdatePreparation,
    LocalWritePreparation,
    build_create_preparation,
    build_delete_preparation,
    build_update_preparation,
    build_write_preparation,
    clone_records,
    combined_source,
    merge_fallback_records,
    merge_issues,
    normalized_workbook_path,
    same_record_identity,
)
from app.models.compensacao import Compensacao


class LocalWriteAuthorityUseCases:
    def __init__(self, snapshot_reader_or_queries):
        if isinstance(snapshot_reader_or_queries, LocalRecordQueriesUseCases):
            self.local_record_queries = snapshot_reader_or_queries
        else:
            self.local_record_queries = LocalRecordQueriesUseCases(snapshot_reader_or_queries)

    @staticmethod
    def _normalized_path(workbook_path: str) -> str:
        return normalized_workbook_path(workbook_path)

    @staticmethod
    def _clone_records(records: Sequence[Compensacao]) -> tuple[Compensacao, ...]:
        return clone_records(records)

    @staticmethod
    def _same_record(left: Compensacao, right: Compensacao) -> bool:
        return same_record_identity(left, right)

    @staticmethod
    def _merge_issues(*issue_groups: Sequence[str]) -> tuple[str, ...]:
        return merge_issues(*issue_groups)

    @staticmethod
    def _combined_source(*results: object) -> str:
        return combined_source(*results)

    def _build_preparation(
        self,
        *,
        workbook_path: str,
        base_result: LocalRecordReadResult,
        selected_result: LocalSelectedRecordResult | None = None,
        duplicate_result: LocalDuplicateCheckResult | None = None,
    ) -> LocalWritePreparation:
        return build_write_preparation(
            workbook_path=workbook_path,
            base_result=base_result,
            selected_result=selected_result,
            duplicate_result=duplicate_result,
        )

    def prepare_base(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
    ) -> LocalWritePreparation:
        base_result = self.local_record_queries.resolve_authoritative_record_source(
            self._normalized_path(workbook_path),
            fallback_records=fallback_records,
        )
        return self._build_preparation(
            workbook_path=workbook_path,
            base_result=base_result,
        )

    def prepare_create(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
        draft_record: Compensacao,
    ) -> LocalCreatePreparation:
        base_preparation = self.prepare_base(
            workbook_path,
            fallback_records=fallback_records,
        )
        duplicate_result = self.local_record_queries.resolve_duplicate_av_tec(
            self._normalized_path(workbook_path),
            fallback_records=base_preparation.base_records,
            av_tec=draft_record.av_tec,
            current_uid="",
        )
        return build_create_preparation(
            base_preparation=base_preparation,
            duplicate_result=duplicate_result,
        )

    def prepare_update(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
        fallback_selected: Compensacao | None,
        draft_record: Compensacao,
    ) -> LocalUpdatePreparation:
        combined_fallback = merge_fallback_records(fallback_records, fallback_selected)

        base_preparation = self.prepare_base(
            workbook_path,
            fallback_records=combined_fallback,
        )
        selected_result = self.local_record_queries.resolve_selected_record(
            self._normalized_path(workbook_path),
            fallback_records=base_preparation.base_records,
            uid=str(getattr(fallback_selected, "uid", "") or ""),
            excel_row=int(getattr(fallback_selected, "excel_row", 0) or 0),
        )
        selected_record = selected_result.record
        duplicate_result = self.local_record_queries.resolve_duplicate_av_tec(
            self._normalized_path(workbook_path),
            fallback_records=base_preparation.base_records,
            av_tec=draft_record.av_tec,
            current_uid=str(getattr(selected_record, "uid", "") or ""),
        )
        return build_update_preparation(
            base_preparation=base_preparation,
            selected_result=selected_result,
            duplicate_result=duplicate_result,
            draft_record=draft_record,
        )

    def prepare_delete(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
        fallback_selected: Compensacao | None,
    ) -> LocalDeletePreparation:
        combined_fallback = merge_fallback_records(fallback_records, fallback_selected)

        base_preparation = self.prepare_base(
            workbook_path,
            fallback_records=combined_fallback,
        )
        selected_result = self.local_record_queries.resolve_selected_record(
            self._normalized_path(workbook_path),
            fallback_records=base_preparation.base_records,
            uid=str(getattr(fallback_selected, "uid", "") or ""),
            excel_row=int(getattr(fallback_selected, "excel_row", 0) or 0),
        )
        return build_delete_preparation(
            base_preparation=base_preparation,
            selected_result=selected_result,
        )
