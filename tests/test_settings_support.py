from app.ui.controllers.settings_support import (
    build_loaded_window_settings_state,
    coerce_recent_files,
    collapse_recent_files_for_single_database_mode,
    is_named_session_path,
    normalize_session_path,
    resolve_preferred_directory,
)


def test_settings_support_normalizes_named_and_file_paths(tmp_path):
    file_path = tmp_path / "base.xlsx"

    assert is_named_session_path("session://banco-local") is True
    assert normalize_session_path("session://banco-local") == "session://banco-local"
    assert normalize_session_path(str(file_path)) == str(file_path.resolve())


def test_settings_support_coerces_recent_files_from_json():
    assert coerce_recent_files('["a.xlsx", "b.xlsx"]') == ["a.xlsx", "b.xlsx"]
    assert coerce_recent_files("{invalido") == []
    assert coerce_recent_files(["a.xlsx", "", "b.xlsx"]) == ["a.xlsx", "b.xlsx"]


def test_settings_support_collapses_recent_files_in_single_database_mode():
    assert collapse_recent_files_for_single_database_mode(["session://banco-local", "C:/tmp/base.xlsx"]) == []


def test_settings_support_builds_loaded_window_state():
    restored = []

    state = build_loaded_window_settings_state(
        is_dark_mode=True,
        geometry=b"geom",
        restore_geometry=lambda geometry: restored.append(geometry) or True,
        active_tab_index=99,
        tabs_count=4,
        recent_files=["session://banco-local"],
    )

    assert state.is_dark_mode is True
    assert state.geometry_restored is True
    assert state.active_tab_index == 0
    assert state.recent_files == ("session://banco-local",)
    assert restored == [b"geom"]


def test_settings_support_resolves_preferred_directory(tmp_path):
    file_path = tmp_path / "base.xlsx"
    file_path.write_text("ok", encoding="utf-8")
    export_dir = tmp_path / "exports"
    export_dir.mkdir()

    assert resolve_preferred_directory("session://banco-local", str(file_path)) == str(tmp_path)
    assert resolve_preferred_directory("", str(export_dir)) == str(export_dir)
