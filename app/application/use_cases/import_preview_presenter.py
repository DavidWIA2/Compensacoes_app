from __future__ import annotations

from app.application.use_cases.import_preview_presenter_support import (
    DEFAULT_IMPORT_PREVIEW_STATUS_OPTIONS,
    ImportPreviewPresentation,
    ImportPreviewRowView,
    build_import_preview_presentation,
    build_import_preview_visible_label,
    filter_import_preview_rows,
)
from app.application.use_cases.workbook_session import ImportSessionAnalysis


class ImportPreviewPresenter:
    STATUS_OPTIONS = DEFAULT_IMPORT_PREVIEW_STATUS_OPTIONS

    def build_presentation(self, analysis: ImportSessionAnalysis) -> ImportPreviewPresentation:
        return build_import_preview_presentation(analysis, status_options=self.STATUS_OPTIONS)

    @staticmethod
    def visible_label(*, visible_count: int, total_count: int) -> str:
        return build_import_preview_visible_label(visible_count=visible_count, total_count=total_count)

    def filter_rows(
        self,
        rows: tuple[ImportPreviewRowView, ...],
        *,
        selected_status: str,
        search_text: str,
    ) -> list[ImportPreviewRowView]:
        return filter_import_preview_rows(
            rows,
            selected_status=selected_status,
            search_text=search_text,
        )
