from app.application.use_cases.import_preview_presenter_support import (
    DEFAULT_IMPORT_PREVIEW_STATUS_OPTIONS,
    build_import_preview_presentation,
    build_import_preview_visible_label,
    filter_import_preview_rows,
)
from app.application.use_cases.workbook_session import (
    ImportConflictDetail,
    ImportValidationIssue,
    ImportWorkbookAnalysis,
)
from app.models.compensacao import Compensacao


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 3,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "Gregorio",
        "compensado": "",
        "uid": "uid-1",
    }
    base.update(overrides)
    return Compensacao(**base)


def make_analysis() -> ImportWorkbookAnalysis:
    return ImportWorkbookAnalysis(
        import_path="importar.xlsx",
        incoming_records=[make_record(excel_row=2), make_record(excel_row=3)],
        records_to_add=[make_record(excel_row=2, uid="novo-1", av_tec="AT-NEW")],
        skipped_by_uid=1,
        skipped_by_av_tec=1,
        skipped_uid_details=[ImportConflictDetail(import_row=3, uid="dup", av_tec="AT-2", matched_row=10)],
        skipped_av_tec_details=[ImportConflictDetail(import_row=4, uid="dup-2", av_tec="AT-3", matched_row=11)],
        invalid_issues=[ImportValidationIssue(import_row=5, uid="inv-1", av_tec="AT-4", message="Campo X obrigatorio.")],
    )


def test_support_builds_complete_import_preview_presentation():
    presentation = build_import_preview_presentation(make_analysis())

    assert presentation.status_options == DEFAULT_IMPORT_PREVIEW_STATUS_OPTIONS
    assert "Arquivo analisado: importar.xlsx" in presentation.summary_text
    assert "Conflitos por UID: 1" in presentation.breakdown_text
    assert presentation.hint_text.startswith("A importacao foi bloqueada")
    assert [row.status for row in presentation.rows] == [
        "Novo",
        "UID existente",
        "Av. Tec. existente",
        "Invalido",
    ]


def test_support_filters_rows_by_status_and_search_text():
    rows = build_import_preview_presentation(make_analysis()).rows

    filtered = filter_import_preview_rows(rows, selected_status="UID existente", search_text="dup")

    assert [row.uid for row in filtered] == ["dup"]


def test_support_builds_visible_label():
    assert build_import_preview_visible_label(visible_count=2, total_count=4) == "Mostrando 2 de 4 itens"
