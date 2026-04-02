from app.application.use_cases.import_preview_presenter import ImportPreviewPresenter
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


def test_build_presentation_summarizes_preflight_and_top_invalid_rules():
    presenter = ImportPreviewPresenter()
    analysis = ImportWorkbookAnalysis(
        import_path="importar.xlsx",
        incoming_records=[make_record(excel_row=2), make_record(excel_row=3)],
        records_to_add=[make_record(excel_row=2, uid="novo-1", av_tec="AT-NEW")],
        skipped_by_uid=1,
        skipped_by_av_tec=1,
        skipped_uid_details=[ImportConflictDetail(import_row=3, uid="dup", av_tec="AT-2", matched_row=10)],
        skipped_av_tec_details=[ImportConflictDetail(import_row=4, uid="dup-2", av_tec="AT-3", matched_row=11)],
        invalid_issues=[
            ImportValidationIssue(import_row=5, uid="inv-1", av_tec="AT-4", message="Campo X obrigatorio."),
            ImportValidationIssue(import_row=6, uid="inv-2", av_tec="AT-5", message="Campo X obrigatorio."),
        ],
    )

    presentation = presenter.build_presentation(analysis)

    assert "Arquivo analisado: importar.xlsx" in presentation.summary_text
    assert "Conflitos por UID: 1" in presentation.breakdown_text
    assert "Conflitos por Av. Tec.: 1" in presentation.breakdown_text
    assert "2x Campo X obrigatorio." in presentation.breakdown_text
    assert presentation.hint_text.startswith("A importacao foi bloqueada")
    assert len(presentation.rows) == 5


def test_filter_rows_by_status_and_search():
    presenter = ImportPreviewPresenter()
    analysis = ImportWorkbookAnalysis(
        import_path="importar.xlsx",
        incoming_records=[],
        records_to_add=[make_record(excel_row=2, uid="novo-1", av_tec="AT-NEW")],
        skipped_by_uid=1,
        skipped_by_av_tec=0,
        skipped_uid_details=[ImportConflictDetail(import_row=3, uid="dup", av_tec="AT-DUP", matched_row=10)],
        skipped_av_tec_details=[],
        invalid_issues=[],
    )

    rows = presenter.build_presentation(analysis).rows

    assert [row.status for row in presenter.filter_rows(rows, selected_status="Todos", search_text="")] == [
        "Novo",
        "UID existente",
    ]
    assert [row.uid for row in presenter.filter_rows(rows, selected_status="UID existente", search_text="")] == ["dup"]
    assert [row.av_tec for row in presenter.filter_rows(rows, selected_status="Todos", search_text="at-new")] == [
        "AT-NEW"
    ]
