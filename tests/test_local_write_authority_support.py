from types import SimpleNamespace

from app.application.use_cases.local_write_authority_support import (
    build_create_preparation,
    build_delete_preparation,
    build_update_preparation,
    build_write_preparation,
    clone_records,
    combined_source,
    merge_fallback_records,
    merge_issues,
    normalized_workbook_path,
    same_record_identity,
)
from app.models.compensacao import Compensacao


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
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


def test_small_local_write_helpers_keep_identity_and_paths_stable():
    record_a = make_record(uid="u-1", excel_row=2)
    record_b = make_record(uid="u-1", excel_row=9)
    record_c = make_record(uid="u-3", excel_row=2)

    assert normalized_workbook_path("  C:/tmp/base.xlsx  ") == "C:/tmp/base.xlsx"
    assert same_record_identity(record_a, record_b) is True
    assert same_record_identity(record_a, record_c) is True
    assert merge_issues(("warn",), ("warn", "other")) == ("warn", "other")
    assert combined_source(SimpleNamespace(uses_sqlite=True), SimpleNamespace(uses_sqlite=True)) == "sqlite"
    assert clone_records([record_a])[0] is not record_a


def test_build_preparation_helpers_merge_metadata_and_records():
    base_result = SimpleNamespace(
        uses_sqlite=True,
        workbook_path="C:/tmp/base.xlsx",
        records=(make_record(uid="u-1"),),
        synced_at="2026-04-05T10:00:00+00:00",
        mirrored_records=3,
        session_records=3,
        issues=("base-warn",),
    )
    selected_result = SimpleNamespace(
        uses_sqlite=True,
        record=make_record(uid="u-1", excel_row=4),
        synced_at="",
        mirrored_records=3,
        session_records=3,
        issues=("sel-warn",),
    )
    duplicate_result = SimpleNamespace(
        uses_sqlite=True,
        duplicate_row=7,
        synced_at="",
        mirrored_records=3,
        session_records=3,
        issues=("dup-warn",),
    )

    base_preparation = build_write_preparation(
        workbook_path="C:/tmp/base.xlsx",
        base_result=base_result,
        selected_result=selected_result,
        duplicate_result=duplicate_result,
    )
    create_preparation = build_create_preparation(
        base_preparation=base_preparation,
        duplicate_result=duplicate_result,
    )
    update_preparation = build_update_preparation(
        base_preparation=base_preparation,
        selected_result=selected_result,
        duplicate_result=duplicate_result,
        draft_record=make_record(uid="draft", excel_row=99, endereco="Rua Nova"),
    )
    delete_preparation = build_delete_preparation(
        base_preparation=base_preparation,
        selected_result=selected_result,
    )

    assert base_preparation.uses_sqlite is True
    assert create_preparation.duplicate_row == 7
    assert update_preparation.selected_record is not None
    assert update_preparation.effective_record is not None
    assert update_preparation.effective_record.uid == "u-1"
    assert update_preparation.effective_record.excel_row == 4
    assert delete_preparation.selected_record is not None


def test_merge_fallback_records_avoids_duplicate_identity():
    selected = make_record(uid="u-1", excel_row=9)
    merged = merge_fallback_records([make_record(uid="u-1", excel_row=2)], selected)

    assert len(merged) == 1
