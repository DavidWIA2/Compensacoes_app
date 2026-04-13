from __future__ import annotations

from typing import Callable, Optional, Protocol, Sequence

from app.application.use_cases.workbook_session_support import (
    ImportConflictDetail,  # noqa: F401
    ImportSessionAnalysis,
    ImportValidationIssue,  # noqa: F401
    LoadSessionResult,
    analyze_import_records,
    build_load_session_result,
)
from app.models.compensacao import Compensacao

ProgressCallback = Callable[[int, int], None]


class SessionSourceLoader(Protocol):
    path: str

    def load(self, path: str) -> list[Compensacao]: ...

    def import_records_atomic(
        self,
        records: list[Compensacao],
        *,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> int: ...

class SessionRuntimeUseCases:
    def __init__(
        self,
        workbook: SessionSourceLoader,
        *,
        loader_factory: Callable[[], SessionSourceLoader],
    ):
        self.workbook = workbook
        self.loader_factory = loader_factory

    def load_session(self, path: str) -> LoadSessionResult:
        return build_load_session_result(path=path, records=self.workbook.load(path))

    def load_workbook(self, path: str) -> LoadSessionResult:
        return self.load_session(path)

    def analyze_import(
        self,
        current_records: Sequence[Compensacao],
        import_path: str,
    ) -> ImportSessionAnalysis:
        temp_workbook = self.loader_factory()
        incoming_records = temp_workbook.load(import_path)
        return analyze_import_records(
            current_records=current_records,
            incoming_records=incoming_records,
            import_path=import_path,
        )

    def import_records(
        self,
        records: Sequence[Compensacao],
        *,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> int:
        return self.workbook.import_records_atomic(list(records), progress_callback=progress_callback)


WorkbookLoader = SessionSourceLoader
LoadWorkbookResult = LoadSessionResult
ImportWorkbookAnalysis = ImportSessionAnalysis
WorkbookSessionUseCases = SessionRuntimeUseCases
