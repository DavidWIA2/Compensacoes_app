from app.application.use_cases.workbook_session_support import (
    analyze_import_records,
    build_current_av_tec_rows,
    build_current_uid_rows,
    build_load_session_result,
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


def test_workbook_session_support_builds_current_indexes():
    current = [make_record(uid="uid-1", av_tec="AT-1", excel_row=3)]

    assert build_current_uid_rows(current) == {"uid-1": 3}
    assert build_current_av_tec_rows(current) == {"AT-1": 3}


def test_workbook_session_support_analyzes_import_conflicts_and_invalids():
    current = [make_record(uid="uid-1", av_tec="AT-1")]
    incoming = [
        make_record(uid="uid-1", av_tec="AT-X"),
        make_record(uid="uid-2", av_tec="AT-1"),
        make_record(uid="uid-3", av_tec="AT-3"),
        make_record(uid="uid-3", av_tec="AT-4"),
        make_record(uid="uid-4", av_tec="AT-3"),
    ]

    analysis = analyze_import_records(
        current_records=current,
        incoming_records=incoming,
        import_path="import.xlsx",
    )

    assert analysis.skipped_by_uid == 1
    assert analysis.skipped_by_av_tec == 1
    assert analysis.total_invalid == 2
    assert analysis.total_new_records == 1
    assert analysis.records_to_add[0].uid == "uid-3"


def test_workbook_session_support_builds_load_result():
    result = build_load_session_result("base.xlsx", [make_record(uid="uid-base")])

    assert result.path == "base.xlsx"
    assert result.session_path == "base.xlsx"
