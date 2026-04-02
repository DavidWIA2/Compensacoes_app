from app.application.use_cases.workbook_session import WorkbookSessionUseCases
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


class FakeWorkbook:
    def __init__(self, *, records_by_path=None):
        self.path = ""
        self.records_by_path = records_by_path or {}

    def load(self, path: str) -> list[Compensacao]:
        self.path = path
        return list(self.records_by_path.get(path, []))

    def import_records_atomic(self, records, *, progress_callback=None) -> int:
        return len(records)


def test_analyze_import_reports_invalid_and_duplicate_rows_before_commit():
    current_records = [make_record(excel_row=2, uid="uid-existing", av_tec="AT-1")]
    import_records = [
        make_record(excel_row=2, uid="uid-existing", av_tec="AT-X"),
        make_record(excel_row=3, uid="uid-2", av_tec="AT-1"),
        make_record(excel_row=4, uid="uid-3", av_tec="AT-3", oficio_processo=""),
        make_record(excel_row=5, uid="uid-4", av_tec="AT-4"),
        make_record(excel_row=6, uid="uid-5", av_tec="AT-4"),
    ]

    use_cases = WorkbookSessionUseCases(
        FakeWorkbook(),
        loader_factory=lambda: FakeWorkbook(records_by_path={"import.xlsx": import_records}),
    )

    analysis = use_cases.analyze_import(current_records, "import.xlsx")

    assert analysis.total_incoming == 5
    assert analysis.skipped_by_uid == 1
    assert analysis.skipped_by_av_tec == 1
    assert analysis.total_invalid == 2
    assert analysis.total_new_records == 1
    assert [record.uid for record in analysis.records_to_add] == ["uid-4"]
    assert analysis.invalid_issues[0].import_row == 4
    assert "Preencha Of" in analysis.invalid_issues[0].message
    assert analysis.invalid_issues[1].import_row == 6
    assert "duplicada dentro da planilha importada" in analysis.invalid_issues[1].message
