from __future__ import annotations

from typing import Optional, Protocol, Sequence

from app.application.use_cases.record_mutations_support import (
    RecordValidationResult,
    build_validation_result,
    find_duplicate_av_tec_row,
)
from app.models.compensacao import Compensacao


class RecordStore(Protocol):
    def add_new(self, record: Compensacao) -> int: ...

    def save_edit(self, record: Compensacao) -> None: ...

    def delete_record_shift_up(self, row_idx: int, uid: str = "") -> None: ...

    def find_row_by_uid(self, uid: str) -> Optional[int]: ...

class RecordMutationUseCases:
    def __init__(self, record_store: RecordStore):
        self.record_store = record_store

    def validate_for_create(
        self,
        record: Compensacao,
        existing_records: Sequence[Compensacao],
    ) -> RecordValidationResult:
        return self._validate(record, existing_records, current_uid="")

    def validate_for_update(
        self,
        record: Compensacao,
        existing_records: Sequence[Compensacao],
    ) -> RecordValidationResult:
        return self._validate(record, existing_records, current_uid=record.uid)

    def find_duplicate_av_tec(
        self,
        existing_records: Sequence[Compensacao],
        av_tec: str,
        current_uid: str,
    ) -> Optional[int]:
        return find_duplicate_av_tec_row(
            self.record_store,
            existing_records,
            av_tec,
            current_uid,
        )

    def add_new(self, record: Compensacao) -> int:
        return self.record_store.add_new(record)

    def save_edit(self, record: Compensacao) -> None:
        self.record_store.save_edit(record)

    def delete(self, record: Compensacao) -> None:
        self.record_store.delete_record_shift_up(record.excel_row, record.uid)

    def _validate(
        self,
        record: Compensacao,
        existing_records: Sequence[Compensacao],
        *,
        current_uid: str,
    ) -> RecordValidationResult:
        return build_validation_result(
            record,
            record_store=self.record_store,
            existing_records=existing_records,
            current_uid=current_uid,
        )
