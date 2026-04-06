from __future__ import annotations

import os
import uuid
from typing import Sequence

from app.application.use_cases.workbook_commands import ImportExecutionResult
from app.application.use_cases.workbook_session import ImportSessionAnalysis
from app.models.compensacao import Compensacao
from app.services.audit_service import serialize_records_sample


def next_excel_row(records: Sequence[Compensacao]) -> int:
    highest_row = max(
        (int(getattr(record, "excel_row", 0) or 0) for record in records),
        default=1,
    )
    return max(highest_row, 1) + 1


def generate_unique_uid(used_uids: set[str]) -> str:
    candidate = uuid.uuid4().hex
    while candidate in used_uids:
        candidate = uuid.uuid4().hex
    return candidate


def assign_provisional_add_identity(
    record: Compensacao,
    *,
    existing_records: Sequence[Compensacao],
) -> None:
    used_uids = {
        str(getattr(existing_record, "uid", "") or "").strip()
        for existing_record in existing_records
        if str(getattr(existing_record, "uid", "") or "").strip()
    }
    record_uid = str(getattr(record, "uid", "") or "").strip()
    if not record_uid or record_uid in used_uids:
        record.uid = generate_unique_uid(used_uids)

    if int(getattr(record, "excel_row", 0) or 0) <= 0:
        record.excel_row = next_excel_row(existing_records)


def assign_provisional_import_identities(
    imported_records: Sequence[Compensacao],
    *,
    existing_records: Sequence[Compensacao],
) -> None:
    used_uids = {
        str(getattr(record, "uid", "") or "").strip()
        for record in existing_records
        if str(getattr(record, "uid", "") or "").strip()
    }
    pending_row = next_excel_row(existing_records)
    for record in imported_records:
        record_uid = str(getattr(record, "uid", "") or "").strip()
        if not record_uid or record_uid in used_uids:
            record.uid = generate_unique_uid(used_uids)
            used_uids.add(record.uid)
        else:
            used_uids.add(record_uid)

        if int(getattr(record, "excel_row", 0) or 0) <= 0:
            record.excel_row = pending_row
            pending_row += 1


def build_import_execution_result(
    *,
    analysis: ImportSessionAnalysis,
    imported_records: Sequence[Compensacao],
    backup_path: str,
) -> ImportExecutionResult:
    return ImportExecutionResult(
        import_path=analysis.import_path,
        imported_count=len(imported_records),
        total_incoming=analysis.total_incoming,
        skipped_by_uid=analysis.skipped_by_uid,
        skipped_by_av_tec=analysis.skipped_by_av_tec,
        backup_path=backup_path,
        imported_records=tuple(imported_records),
    )


def build_import_audit_metadata(
    *,
    analysis: ImportSessionAnalysis,
    import_result: ImportExecutionResult,
) -> dict[str, object]:
    return {
        "source_path": os.path.abspath(analysis.import_path),
        "incoming_records": analysis.total_incoming,
        "imported_records": import_result.imported_count,
        "skipped_by_uid": analysis.skipped_by_uid,
        "skipped_by_av_tec": analysis.skipped_by_av_tec,
        "source_kind": "excel_import",
    }


def build_import_audit_after_payload(imported_records: Sequence[Compensacao]) -> dict[str, object]:
    imported_tuple = tuple(imported_records)
    return {
        "imported_count": len(imported_tuple),
        "sample_records": serialize_records_sample(imported_tuple),
    }


def build_batch_geocode_audit_metadata(updated_records: Sequence[Compensacao]) -> dict[str, object]:
    updated_list = list(updated_records)
    return {
        "updated_records": len(updated_list),
        "sample_rows": [
            int(getattr(record, "excel_row", 0) or 0)
            for record in updated_list[:10]
        ],
        "sample_uids": [
            str(getattr(record, "uid", "") or "").strip()
            for record in updated_list[:10]
            if str(getattr(record, "uid", "") or "").strip()
        ],
    }


def build_batch_geocode_audit_after_payload(updated_records: Sequence[Compensacao]) -> dict[str, object]:
    updated_list = list(updated_records)
    return {
        "updated_count": len(updated_list),
        "sample_records": serialize_records_sample(updated_list),
    }
