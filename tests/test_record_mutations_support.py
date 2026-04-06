from app.application.use_cases.record_mutations_support import (
    build_validation_result,
    find_duplicate_av_tec_row,
    normalize_av_tec,
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


class FakeRecordStore:
    def __init__(self, row_by_uid=None):
        self.row_by_uid = row_by_uid or {}

    def find_row_by_uid(self, uid: str):
        return self.row_by_uid.get(uid)


def test_duplicate_lookup_prefers_store_row_and_ignores_current_uid():
    store = FakeRecordStore(row_by_uid={"uid-2": 11})
    existing = [make_record(excel_row=7, av_tec="at-2", uid="uid-2")]

    duplicate = find_duplicate_av_tec_row(store, existing, "AT-2", current_uid="")
    ignored = find_duplicate_av_tec_row(store, existing, "AT-2", current_uid="uid-2")

    assert duplicate == 11
    assert ignored is None


def test_validation_helper_combines_validation_and_duplicate_row():
    store = FakeRecordStore()
    existing = [make_record(excel_row=7, av_tec="AT-9", uid="uid-9")]
    result = build_validation_result(
        make_record(oficio_processo="", av_tec="AT-9", uid=""),
        record_store=store,
        existing_records=existing,
        current_uid="",
    )

    assert result.error_message == "Preencha Of\xedcio/Processo."
    assert result.duplicate_row == 7
    assert result.is_valid is False


def test_normalize_av_tec_strips_and_uppercases():
    assert normalize_av_tec("  at-1  ") == "AT-1"
