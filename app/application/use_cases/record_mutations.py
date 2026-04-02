from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

from app.models.compensacao import Compensacao
from app.services.validation import validate_compensacao


class RecordStore(Protocol):
    def add_new(self, record: Compensacao) -> int: ...

    def save_edit(self, record: Compensacao) -> None: ...

    def delete_record_shift_up(self, row_idx: int, uid: str = "") -> None: ...

    def find_row_by_uid(self, uid: str) -> Optional[int]: ...


@dataclass(frozen=True)
class RecordValidationResult:
    error_message: str = ""
    duplicate_row: Optional[int] = None

    @property
    def is_valid(self) -> bool:
        return not self.error_message


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
        target = (av_tec or "").strip().upper()
        if not target:
            return None

        for existing_record in existing_records:
            if existing_record.uid == current_uid:
                continue
            if (existing_record.av_tec or "").strip().upper() != target:
                continue

            actual_row = self.record_store.find_row_by_uid(existing_record.uid) if existing_record.uid else None
            return actual_row if actual_row else existing_record.excel_row
        return None

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
        return RecordValidationResult(
            error_message=validate_compensacao(record),
            duplicate_row=self.find_duplicate_av_tec(existing_records, record.av_tec, current_uid),
        )
