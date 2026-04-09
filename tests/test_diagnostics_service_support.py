from types import SimpleNamespace

from app.services.diagnostics_service_support import (
    build_persistence_snapshot,
    build_window_session_snapshot,
)


def test_build_window_session_snapshot_handles_probe_failures():
    warnings = []
    logger = SimpleNamespace(
        warning=lambda message, *args, **kwargs: warnings.append(message % args if args else message)
    )
    window = SimpleNamespace(
        session_runtime=SimpleNamespace(
            session_path="session://banco-local",
            has_materialized_workbook=lambda: (_ for _ in ()).throw(RuntimeError("falhou")),
        ),
        records=[1, 2],
        filtered_records=[1],
        selected=SimpleNamespace(uid="uid-1"),
        recent_files=["session://banco-local"],
        is_dark_mode=True,
        last_marker_coords=(-22.0, -47.0),
        settings_controller=SimpleNamespace(
            current_map_layer=lambda: (_ for _ in ()).throw(RuntimeError("sem camada"))
        ),
        _local_session_source_status={"source": "sqlite"},
        _local_filter_facets_status={"source": "sqlite"},
        _local_mutation_sync_status={"status": "ok"},
        _local_record_read_status={"strategy": "sqlite_query"},
    )

    snapshot = build_window_session_snapshot(window, logger=logger, serializer=lambda value: value)

    assert snapshot["session_path"] == "session://banco-local"
    assert snapshot["map_layer"] == ""
    assert snapshot["workbook_runtime_loaded"] is False
    assert snapshot["selected_uid"] == "uid-1"
    assert snapshot["local_record_read"]["strategy"] == "sqlite_query"
    assert snapshot["record_integrity"].issue_count == 0
    assert len(warnings) == 2


def test_build_persistence_snapshot_includes_error_when_probe_fails():
    warnings = []
    logger = SimpleNamespace(
        warning=lambda message, *args, **kwargs: warnings.append(message % args if args else message)
    )
    window = SimpleNamespace(
        persistence_service=SimpleNamespace(
            db_path="C:/dados/state/compensacoes.db",
            build_session_diagnostics=lambda _session_path: (_ for _ in ()).throw(RuntimeError("sqlite offline")),
        )
    )

    snapshot = build_persistence_snapshot(
        window,
        session_path="session://banco-local",
        logger=logger,
        serializer=lambda value: value,
    )

    assert snapshot["available"] is True
    assert snapshot["db_path"] == "C:/dados/state/compensacoes.db"
    assert snapshot["error"] == "sqlite offline"
    assert warnings == ["Falha ao montar diagnosticos de persistencia: sqlite offline"]
