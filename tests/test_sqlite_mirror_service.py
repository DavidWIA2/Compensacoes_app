import os
import sqlite3

import pytest

from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem
from app.services.sqlite_mirror_service import (
    LocalWorkspaceEntry,
    LocalWorkspaceFilterFacets,
    LocalWorkspaceOverview,
    LocalWorkspaceSnapshotSummary,
    SCHEMA_VERSION,
    NamedSessionEntry,
    SessionFilterFacets,
    SessionRecordOverview,
    SessionSnapshotSummary,
    SqliteMirrorService,
)


def make_record(
    *,
    excel_row: int,
    uid: str,
    av_tec: str,
    updated_at: str = "",
    plantios: list[PlantioItem] | None = None,
) -> Compensacao:
    return Compensacao(
        excel_row=excel_row,
        oficio_processo=f"{excel_row}/2026",
        eletronico="SIM",
        caixa=f"CX-{excel_row}",
        av_tec=av_tec,
        compensacao="12",
        endereco=f"Rua {excel_row}",
        microbacia="Gregorio",
        compensado="",
        endereco_plantio="Area principal",
        latitude_plantio="",
        longitude_plantio="",
        latitude="",
        longitude="",
        uid=uid,
        updated_at=updated_at,
        plantios=list(plantios or []),
    )


def test_sqlite_mirror_service_initializes_schema(tmp_path):
    db_path = tmp_path / "mirror.db"

    SqliteMirrorService(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        schema_version = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        record_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(records)").fetchall()
        }
        workbook_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(workbooks)").fetchall()
        }

    assert {"meta", "workbooks", "records", "plantios", "audit_events"}.issubset(tables)
    assert int(schema_version) == SCHEMA_VERSION
    assert {"source_mtime_ns", "source_size"}.issubset(workbook_columns)
    assert {"oficio_year", "tipo_key", "microbacia_key", "search_blob_norm", "updated_at"}.issubset(record_columns)


def test_sync_workbook_snapshot_persists_records_and_plantios(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("planilha-base", encoding="utf-8")
    records = [
        make_record(
            excel_row=2,
            uid="uid-1",
            av_tec="AT-1",
            plantios=[
                PlantioItem(sequence=1, endereco="Area 1", qtd_mudas="10"),
                PlantioItem(sequence=2, endereco="Area 2", qtd_mudas="15"),
            ],
        ),
        make_record(excel_row=3, uid="uid-2", av_tec="AT-2", plantios=[]),
    ]
    records[1].endereco_plantio = ""

    summary = service.sync_workbook_snapshot(str(workbook_path), records)

    assert summary.record_count == 2
    assert summary.plantio_count == 2
    assert summary.source_mtime_ns > 0
    assert summary.source_size == workbook_path.stat().st_size

    with sqlite3.connect(service.db_path) as conn:
        record_count = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        plantio_count = conn.execute("SELECT COUNT(*) FROM plantios").fetchone()[0]
        workbook_row = conn.execute(
            "SELECT record_count, plantio_count, source_mtime_ns, source_size FROM workbooks WHERE workbook_path = ?",
            (str(workbook_path.resolve()),),
        ).fetchone()

    assert record_count == 2
    assert plantio_count == 2
    assert workbook_row == (2, 2, summary.source_mtime_ns, summary.source_size)


def test_sync_workbook_snapshot_rolls_back_on_invalid_duplicate(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    workbook_path = tmp_path / "base.xlsx"
    original_records = [make_record(excel_row=2, uid="uid-1", av_tec="AT-1")]
    invalid_records = [
        make_record(excel_row=2, uid="uid-2", av_tec="AT-2"),
        make_record(excel_row=3, uid="uid-2", av_tec="AT-3"),
    ]

    service.sync_workbook_snapshot(str(workbook_path), original_records)

    with pytest.raises(sqlite3.IntegrityError):
        service.sync_workbook_snapshot(str(workbook_path), invalid_records)

    summary = service.get_workbook_snapshot_summary(str(workbook_path))

    with sqlite3.connect(service.db_path) as conn:
        persisted_rows = conn.execute(
            "SELECT uid, av_tec FROM records ORDER BY excel_row"
        ).fetchall()

    assert summary.record_count == 1
    assert persisted_rows == [("uid-1", "AT-1")]


def test_mirror_audit_event_is_idempotent_and_updates_summary(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    workbook_path = tmp_path / "base.xlsx"
    service.sync_workbook_snapshot(
        str(workbook_path),
        [make_record(excel_row=2, uid="uid-1", av_tec="AT-1")],
    )

    payload = {
        "event_id": "evt-1",
        "timestamp": "2026-03-30T12:00:00+00:00",
        "workbook_path": str(workbook_path),
        "action": "import",
        "summary": "1 registro importado",
        "backup_path": str(tmp_path / "backup.xlsx"),
        "metadata": {"source": "teste"},
    }
    service.mirror_audit_event(**payload)
    service.mirror_audit_event(**payload)

    summary = service.get_workbook_snapshot_summary(str(workbook_path))

    with sqlite3.connect(service.db_path) as conn:
        audit_rows = conn.execute(
            "SELECT event_id, action, summary FROM audit_events"
        ).fetchall()

    assert summary.audit_event_count == 1
    assert audit_rows == [("evt-1", "import", "1 registro importado")]


def test_build_workbook_diagnostics_returns_counts_and_recent_events(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    workbook_path = tmp_path / "base.xlsx"
    records = [
        make_record(
            excel_row=2,
            uid="uid-1",
            av_tec="AT-1",
            plantios=[PlantioItem(sequence=1, endereco="Area 1", qtd_mudas="10")],
        ),
        make_record(excel_row=3, uid="uid-2", av_tec="AT-2", plantios=[]),
    ]
    records[0].microbacia = "Gregorio"
    records[0].compensado = "SIM"
    records[1].microbacia = "Medeiros"
    records[1].compensado = ""
    records[1].endereco_plantio = ""

    service.sync_workbook_snapshot(str(workbook_path), records)
    service.mirror_audit_event(
        event_id="evt-1",
        timestamp="2026-03-30T12:00:00+00:00",
        workbook_path=str(workbook_path),
        action="edit",
        summary="Registro alterado",
    )

    diagnostics = service.build_workbook_diagnostics(str(workbook_path))

    assert diagnostics.record_count == 2
    assert diagnostics.plantio_count == 1
    assert diagnostics.audit_event_count == 1
    assert diagnostics.compensados_count == 1
    assert diagnostics.pendentes_count == 1
    assert ("Gregorio", 1) in diagnostics.top_microbacias
    assert diagnostics.recent_audit_events[0]["action"] == "edit"


def test_build_workbook_record_overview_returns_operational_summary(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    workbook_path = tmp_path / "base.xlsx"
    records = [
        make_record(
            excel_row=2,
            uid="uid-1",
            av_tec="AT-1",
            plantios=[PlantioItem(sequence=1, endereco="Area 1", qtd_mudas="10")],
        ),
        make_record(excel_row=3, uid="uid-2", av_tec="AT-2", plantios=[]),
    ]
    records[0].microbacia = "Gregorio"
    records[0].compensado = "SIM"
    records[0].latitude = "-22.0"
    records[0].longitude = "-47.0"
    records[1].microbacia = ""
    records[1].compensado = ""
    records[1].endereco_plantio = ""
    records[1].latitude = ""
    records[1].longitude = ""

    service.sync_workbook_snapshot(str(workbook_path), records)

    overview = service.build_workbook_record_overview(str(workbook_path), top_microbacias_limit=5, sample_limit=5)

    assert overview.total_records == 2
    assert overview.compensados_count == 1
    assert overview.pendentes_count == 1
    assert overview.records_with_plantios_count == 1
    assert overview.records_without_microbacia_count == 1
    assert overview.records_without_coordinates_count == 1
    assert ("Gregorio", 1) in overview.top_microbacias
    assert ("(sem microbacia)", 1) in overview.top_microbacias
    assert overview.sample_records[0].uid == "uid-1"
    assert overview.sample_records[0].plantio_count == 1


def test_list_records_for_workbook_reconstructs_records_and_plantios(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    workbook_path = tmp_path / "base.xlsx"
    records = [
        make_record(
            excel_row=2,
            uid="uid-1",
            av_tec="AT-1",
            updated_at="2026-04-09T12:00:00+00:00",
            plantios=[
                PlantioItem(sequence=1, endereco="Area 1", qtd_mudas="10", latitude="-22.0", longitude="-47.0"),
            ],
        ),
        make_record(excel_row=3, uid="uid-2", av_tec="AT-2", plantios=[]),
    ]
    records[0].eletronico = "Eletrônico"
    records[0].compensado = "SIM"
    service.sync_workbook_snapshot(str(workbook_path), records)

    mirrored = service.list_records_for_workbook(str(workbook_path))

    assert [record.uid for record in mirrored] == ["uid-1", "uid-2"]
    assert mirrored[0].eletronico == "Eletrônico"
    assert mirrored[0].plantios[0].endereco == "Area 1"
    assert mirrored[0].plantios[0].qtd_mudas == "10"
    assert mirrored[0].updated_at == "2026-04-09T12:00:00+00:00"


def test_incremental_record_mutations_update_sqlite_without_rebuilding_snapshot(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("base-incremental", encoding="utf-8")
    base_records = [
        make_record(excel_row=2, uid="uid-1", av_tec="AT-1"),
        make_record(excel_row=3, uid="uid-2", av_tec="AT-2"),
    ]
    service.sync_workbook_snapshot(str(workbook_path), base_records)

    added_record = make_record(
        excel_row=4,
        uid="uid-3",
        av_tec="AT-3",
        plantios=[PlantioItem(sequence=1, endereco="Area 3", qtd_mudas="20")],
    )
    added_record.microbacia = "Medeiros"
    add_summary = service.append_record_to_workbook(str(workbook_path), added_record)

    updated_record = make_record(
        excel_row=3,
        uid="uid-2",
        av_tec="AT-2B",
        plantios=[PlantioItem(sequence=1, endereco="Area 2", qtd_mudas="15")],
    )
    updated_record.caixa = "Arquivado"
    updated_record.microbacia = "Santa Maria do Leme"
    update_summary = service.update_record_in_workbook(str(workbook_path), updated_record)
    delete_summary = service.delete_record_from_workbook(str(workbook_path), base_records[0])

    mirrored = service.list_records_for_workbook(str(workbook_path))

    assert add_summary.record_count == 3
    assert update_summary.record_count == 3
    assert delete_summary.record_count == 2
    assert [record.uid for record in mirrored] == ["uid-2", "uid-3"]
    assert [record.excel_row for record in mirrored] == [2, 3]
    assert mirrored[0].av_tec == "AT-2B"
    assert mirrored[0].caixa == "Arquivado"
    assert mirrored[0].microbacia == "Santa Maria do Leme"
    assert mirrored[0].plantios[0].endereco == "Area 2"
    assert mirrored[1].plantios[0].qtd_mudas == "20"


def test_append_records_to_workbook_adds_batch_incrementally(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("base-import", encoding="utf-8")
    service.sync_workbook_snapshot(
        str(workbook_path),
        [make_record(excel_row=2, uid="uid-1", av_tec="AT-1")],
    )

    imported_records = [
        make_record(excel_row=3, uid="uid-2", av_tec="AT-2"),
        make_record(excel_row=4, uid="uid-3", av_tec="AT-3"),
    ]

    summary = service.append_records_to_workbook(str(workbook_path), imported_records)
    mirrored = service.list_records_for_workbook(str(workbook_path))

    assert summary.record_count == 3
    assert [record.uid for record in mirrored] == ["uid-1", "uid-2", "uid-3"]


def test_sqlite_mirror_service_can_lookup_record_details_and_duplicate_rows(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("base-lookups", encoding="utf-8")
    records = [
        make_record(excel_row=2, uid="uid-1", av_tec="AT-1"),
        make_record(
            excel_row=3,
            uid="uid-2",
            av_tec="AT-2",
            plantios=[PlantioItem(sequence=1, endereco="Area 2", qtd_mudas="5")],
        ),
    ]
    records[1].endereco = "Rua Atualizada"
    service.sync_workbook_snapshot(str(workbook_path), records)

    by_uid = service.find_record_by_uid_for_workbook(str(workbook_path), "uid-2")
    by_row = service.find_record_by_excel_row_for_workbook(str(workbook_path), 2)
    duplicate_row = service.find_duplicate_av_tec_for_workbook(
        str(workbook_path),
        av_tec="AT-2",
    )

    assert by_uid is not None
    assert by_uid.endereco == "Rua Atualizada"
    assert by_uid.plantios[0].endereco == "Area 2"
    assert by_row is not None
    assert by_row.uid == "uid-1"
    assert duplicate_row == 3


def test_query_records_for_workbook_applies_indexed_filters(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    workbook_path = tmp_path / "base.xlsx"
    records = [
        make_record(excel_row=2, uid="uid-1", av_tec="AT-1"),
        make_record(excel_row=3, uid="uid-2", av_tec="AT-2"),
        make_record(excel_row=4, uid="uid-3", av_tec="AT-3"),
    ]
    records[0].oficio_processo = "ABC/2026"
    records[0].eletronico = "Eletrônico"
    records[0].compensado = "SIM"
    records[0].microbacia = "Gregorio"
    records[1].oficio_processo = "XYZ/2025"
    records[1].eletronico = "Ofício"
    records[1].compensado = ""
    records[1].microbacia = "Medeiros"
    records[2].oficio_processo = "ABC/2026"
    records[2].eletronico = "Físico"
    records[2].compensado = ""
    records[2].microbacia = "Gregorio"

    service.sync_workbook_snapshot(str(workbook_path), records)

    filtered = service.query_records_for_workbook(
        str(workbook_path),
        search_text="ABC",
        status="Pendentes",
        selected_micros=("Gregorio",),
        selected_eletronicos=("Físico",),
        micro_all_selected=False,
        eletronico_all_selected=False,
        selected_year="2026",
    )

    assert [record.uid for record in filtered] == ["uid-3"]


def test_query_filter_facets_for_workbook_returns_distinct_microbacias_and_years(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    workbook_path = tmp_path / "base.xlsx"
    records = [
        make_record(excel_row=2, uid="uid-1", av_tec="AT-1"),
        make_record(excel_row=3, uid="uid-2", av_tec="AT-2"),
        make_record(excel_row=4, uid="uid-3", av_tec="AT-3"),
    ]
    records[0].oficio_processo = "ABC/2026"
    records[0].microbacia = "Gregorio"
    records[1].oficio_processo = "XYZ/2025"
    records[1].microbacia = "Medeiros"
    records[2].oficio_processo = "QWE/2026"
    records[2].microbacia = "Gregorio"

    service.sync_workbook_snapshot(str(workbook_path), records)

    facets = service.query_filter_facets_for_workbook(str(workbook_path))

    assert facets.record_count == 3
    assert facets.microbacias == ("Gregorio", "Medeiros")
    assert facets.years == ("2026", "2025")


def test_query_metrics_for_workbook_returns_same_filtered_breakdown(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    workbook_path = tmp_path / "base.xlsx"
    records = [
        make_record(excel_row=2, uid="uid-1", av_tec="AT-1"),
        make_record(excel_row=3, uid="uid-2", av_tec="AT-2"),
        make_record(excel_row=4, uid="uid-3", av_tec="AT-3"),
    ]
    records[0].oficio_processo = "ABC/2026"
    records[0].eletronico = "Eletrônico"
    records[0].compensado = ""
    records[0].compensacao = "12"
    records[0].microbacia = "Gregorio"
    records[1].oficio_processo = "ABC/2026"
    records[1].eletronico = "Ofício"
    records[1].compensado = ""
    records[1].compensacao = "8"
    records[1].microbacia = "Medeiros"
    records[2].oficio_processo = "XYZ/2026"
    records[2].eletronico = "Eletrônico"
    records[2].compensado = "SIM"
    records[2].compensacao = "5"
    records[2].microbacia = "Gregorio"

    service.sync_workbook_snapshot(str(workbook_path), records)

    metrics = service.query_metrics_for_workbook(
        str(workbook_path),
        search_text="ABC",
        status="Pendentes",
        selected_year="2026",
    )

    assert metrics["count_total"] == 2
    assert metrics["count_pend"] == 2
    assert metrics["count_comp"] == 0
    assert metrics["total_geral"] == 20.0
    assert metrics["total_pendente"] == 20.0
    assert metrics["total_compensado"] == 0.0
    assert metrics["pend_micro_sorted"] == [("Gregorio", 12.0), ("Medeiros", 8.0)]
    assert ("Eletrônico", 12.0) in metrics["pend_ele_sorted"]


def test_sqlite_mirror_service_migrates_v2_schema_and_backfills_query_columns(tmp_path):
    db_path = tmp_path / "legacy_v2.db"
    workbook_path = str((tmp_path / "base.xlsx").resolve())
    (tmp_path / "base.xlsx").write_text("legacy-v2", encoding="utf-8")

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '2')")
        conn.execute(
            """
            CREATE TABLE workbooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workbook_path TEXT NOT NULL UNIQUE COLLATE NOCASE,
                workbook_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_loaded_at TEXT NOT NULL,
                last_synced_at TEXT NOT NULL,
                record_count INTEGER NOT NULL DEFAULT 0,
                plantio_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workbook_id INTEGER NOT NULL,
                uid TEXT NOT NULL COLLATE NOCASE,
                excel_row INTEGER NOT NULL,
                oficio_processo TEXT NOT NULL,
                eletronico TEXT NOT NULL,
                caixa TEXT NOT NULL,
                av_tec TEXT NOT NULL COLLATE NOCASE,
                compensacao TEXT NOT NULL,
                endereco TEXT NOT NULL,
                microbacia TEXT NOT NULL,
                compensado TEXT NOT NULL,
                endereco_plantio TEXT NOT NULL DEFAULT '',
                latitude_plantio TEXT NOT NULL DEFAULT '',
                longitude_plantio TEXT NOT NULL DEFAULT '',
                latitude TEXT NOT NULL DEFAULT '',
                longitude TEXT NOT NULL DEFAULT '',
                synced_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE plantios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER NOT NULL,
                sequence INTEGER NOT NULL,
                endereco TEXT NOT NULL DEFAULT '',
                qtd_mudas TEXT NOT NULL DEFAULT '',
                latitude TEXT NOT NULL DEFAULT '',
                longitude TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                workbook_id INTEGER,
                workbook_path TEXT NOT NULL COLLATE NOCASE,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                summary TEXT NOT NULL,
                backup_path TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                before_json TEXT,
                after_json TEXT,
                mirrored_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO workbooks (
                id, workbook_path, workbook_name, created_at, last_loaded_at, last_synced_at, record_count, plantio_count
            ) VALUES (1, ?, 'base.xlsx', '2026-03-31T12:00:00+00:00', '2026-03-31T12:00:00+00:00', '2026-03-31T12:00:00+00:00', 1, 0)
            """,
            (workbook_path,),
        )
        conn.execute(
            """
            INSERT INTO records (
                workbook_id, uid, excel_row, oficio_processo, eletronico, caixa, av_tec, compensacao,
                endereco, microbacia, compensado, endereco_plantio, latitude_plantio, longitude_plantio,
                latitude, longitude, synced_at
            ) VALUES (1, 'uid-1', 2, 'ABC/2026', 'SIM', 'Arquivado', 'AT-1', '12', 'Rua A', 'Gregorio', '', '', '', '', '', '', '2026-03-31T12:00:00+00:00')
            """
        )
        conn.commit()

    service = SqliteMirrorService(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT oficio_year, tipo_key, microbacia_key, search_blob_norm, updated_at FROM records WHERE uid = 'uid-1'"
        ).fetchone()
        workbook_row = conn.execute(
            "SELECT source_mtime_ns, source_size FROM workbooks WHERE id = 1"
        ).fetchone()

    assert row[0] == "2026"
    assert row[1] == "ELETRONICO"
    assert row[2] == "GREGORIO"
    assert "abc/2026" in row[3]
    assert isinstance(row[4], str)
    assert int(workbook_row[0]) > 0
    assert int(workbook_row[1]) == (tmp_path / "base.xlsx").stat().st_size
    filtered = service.query_records_for_workbook(
        workbook_path,
        search_text="ABC",
        selected_eletronicos=("Eletrônico",),
        eletronico_all_selected=False,
    )
    assert [record.uid for record in filtered] == ["uid-1"]


def test_sqlite_mirror_service_exposes_session_aliases_and_wrappers(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    session_path = tmp_path / "base.xlsx"
    session_path.write_text("sessao", encoding="utf-8")
    record = make_record(excel_row=2, uid="uid-1", av_tec="AT-1")

    summary = service.sync_session_snapshot(str(session_path), [record])
    facets = service.query_filter_facets_for_session(str(session_path))
    overview = service.build_session_record_overview(str(session_path))
    diagnostics = service.build_session_diagnostics(str(session_path))
    listed = service.list_records_for_session(str(session_path))

    assert isinstance(summary, SessionSnapshotSummary)
    assert isinstance(facets, SessionFilterFacets)
    assert isinstance(overview, SessionRecordOverview)
    expected_path = os.path.normcase(str(session_path.resolve()))
    assert summary.session_path == expected_path
    assert facets.session_path == expected_path
    assert overview.session_path == expected_path
    assert diagnostics.session_path == expected_path
    assert [item.uid for item in listed] == ["uid-1"]


def test_sqlite_mirror_service_catalogs_named_sessions_with_friendly_labels(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")

    created = service.create_named_session("Sessão Operacional")
    listed = service.list_named_sessions()
    fetched = service.get_session_entry(created.session_path)

    assert isinstance(created, NamedSessionEntry)
    assert created.session_path.startswith("session://")
    assert created.display_name == "Sessão Operacional"
    assert created.picker_label == "Sessão Operacional [0 registro(s)]"
    assert fetched is not None
    assert fetched.session_path == created.session_path
    assert service.get_session_display_name(created.session_path) == "Sessão Operacional"
    assert [entry.session_path for entry in listed] == [created.session_path]


def test_sqlite_mirror_service_ensures_singleton_database_entry(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")

    singleton = service.ensure_singleton_session()
    repeated = service.ensure_singleton_session()

    assert singleton.session_path.startswith("session://")
    assert singleton.display_name == "Banco local"
    assert repeated.session_path == singleton.session_path
    assert repeated.display_name == "Banco local"


def test_sqlite_mirror_service_exposes_local_workspace_wrappers(tmp_path):
    service = SqliteMirrorService(db_path=tmp_path / "mirror.db")
    workspace = service.create_local_workspace("Base Operacional")
    record = make_record(excel_row=2, uid="uid-1", av_tec="AT-1")

    summary = service.sync_local_workspace_snapshot(workspace.session_path, [record])
    fetched = service.get_local_workspace(workspace.session_path)
    listed = service.list_local_workspaces()
    facets = service.query_filter_facets_for_local_workspace(workspace.session_path)
    overview = service.build_local_workspace_record_overview(workspace.session_path)
    diagnostics = service.build_local_workspace_diagnostics(workspace.session_path)

    assert isinstance(workspace, LocalWorkspaceEntry)
    assert isinstance(summary, LocalWorkspaceSnapshotSummary)
    assert isinstance(facets, LocalWorkspaceFilterFacets)
    assert isinstance(overview, LocalWorkspaceOverview)
    assert fetched is not None
    assert fetched.display_name == "Base Operacional"
    assert [entry.session_path for entry in listed] == [workspace.session_path]
    assert service.get_local_workspace_display_name(workspace.session_path) == "Base Operacional"
    assert diagnostics.session_path == workspace.session_path
    assert [item.uid for item in service.list_records_for_local_workspace(workspace.session_path)] == ["uid-1"]
