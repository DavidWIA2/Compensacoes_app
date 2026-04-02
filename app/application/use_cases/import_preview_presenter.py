from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.application.use_cases.workbook_session import ImportWorkbookAnalysis


@dataclass(frozen=True)
class ImportPreviewRowView:
    line_number: str
    uid: str
    av_tec: str
    status: str
    detail: str

    def key(self) -> tuple[str, str, str, str, str]:
        return (self.line_number, self.uid, self.av_tec, self.status, self.detail)


@dataclass(frozen=True)
class ImportPreviewPresentation:
    summary_text: str
    hint_text: str
    breakdown_text: str
    status_options: tuple[str, ...]
    rows: tuple[ImportPreviewRowView, ...]


class ImportPreviewPresenter:
    STATUS_OPTIONS = ("Todos", "Novo", "UID existente", "Av. Tec. existente", "Invalido")

    def build_presentation(self, analysis: ImportWorkbookAnalysis) -> ImportPreviewPresentation:
        return ImportPreviewPresentation(
            summary_text="\n".join(
                [
                    f"Arquivo analisado: {analysis.import_path}",
                    f"Registros encontrados: {analysis.total_incoming}",
                    f"Novos para importar: {analysis.total_new_records}",
                    f"Ignorados por UID existente: {analysis.skipped_by_uid}",
                    f"Ignorados por Av. Tec. existente: {analysis.skipped_by_av_tec}",
                    f"Invalidos: {analysis.total_invalid}",
                ]
            ),
            hint_text=self._build_hint_text(analysis),
            breakdown_text=self._build_breakdown_text(analysis),
            status_options=self.STATUS_OPTIONS,
            rows=self._build_rows(analysis),
        )

    @staticmethod
    def visible_label(*, visible_count: int, total_count: int) -> str:
        return f"Mostrando {visible_count} de {total_count} itens"

    def filter_rows(
        self,
        rows: tuple[ImportPreviewRowView, ...],
        *,
        selected_status: str,
        search_text: str,
    ) -> list[ImportPreviewRowView]:
        normalized_search = str(search_text or "").strip().lower()
        filtered: list[ImportPreviewRowView] = []
        for row in rows:
            if selected_status and selected_status != "Todos" and row.status != selected_status:
                continue
            if normalized_search:
                haystack = " ".join(row.key()).strip().lower()
                if normalized_search not in haystack:
                    continue
            filtered.append(row)
        return filtered

    @staticmethod
    def _build_hint_text(analysis: ImportWorkbookAnalysis) -> str:
        if analysis.total_invalid:
            return "A importacao foi bloqueada. Corrija os itens marcados como Invalidos antes de tentar novamente."
        return "Revise o preflight abaixo. Os itens marcados como Novo serao importados se voce continuar."

    @staticmethod
    def _build_rows(analysis: ImportWorkbookAnalysis) -> tuple[ImportPreviewRowView, ...]:
        rows: list[ImportPreviewRowView] = []

        for record in analysis.records_to_add:
            rows.append(
                ImportPreviewRowView(
                    line_number=str(record.excel_row or ""),
                    uid=str(record.uid or ""),
                    av_tec=str(record.av_tec or ""),
                    status="Novo",
                    detail="Pronto para importar",
                )
            )

        for detail in analysis.skipped_uid_details:
            matched = f"Registro ja existe na linha {detail.matched_row}." if detail.matched_row else "UID ja existe."
            rows.append(
                ImportPreviewRowView(
                    line_number=str(detail.import_row or ""),
                    uid=str(detail.uid or ""),
                    av_tec=str(detail.av_tec or ""),
                    status="UID existente",
                    detail=matched,
                )
            )

        for detail in analysis.skipped_av_tec_details:
            matched = (
                f"Av. Tec. ja cadastrada na linha {detail.matched_row}."
                if detail.matched_row
                else "Av. Tec. ja cadastrada."
            )
            rows.append(
                ImportPreviewRowView(
                    line_number=str(detail.import_row or ""),
                    uid=str(detail.uid or ""),
                    av_tec=str(detail.av_tec or ""),
                    status="Av. Tec. existente",
                    detail=matched,
                )
            )

        for issue in analysis.invalid_issues:
            rows.append(
                ImportPreviewRowView(
                    line_number=str(issue.import_row or ""),
                    uid=str(issue.uid or ""),
                    av_tec=str(issue.av_tec or ""),
                    status="Invalido",
                    detail=str(issue.message or ""),
                )
            )

        return tuple(rows)

    @staticmethod
    def _build_breakdown_text(analysis: ImportWorkbookAnalysis) -> str:
        lines = [
            "Resumo da analise:",
            f"- Prontos para importar: {analysis.total_new_records}",
            f"- Conflitos por UID: {analysis.skipped_by_uid}",
            f"- Conflitos por Av. Tec.: {analysis.skipped_by_av_tec}",
            f"- Bloqueios por validacao: {analysis.total_invalid}",
        ]

        if analysis.invalid_issues:
            lines.append("Regras invalidas mais frequentes:")
            for message, count in Counter(issue.message for issue in analysis.invalid_issues).most_common(3):
                lines.append(f"- {count}x {message}")
        else:
            lines.append("Nenhuma regra bloqueante foi encontrada nesta analise.")

        return "\n".join(lines)
