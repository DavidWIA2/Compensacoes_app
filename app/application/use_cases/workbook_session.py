from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Sequence

from app.models.compensacao import Compensacao
from app.services.validation import validate_compensacao

ProgressCallback = Callable[[int, int], None]


class WorkbookLoader(Protocol):
    path: str

    def load(self, path: str) -> list[Compensacao]: ...

    def import_records_atomic(
        self,
        records: list[Compensacao],
        *,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> int: ...


@dataclass(frozen=True)
class LoadWorkbookResult:
    path: str
    records: list[Compensacao]


@dataclass(frozen=True)
class ImportConflictDetail:
    import_row: int
    uid: str
    av_tec: str
    matched_row: Optional[int]


@dataclass(frozen=True)
class ImportValidationIssue:
    import_row: int
    uid: str
    av_tec: str
    message: str


@dataclass(frozen=True)
class ImportWorkbookAnalysis:
    import_path: str
    incoming_records: list[Compensacao]
    records_to_add: list[Compensacao]
    skipped_by_uid: int
    skipped_by_av_tec: int
    skipped_uid_details: list[ImportConflictDetail]
    skipped_av_tec_details: list[ImportConflictDetail]
    invalid_issues: list[ImportValidationIssue]

    @property
    def total_new_records(self) -> int:
        return len(self.records_to_add)

    @property
    def total_skipped(self) -> int:
        return self.skipped_by_uid + self.skipped_by_av_tec

    @property
    def total_invalid(self) -> int:
        return len(self.invalid_issues)

    @property
    def total_incoming(self) -> int:
        return len(self.incoming_records)


class WorkbookSessionUseCases:
    def __init__(
        self,
        workbook: WorkbookLoader,
        *,
        loader_factory: Callable[[], WorkbookLoader],
    ):
        self.workbook = workbook
        self.loader_factory = loader_factory

    def load_workbook(self, path: str) -> LoadWorkbookResult:
        return LoadWorkbookResult(path=path, records=self.workbook.load(path))

    def analyze_import(
        self,
        current_records: Sequence[Compensacao],
        import_path: str,
    ) -> ImportWorkbookAnalysis:
        temp_workbook = self.loader_factory()
        incoming_records = temp_workbook.load(import_path)

        current_uid_rows = {
            record.uid: record.excel_row
            for record in current_records
            if record.uid
        }
        current_av_tec_rows = {
            record.av_tec.strip().upper(): record.excel_row
            for record in current_records
            if (record.av_tec or "").strip()
        }

        records_to_add: list[Compensacao] = []
        skipped_by_uid = 0
        skipped_by_av_tec = 0
        skipped_uid_details: list[ImportConflictDetail] = []
        skipped_av_tec_details: list[ImportConflictDetail] = []
        invalid_issues: list[ImportValidationIssue] = []
        seen_uids_to_add: set[str] = set()
        seen_av_tecs_to_add: set[str] = set()

        for incoming in incoming_records:
            if incoming.uid and incoming.uid in current_uid_rows:
                skipped_by_uid += 1
                skipped_uid_details.append(
                    ImportConflictDetail(
                        import_row=incoming.excel_row,
                        uid=incoming.uid,
                        av_tec=(incoming.av_tec or "").strip(),
                        matched_row=current_uid_rows.get(incoming.uid),
                    )
                )
                continue

            normalized_av_tec = (incoming.av_tec or "").strip().upper()
            if normalized_av_tec and normalized_av_tec in current_av_tec_rows:
                skipped_by_av_tec += 1
                skipped_av_tec_details.append(
                    ImportConflictDetail(
                        import_row=incoming.excel_row,
                        uid=incoming.uid,
                        av_tec=(incoming.av_tec or "").strip(),
                        matched_row=current_av_tec_rows.get(normalized_av_tec),
                    )
                )
                continue

            validation_error = validate_compensacao(incoming)
            if validation_error:
                invalid_issues.append(
                    ImportValidationIssue(
                        import_row=incoming.excel_row,
                        uid=incoming.uid,
                        av_tec=(incoming.av_tec or "").strip(),
                        message=validation_error,
                    )
                )
                continue

            if incoming.uid and incoming.uid in seen_uids_to_add:
                invalid_issues.append(
                    ImportValidationIssue(
                        import_row=incoming.excel_row,
                        uid=incoming.uid,
                        av_tec=(incoming.av_tec or "").strip(),
                        message="UID duplicado dentro da planilha importada.",
                    )
                )
                continue

            if normalized_av_tec and normalized_av_tec in seen_av_tecs_to_add:
                invalid_issues.append(
                    ImportValidationIssue(
                        import_row=incoming.excel_row,
                        uid=incoming.uid,
                        av_tec=(incoming.av_tec or "").strip(),
                        message="Av. Tec. duplicada dentro da planilha importada.",
                    )
                )
                continue

            records_to_add.append(incoming)
            if incoming.uid:
                seen_uids_to_add.add(incoming.uid)
            if normalized_av_tec:
                seen_av_tecs_to_add.add(normalized_av_tec)

        return ImportWorkbookAnalysis(
            import_path=import_path,
            incoming_records=incoming_records,
            records_to_add=records_to_add,
            skipped_by_uid=skipped_by_uid,
            skipped_by_av_tec=skipped_by_av_tec,
            skipped_uid_details=skipped_uid_details,
            skipped_av_tec_details=skipped_av_tec_details,
            invalid_issues=invalid_issues,
        )

    def import_records(
        self,
        records: Sequence[Compensacao],
        *,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> int:
        return self.workbook.import_records_atomic(list(records), progress_callback=progress_callback)
