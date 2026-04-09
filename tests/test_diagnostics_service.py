import json
from types import SimpleNamespace

from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.models.compensacao import Compensacao
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
    records = [
        Compensacao(
            excel_row=2,
            oficio_processo="206/2021",
            eletronico="Oficio",
            caixa="",
            av_tec="107/2021",
            compensacao="1",
            endereco="Rua A",
            microbacia="Gregorio",
            compensado="NAO",
            uid="uid-1",
        ),
        Compensacao(
            excel_row=3,
            oficio_processo="207/2021",
            eletronico="Oficio",
            caixa="",
            av_tec="107/2021",
            compensacao="1",
            endereco="Rua B",
            microbacia="Gregorio",
            compensado="NAO",
            uid="uid-2",
        ),
    ]
    window = SimpleNamespace(
        session_runtime=SimpleNamespace(
            path="C:/dados/base.xlsx",
            has_materialized_workbook=lambda: False,
        ),
        records=records,
        filtered_records=[1],
        selected=SimpleNamespace(uid="uid-1"),
        recent_files=["a.xlsx", "b.xlsx"],
        is_dark_mode=True,
        last_marker_coords=(-22.01, -47.89),
        settings_controller=SimpleNamespace(current_map_layer=lambda: "Mapa Claro"),
        _local_session_source_status={"source": "sqlite", "strategy": "sqlite_snapshot", "filtered_records": 2},
        _local_filter_facets_status={"source": "sqlite", "micro_count": 2, "year_count": 1},
        _local_mutation_sync_status={"status": "sqlite", "operation": "edit", "record_count": 2},
        _local_record_read_status=LocalRecordReadStatus(
            status="sqlite",
            source="sqlite",
            strategy="sqlite_query",
            workbook_path="C:/dados/base.xlsx",
            synced_at="2026-03-31T12:00:00+00:00",
            mirrored_records=2,
            session_records=2,
            filtered_records=1,
        ),
    )

    snapshot = build_diagnostics_snapshot(window)

    assert snapshot["app"]["version"]
    assert snapshot["paths"]["app_data_dir"]
    assert snapshot["session"]["session_path"] == "C:/dados/base.xlsx"
    assert snapshot["session"]["workbook_runtime_loaded"] is False
    assert snapshot["session"]["session_runtime_materialized"] is False
    assert snapshot["session"]["records_total"] == 2
    assert snapshot["session"]["filtered_total"] == 1
    assert snapshot["session"]["selected_uid"] == "uid-1"
    assert snapshot["session"]["map_layer"] == "Mapa Claro"
    assert snapshot["session"]["last_marker_coords"] == [-22.01, -47.89]
    assert snapshot["session"]["local_session_source"]["strategy"] == "sqlite_snapshot"
    assert snapshot["session"]["local_filter_facets"]["source"] == "sqlite"
    assert snapshot["session"]["local_mutation_sync"]["operation"] == "edit"
    assert snapshot["session"]["local_record_read"]["source"] == "sqlite"
    assert snapshot["session"]["local_record_read"]["filtered_records"] == 1
    assert snapshot["session"]["record_integrity"]["issue_count"] == 1
    assert snapshot["session"]["record_integrity"]["error_count"] == 1


def test_build_diagnostics_snapshot_includes_persistence_data():
    persistence_service = SimpleNamespace(
        db_path="C:/dados/state/compensacoes.db",
        build_session_diagnostics=lambda session_path: SimpleNamespace(
            session_path=session_path,
            workbook_path=session_path,
            db_path="C:/dados/state/compensacoes.db",
            synced_at="2026-03-30T12:00:00+00:00",
            record_count=3,
            plantio_count=1,
            audit_event_count=2,
            compensados_count=1,
            pendentes_count=2,
            top_microbacias=(("Gregorio", 2),),
            recent_audit_events=({"action": "edit", "summary": "Registro alterado", "timestamp": "2026-03-30T12:00:00+00:00"},),
        ),
    )
    window = SimpleNamespace(
        session_runtime=SimpleNamespace(
            path="C:/dados/base.xlsx",
            has_materialized_workbook=lambda: False,
        ),
        records=[1, 2, 3],
        filtered_records=[1, 2],
        selected=None,
        recent_files=[],
        is_dark_mode=False,
        last_marker_coords=(),
        settings_controller=SimpleNamespace(current_map_layer=lambda: "Mapa Claro"),
        persistence_service=persistence_service,
        _local_session_source_status={"source": "session", "issues": ["divergente"]},
        _local_filter_facets_status={"source": "session", "issues": ["fallback"]},
        _local_mutation_sync_status={"status": "falha", "operation": "import", "issues": ["sqlite offline"]},
        _local_record_read_status=LocalRecordReadStatus(
            status="fallback",
            source="session",
            strategy="session_filter",
            workbook_path="C:/dados/base.xlsx",
            synced_at="2026-03-31T12:00:00+00:00",
            mirrored_records=2,
            session_records=3,
            filtered_records=2,
            issues=("Espelho com contagem divergente.",),
        ),
    )

    snapshot = build_diagnostics_snapshot(window)

    assert snapshot["persistence"]["available"] is True
    assert snapshot["persistence"]["db_path"] == "C:/dados/state/compensacoes.db"
    assert snapshot["persistence"]["session"]["record_count"] == 3
    assert snapshot["persistence"]["session"]["session_path"] == "C:/dados/base.xlsx"
    assert snapshot["persistence"]["workbook"]["record_count"] == 3
    assert snapshot["persistence"]["workbook"]["recent_audit_events"][0]["action"] == "edit"
    assert snapshot["session"]["local_session_source"]["source"] == "session"
    assert snapshot["session"]["local_filter_facets"]["source"] == "session"
    assert snapshot["session"]["local_mutation_sync"]["status"] == "falha"
    assert snapshot["session"]["local_record_read"]["status"] == "fallback"


def test_write_diagnostics_report_persists_json(tmp_path):
    path = tmp_path / "diag.json"
    snapshot = {"app": {"name": "Compensacoes"}, "session": {"records_total": 2}}

    write_diagnostics_report(str(path), snapshot)

    with open(path, "r", encoding="utf-8") as handle:
        persisted = json.load(handle)

    assert persisted == snapshot
