import json
from types import SimpleNamespace

from app.services.diagnostics_service import (
    build_diagnostics_snapshot,
    default_diagnostics_filename,
    write_diagnostics_report,
)


def test_default_diagnostics_filename_uses_expected_prefix():
    filename = default_diagnostics_filename()

    assert filename.startswith("diagnostico_compensacoes_")
    assert filename.endswith(".json")


def test_build_diagnostics_snapshot_includes_window_session_data():
    window = SimpleNamespace(
        excel=SimpleNamespace(path="C:/dados/base.xlsx"),
        records=[1, 2, 3],
        filtered_records=[1],
        selected=SimpleNamespace(uid="uid-1"),
        recent_files=["a.xlsx", "b.xlsx"],
        is_dark_mode=True,
        last_marker_coords=(-22.01, -47.89),
        settings_controller=SimpleNamespace(current_map_layer=lambda: "Mapa Claro"),
    )

    snapshot = build_diagnostics_snapshot(window)

    assert snapshot["app"]["version"]
    assert snapshot["paths"]["app_data_dir"]
    assert snapshot["session"]["excel_path"] == "C:/dados/base.xlsx"
    assert snapshot["session"]["records_total"] == 3
    assert snapshot["session"]["filtered_total"] == 1
    assert snapshot["session"]["selected_uid"] == "uid-1"
    assert snapshot["session"]["map_layer"] == "Mapa Claro"
    assert snapshot["session"]["last_marker_coords"] == [-22.01, -47.89]


def test_write_diagnostics_report_persists_json(tmp_path):
    path = tmp_path / "diag.json"
    snapshot = {"app": {"name": "Compensacoes"}, "session": {"records_total": 2}}

    write_diagnostics_report(str(path), snapshot)

    with open(path, "r", encoding="utf-8") as handle:
        persisted = json.load(handle)

    assert persisted == snapshot
