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
    def __init__(self, *, records_by_path=None, import_result=None):
        self.path = ""
        self.records_by_path = records_by_path or {}
        self.import_result = import_result
        self.load_calls = []
        self.imported_records = []

    def load(self, path: str) -> list[Compensacao]:
        self.load_calls.append(path)
        self.path = path
        return list(self.records_by_path.get(path, []))

    def import_records_atomic(self, records, *, progress_callback=None) -> int:
        self.imported_records = list(records)
        if progress_callback:
            total = len(records)
            for index, _record in enumerate(records, start=1):
                progress_callback(index, total)
        return self.import_result if self.import_result is not None else len(records)


def test_load_workbook_returns_loaded_path_and_records():
    workbook = FakeWorkbook(records_by_path={"base.xlsx": [make_record(uid="uid-base")]})
    use_cases = WorkbookSessionUseCases(workbook, loader_factory=lambda: FakeWorkbook())

    result = use_cases.load_workbook("base.xlsx")

    assert result.path == "base.xlsx"
    assert [record.uid for record in result.records] == ["uid-base"]
    assert workbook.load_calls == ["base.xlsx"]


def test_analyze_import_skips_existing_uid_and_av_tec_conflicts():
    current_records = [
        make_record(uid="uid-1", av_tec="AT-1"),
        make_record(uid="uid-2", av_tec="AT-2"),
    ]
    import_records = [
        make_record(uid="uid-1", av_tec="AT-X"),
        make_record(uid="uid-10", av_tec="AT-2"),
        make_record(uid="uid-11", av_tec="AT-11"),
    ]
    temp_workbook = FakeWorkbook(records_by_path={"import.xlsx": import_records})
    use_cases = WorkbookSessionUseCases(FakeWorkbook(), loader_factory=lambda: temp_workbook)

    analysis = use_cases.analyze_import(current_records, "import.xlsx")

    assert analysis.import_path == "import.xlsx"
    assert analysis.skipped_by_uid == 1
    assert analysis.skipped_by_av_tec == 1
    assert analysis.total_skipped == 2
    assert analysis.total_new_records == 1
    assert [record.uid for record in analysis.records_to_add] == ["uid-11"]


def test_import_records_uses_atomic_commit_and_reports_progress():
    workbook = FakeWorkbook(import_result=2)
    use_cases = WorkbookSessionUseCases(workbook, loader_factory=lambda: FakeWorkbook())
    records = [make_record(uid="uid-20"), make_record(uid="uid-21", av_tec="AT-21")]
    progress_updates = []

    result = use_cases.import_records(
        records,
        progress_callback=lambda current, total: progress_updates.append((current, total)),
    )

    assert result == 2
    assert workbook.imported_records == records
    assert progress_updates == [(1, 2), (2, 2)]
