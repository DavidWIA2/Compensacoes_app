from app.application.use_cases.record_mutations import RecordMutationUseCases
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


class FakeRecordStore:
    def __init__(self, *, row_by_uid=None):
        self.row_by_uid = row_by_uid or {}
        self.added = []
        self.saved = []
        self.deleted = []

    def add_new(self, record: Compensacao) -> int:
        self.added.append(record)
        return 99

    def save_edit(self, record: Compensacao) -> None:
        self.saved.append(record)

    def delete_record_shift_up(self, row_idx: int, uid: str = "") -> None:
        self.deleted.append((row_idx, uid))

    def find_row_by_uid(self, uid: str):
        return self.row_by_uid.get(uid)


def test_validate_for_create_reports_duplicate_row_from_store_lookup():
    store = FakeRecordStore(row_by_uid={"uid-2": 11})
    use_cases = RecordMutationUseCases(store)
    existing = [make_record(excel_row=5, av_tec="AT-2", uid="uid-2")]

    result = use_cases.validate_for_create(make_record(av_tec="AT-2", uid=""), existing)

    assert result.error_message == ""
    assert result.duplicate_row == 11
    assert result.is_valid is True


def test_validate_for_update_ignores_current_record_when_checking_duplicates():
    store = FakeRecordStore(row_by_uid={"uid-1": 20})
    use_cases = RecordMutationUseCases(store)
    current_record = make_record(uid="uid-1", av_tec="AT-1")

    result = use_cases.validate_for_update(current_record, [current_record])

    assert result.error_message == ""
    assert result.duplicate_row is None


def test_validate_returns_error_message_and_excel_row_fallback_for_duplicate():
    store = FakeRecordStore()
    use_cases = RecordMutationUseCases(store)
    existing = [make_record(excel_row=7, av_tec="AT-9", uid="uid-9")]
    invalid_record = make_record(oficio_processo="", av_tec="AT-9", uid="")

    result = use_cases.validate_for_create(invalid_record, existing)

    assert result.error_message == "Preencha Of\xedcio/Processo."
    assert result.duplicate_row == 7
    assert result.is_valid is False


def test_mutation_commands_delegate_to_record_store():
    store = FakeRecordStore()
    use_cases = RecordMutationUseCases(store)
    record = make_record(excel_row=14, uid="uid-14")

    added_row = use_cases.add_new(record)
    use_cases.save_edit(record)
    use_cases.delete(record)

    assert added_row == 99
    assert store.added == [record]
    assert store.saved == [record]
    assert store.deleted == [(14, "uid-14")]
