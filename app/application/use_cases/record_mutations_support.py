from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

from app.models.compensacao import Compensacao
from app.services.validation import validate_compensacao


class RecordStoreLookup(Protocol):
    def find_row_by_uid(self, uid: str) -> Optional[int]: ...


@dataclass(frozen=True)
class RecordValidationResult:
    error_message: str = ""
    duplicate_row: Optional[int] = None

    @property
    def is_valid(self) -> bool:
        return not self.error_message


def normalize_av_tec(av_tec: str) -> str:
    return str(av_tec or "").strip().upper()


def find_duplicate_av_tec_row(
    record_store: RecordStoreLookup,
    existing_records: Sequence[Compensacao],
    av_tec: str,
    current_uid: str,
) -> Optional[int]:
    target = normalize_av_tec(av_tec)
    if not target:
        return None

    for existing_record in existing_records:
        if existing_record.uid == current_uid:
            continue
        if normalize_av_tec(existing_record.av_tec) != target:
            continue

        actual_row = record_store.find_row_by_uid(existing_record.uid) if existing_record.uid else None
        return actual_row if actual_row else existing_record.excel_row
    return None


def build_validation_result(
    record: Compensacao,
    *,
    record_store: RecordStoreLookup,
    existing_records: Sequence[Compensacao],
    current_uid: str,
) -> RecordValidationResult:
    return RecordValidationResult(
        error_message=validate_compensacao(record),
        duplicate_row=find_duplicate_av_tec_row(record_store, existing_records, record.av_tec, current_uid),
    )
