import os

from app.services.sqlite_mirror_service_support import (
    build_unique_session_path,
    decode_json_object,
    decode_json_value,
    display_name_for_path,
    is_session_path,
    microbacia_key,
    normalize_session_path,
    read_source_file_identity,
    session_slug,
    stringify,
)


def test_sqlite_mirror_service_support_normalizes_paths_and_labels(tmp_path):
    workbook = tmp_path / "base.xlsx"
    workbook.write_text("conteudo", encoding="utf-8")

    normalized = normalize_session_path(str(workbook))
    assert normalized == os.path.normcase(os.path.abspath(str(workbook)))
    assert is_session_path("session://banco-local") is True
    assert display_name_for_path("session://banco-local") == "banco-local"
    assert display_name_for_path(str(workbook)) == "base.xlsx"


def test_sqlite_mirror_service_support_builds_slug_and_unique_session_path():
    assert session_slug("Sessão São Carlos") == "sessao-sao-carlos"
    candidate = build_unique_session_path(
        "Sessão São Carlos",
        existing_paths=["session://sessao-sao-carlos", "session://sessao-sao-carlos-2"],
    )
    assert candidate == "session://sessao-sao-carlos-3"


def test_sqlite_mirror_service_support_reads_identity_and_decodes_json(tmp_path):
    workbook = tmp_path / "base.xlsx"
    workbook.write_text("conteudo", encoding="utf-8")
    mtime_ns, size = read_source_file_identity(str(workbook))

    assert mtime_ns > 0
    assert size == workbook.stat().st_size
    assert stringify("  valor  ") == "valor"
    assert microbacia_key(" Gregorio ") == "GREGORIO"
    assert decode_json_value('{"a": 1}') == {"a": 1}
    assert decode_json_value("invalido") is None
    assert decode_json_object('{"a": 1}') == {"a": 1}
    assert decode_json_object("[1,2,3]") == {}
