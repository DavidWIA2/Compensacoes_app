from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem
from app.services.plantio_service import record_plantio_items
from app.services.records_service import (
    build_search_blob,
    display_tipo_value,
    extract_year,
    normalize_tipo_key,
    remove_accents,
)
from app.utils.app_paths import ensure_dir, resolve_data_path
from app.utils.logger import get_logger
from app.services.sqlite_mirror_service_support import (
    build_unique_session_path as _build_unique_session_path_helper,
    decode_json_object as _decode_json_object_helper,
    decode_json_value as _decode_json_value_helper,
    display_name_for_path as _display_name_for_path_helper,
    is_session_path as _is_session_path,
    microbacia_key as _microbacia_key,
    normalize_session_path as _normalize_path,
    read_source_file_identity as _read_workbook_file_identity,
    stringify as _stringify,
    utc_timestamp as _utc_timestamp,
)


logger = get_logger("Persistence.SQLite")

SCHEMA_VERSION = 5
DEFAULT_DB_NAME = "compensacoes.db"
SESSION_SCHEME = "session://"
DEFAULT_SINGLETON_SESSION_PATH = f"{SESSION_SCHEME}banco-local"
DEFAULT_SINGLETON_SESSION_NAME = "Banco local"


@dataclass(frozen=True)
class WorkbookSnapshotSummary:
    workbook_path: str
    synced_at: str
    record_count: int
    plantio_count: int
    audit_event_count: int
    source_mtime_ns: int = 0
    source_size: int = 0

    @property
    def session_path(self) -> str:
        return self.workbook_path


@dataclass(frozen=True)
class WorkbookFilterFacets:
    workbook_path: str
    synced_at: str
    record_count: int
    microbacias: tuple[str, ...] = ()
    years: tuple[str, ...] = ()

    @property
    def session_path(self) -> str:
        return self.workbook_path


@dataclass(frozen=True)
class WorkbookMirrorDiagnostics:
    workbook_path: str
    db_path: str
    synced_at: str
    record_count: int
    plantio_count: int
    audit_event_count: int
    compensados_count: int
    pendentes_count: int
    top_microbacias: tuple[tuple[str, int], ...] = ()
    recent_audit_events: tuple[dict[str, str], ...] = ()

    @property
    def session_path(self) -> str:
        return self.workbook_path


@dataclass(frozen=True)
class MirroredRecordSample:
    excel_row: int
    uid: str
    av_tec: str
    microbacia: str
    compensado: str
    plantio_count: int


@dataclass(frozen=True)
class WorkbookRecordOverview:
    workbook_path: str
    synced_at: str
    total_records: int
    compensados_count: int
    pendentes_count: int
    records_with_plantios_count: int
    records_without_microbacia_count: int
    records_without_coordinates_count: int
    top_microbacias: tuple[tuple[str, int], ...] = ()
    sample_records: tuple[MirroredRecordSample, ...] = ()

    @property
    def session_path(self) -> str:
        return self.workbook_path


SessionSnapshotSummary = WorkbookSnapshotSummary
SessionFilterFacets = WorkbookFilterFacets
SessionMirrorDiagnostics = WorkbookMirrorDiagnostics
SessionRecordSample = MirroredRecordSample
SessionRecordOverview = WorkbookRecordOverview
LocalWorkspaceSnapshotSummary = WorkbookSnapshotSummary
LocalWorkspaceFilterFacets = WorkbookFilterFacets
LocalWorkspaceDiagnostics = WorkbookMirrorDiagnostics
LocalWorkspaceRecordSample = MirroredRecordSample
LocalWorkspaceOverview = WorkbookRecordOverview


@dataclass(frozen=True)
class NamedSessionEntry:
    session_path: str
    display_name: str
    record_count: int = 0
    created_at: str = ""
    last_loaded_at: str = ""
    last_synced_at: str = ""

    @property
    def workbook_path(self) -> str:
        return self.session_path

    @property
    def picker_label(self) -> str:
        suffix = f"{self.record_count} registro(s)"
        return f"{self.display_name} [{suffix}]"


LocalWorkspaceEntry = NamedSessionEntry


class SqliteMirrorService:
    def __init__(self, *, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else resolve_data_path("state", DEFAULT_DB_NAME)
        ensure_dir(self.db_path.parent)
        self.initialize()

    def create_named_session(self, session_name: str) -> NamedSessionEntry:
        normalized_name = _stringify(session_name)
        if not normalized_name:
            raise ValueError("Informe um nome para criar a sessão.")

        created_at = _utc_timestamp()
        with self._connect() as conn:
            session_path = self._build_unique_session_path(conn, normalized_name)
            conn.execute(
                """
                INSERT INTO workbooks (
                    workbook_path,
                    workbook_name,
                    created_at,
                    last_loaded_at,
                    last_synced_at,
                    record_count,
                    plantio_count,
                    source_mtime_ns,
                    source_size
                ) VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0)
                """,
                (session_path, normalized_name, created_at, created_at, created_at),
            )
            row = conn.execute(
                """
                SELECT workbook_path, workbook_name, record_count, created_at, last_loaded_at, last_synced_at
                FROM workbooks
                WHERE workbook_path = ?
                """,
                (session_path,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Não foi possível criar a sessão SQLite.")
        return self._row_to_named_session_entry(row)

    def list_named_sessions(self, *, limit: int = 200) -> list[NamedSessionEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT workbook_path, workbook_name, record_count, created_at, last_loaded_at, last_synced_at
                FROM workbooks
                WHERE workbook_path LIKE ?
                ORDER BY last_loaded_at DESC, created_at DESC, workbook_name COLLATE NOCASE ASC
                LIMIT ?
                """,
                (f"{SESSION_SCHEME}%", max(int(limit), 0)),
            ).fetchall()
        return [self._row_to_named_session_entry(row) for row in rows]

    def get_session_entry(self, session_path: str) -> NamedSessionEntry | None:
        normalized_path = _normalize_path(session_path)
        if not normalized_path:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT workbook_path, workbook_name, record_count, created_at, last_loaded_at, last_synced_at
                FROM workbooks
                WHERE workbook_path = ?
                """,
                (normalized_path,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_named_session_entry(row)

    def touch_session(self, session_path: str) -> None:
        normalized_path = _normalize_path(session_path)
        if not normalized_path:
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE workbooks
                SET last_loaded_at = ?
                WHERE workbook_path = ?
                """,
                (_utc_timestamp(), normalized_path),
            )

    def list_local_workspaces(self, *, limit: int = 200) -> list[LocalWorkspaceEntry]:
        return self.list_named_sessions(limit=limit)

    def create_local_workspace(self, workspace_name: str) -> LocalWorkspaceEntry:
        return self.create_named_session(workspace_name)

    def get_local_workspace(self, session_path: str) -> LocalWorkspaceEntry | None:
        return self.get_session_entry(session_path)

    def touch_local_workspace(self, workspace_path: str) -> None:
        self.touch_session(workspace_path)

    def ensure_local_workspace(self) -> LocalWorkspaceEntry:
        return self.ensure_singleton_session()

    def ensure_default_local_workspace(self) -> LocalWorkspaceEntry:
        return self.ensure_local_workspace()

    def ensure_singleton_session(self) -> NamedSessionEntry:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT workbook_path, workbook_name, record_count, created_at, last_loaded_at, last_synced_at
                FROM workbooks
                WHERE workbook_path = ?
                """,
                (DEFAULT_SINGLETON_SESSION_PATH,),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    """
                    SELECT workbook_path, workbook_name, record_count, created_at, last_loaded_at, last_synced_at
                    FROM workbooks
                    WHERE workbook_path LIKE ?
                    ORDER BY
                        CASE WHEN record_count > 0 THEN 0 ELSE 1 END,
                        last_loaded_at DESC,
                        created_at DESC,
                        workbook_name COLLATE NOCASE ASC
                    LIMIT 1
                    """,
                    (f"{SESSION_SCHEME}%",),
                ).fetchone()
            if row is None:
                created_at = _utc_timestamp()
                conn.execute(
                    """
                    INSERT INTO workbooks (
                        workbook_path,
                        workbook_name,
                        created_at,
                        last_loaded_at,
                        last_synced_at,
                        record_count,
                        plantio_count,
                        source_mtime_ns,
                        source_size
                    ) VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0)
                    """,
                    (
                        DEFAULT_SINGLETON_SESSION_PATH,
                        DEFAULT_SINGLETON_SESSION_NAME,
                        created_at,
                        created_at,
                        created_at,
                    ),
                )
                row = conn.execute(
                    """
                    SELECT workbook_path, workbook_name, record_count, created_at, last_loaded_at, last_synced_at
                    FROM workbooks
                    WHERE workbook_path = ?
                    """,
                    (DEFAULT_SINGLETON_SESSION_PATH,),
                ).fetchone()
            else:
                selected_path = _stringify(row["workbook_path"])
                if selected_path and selected_path != DEFAULT_SINGLETON_SESSION_PATH:
                    conn.execute(
                        """
                        UPDATE workbooks
                        SET workbook_path = ?, workbook_name = ?
                        WHERE workbook_path = ?
                        """,
                        (
                            DEFAULT_SINGLETON_SESSION_PATH,
                            DEFAULT_SINGLETON_SESSION_NAME,
                            selected_path,
                        ),
                    )
                    conn.execute(
                        """
                        UPDATE audit_events
                        SET workbook_path = ?
                        WHERE workbook_path = ?
                        """,
                        (
                            DEFAULT_SINGLETON_SESSION_PATH,
                            selected_path,
                        ),
                    )
                    selected_path = DEFAULT_SINGLETON_SESSION_PATH
                conn.execute(
                    """
                    UPDATE workbooks
                    SET workbook_name = ?
                    WHERE workbook_path = ?
                    """,
                    (
                        DEFAULT_SINGLETON_SESSION_NAME,
                        selected_path,
                    ),
                )
                row = conn.execute(
                    """
                    SELECT workbook_path, workbook_name, record_count, created_at, last_loaded_at, last_synced_at
                    FROM workbooks
                    WHERE workbook_path = ?
                    """,
                    (selected_path,),
                ).fetchone()

        if row is None:
            raise RuntimeError("Não foi possível preparar o banco local único.")
        return self._row_to_named_session_entry(row)

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            current_version = self._schema_version(conn)
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Versao de schema {current_version} mais nova que a suportada ({SCHEMA_VERSION})."
                )
            if current_version == 0:
                self._create_schema(conn)
            if current_version == 1:
                self._migrate_v1_to_v2(conn)
                current_version = 2
            if current_version == 2:
                self._migrate_v2_to_v3(conn)
                current_version = 3
            if current_version == 3:
                self._migrate_v3_to_v4(conn)
                current_version = 4
            if current_version == 4:
                self._migrate_v4_to_v5(conn)
            conn.execute(
                """
                INSERT INTO meta (key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

    def sync_workbook_snapshot(
        self,
        workbook_path: str,
        records: Sequence[Compensacao],
    ) -> WorkbookSnapshotSummary:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            raise ValueError("O caminho da planilha precisa ser informado para sincronizar o espelho local.")

        synced_at = _utc_timestamp()
        source_mtime_ns, source_size = _read_workbook_file_identity(normalized_path)
        inserted_records = 0
        inserted_plantios = 0

        with self._connect() as conn:
            workbook_id = self._upsert_workbook(conn, normalized_path, synced_at)
            conn.execute("DELETE FROM records WHERE workbook_id = ?", (workbook_id,))

            for record in records:
                cursor = conn.execute(
                    self._record_insert_sql(),
                    self._record_insert_params(
                        workbook_id=workbook_id,
                        record=record,
                        synced_at=synced_at,
                    ),
                )
                inserted_records += 1
                record_id = int(cursor.lastrowid or 0)
                if record_id <= 0:
                    raise RuntimeError("Nao foi possivel persistir o registro no espelho SQLite.")

                inserted_plantios += self._replace_record_plantios(conn, record_id=record_id, record=record)
            summary = self._refresh_workbook_summary(
                conn,
                workbook_id=workbook_id,
                workbook_path=normalized_path,
                synced_at=synced_at,
                source_mtime_ns=source_mtime_ns,
                source_size=source_size,
            )

        logger.info(
            "[SQLITE] Espelho sincronizado para %s com %s registro(s) e %s plantio(s).",
            normalized_path,
            inserted_records,
            inserted_plantios,
        )
        return summary

    def append_record_to_workbook(
        self,
        workbook_path: str,
        record: Compensacao,
    ) -> WorkbookSnapshotSummary:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            raise ValueError("O caminho da planilha precisa ser informado para sincronizar o espelho local.")

        synced_at = _utc_timestamp()
        with self._connect() as conn:
            workbook_id = self._upsert_workbook(conn, normalized_path, synced_at)
            record_id = self._insert_record(conn, workbook_id=workbook_id, record=record, synced_at=synced_at)
            if record_id <= 0:
                raise RuntimeError("Nao foi possivel persistir o registro no espelho SQLite.")
            return self._refresh_workbook_summary(
                conn,
                workbook_id=workbook_id,
                workbook_path=normalized_path,
                synced_at=synced_at,
            )

    def append_records_to_workbook(
        self,
        workbook_path: str,
        records: Sequence[Compensacao],
    ) -> WorkbookSnapshotSummary:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            raise ValueError("O caminho da planilha precisa ser informado para sincronizar o espelho local.")
        if not records:
            return self.get_workbook_snapshot_summary(normalized_path)

        synced_at = _utc_timestamp()
        with self._connect() as conn:
            workbook_id = self._upsert_workbook(conn, normalized_path, synced_at)
            for record in records:
                self._insert_record(conn, workbook_id=workbook_id, record=record, synced_at=synced_at)
            return self._refresh_workbook_summary(
                conn,
                workbook_id=workbook_id,
                workbook_path=normalized_path,
                synced_at=synced_at,
            )

    def update_record_in_workbook(
        self,
        workbook_path: str,
        record: Compensacao,
    ) -> WorkbookSnapshotSummary:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            raise ValueError("O caminho da planilha precisa ser informado para sincronizar o espelho local.")

        synced_at = _utc_timestamp()
        with self._connect() as conn:
            workbook_id = self._upsert_workbook(conn, normalized_path, synced_at)
            record_row = self._find_record_row_for_mutation(conn, workbook_id=workbook_id, record=record)
            if record_row is None:
                raise LookupError("Nao foi possivel localizar o registro no espelho SQLite para atualizacao.")
            record_id = int(record_row["id"] or 0)
            if record_id <= 0:
                raise LookupError("Nao foi possivel localizar o registro no espelho SQLite para atualizacao.")
            self._update_record(conn, record_id=record_id, record=record, synced_at=synced_at)
            return self._refresh_workbook_summary(
                conn,
                workbook_id=workbook_id,
                workbook_path=normalized_path,
                synced_at=synced_at,
            )

    def delete_record_from_workbook(
        self,
        workbook_path: str,
        record: Compensacao,
    ) -> WorkbookSnapshotSummary:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            raise ValueError("O caminho da planilha precisa ser informado para sincronizar o espelho local.")

        synced_at = _utc_timestamp()
        with self._connect() as conn:
            workbook_id = self._upsert_workbook(conn, normalized_path, synced_at)
            record_row = self._find_record_row_for_mutation(conn, workbook_id=workbook_id, record=record)
            if record_row is None:
                raise LookupError("Nao foi possivel localizar o registro no espelho SQLite para exclusao.")
            record_id = int(record_row["id"] or 0)
            target_excel_row = int(record_row["excel_row"] or 0)
            conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
            if target_excel_row > 0:
                conn.execute(
                    """
                    UPDATE records
                    SET excel_row = excel_row - 1
                    WHERE workbook_id = ? AND excel_row > ?
                    """,
                    (workbook_id, target_excel_row),
                )
            return self._refresh_workbook_summary(
                conn,
                workbook_id=workbook_id,
                workbook_path=normalized_path,
                synced_at=synced_at,
            )

    def mirror_audit_event(
        self,
        *,
        event_id: str,
        timestamp: str,
        workbook_path: str,
        action: str,
        summary: str,
        backup_path: str = "",
        metadata: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            return

        effective_timestamp = _stringify(timestamp) or _utc_timestamp()
        with self._connect() as conn:
            workbook_id = self._upsert_workbook(conn, normalized_path, effective_timestamp)
            conn.execute(
                """
                INSERT INTO audit_events (
                    event_id,
                    workbook_id,
                    workbook_path,
                    timestamp,
                    action,
                    summary,
                    backup_path,
                    metadata_json,
                    before_json,
                    after_json,
                    mirrored_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING
                """,
                (
                    _stringify(event_id),
                    workbook_id,
                    normalized_path,
                    effective_timestamp,
                    _stringify(action),
                    _stringify(summary),
                    os.path.abspath(backup_path) if backup_path else "",
                    json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True),
                    json.dumps(before, ensure_ascii=False, sort_keys=True) if before is not None else None,
                    json.dumps(after, ensure_ascii=False, sort_keys=True) if after is not None else None,
                    _utc_timestamp(),
                ),
            )

    def list_audit_event_payloads_for_workbook(
        self,
        workbook_path: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            return []

        with self._connect() as conn:
            workbook_id = self._workbook_id_for_path(conn, normalized_path)
            if workbook_id is None:
                return []

            rows = conn.execute(
                """
                SELECT
                    event_id,
                    timestamp,
                    workbook_path,
                    action,
                    summary,
                    backup_path,
                    metadata_json,
                    before_json,
                    after_json
                FROM audit_events
                WHERE workbook_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (workbook_id, max(int(limit), 0)),
            ).fetchall()

        payloads: list[dict[str, Any]] = []
        for row in rows:
            payloads.append(
                {
                    "event_id": str(row["event_id"] or ""),
                    "timestamp": str(row["timestamp"] or ""),
                    "workbook_path": str(row["workbook_path"] or ""),
                    "session_path": str(row["workbook_path"] or ""),
                    "action": str(row["action"] or ""),
                    "summary": str(row["summary"] or ""),
                    "backup_path": str(row["backup_path"] or ""),
                    "metadata": self._decode_json_object(row["metadata_json"]),
                    "before": self._decode_json_value(row["before_json"]),
                    "after": self._decode_json_value(row["after_json"]),
                }
            )
        return payloads

    def get_workbook_snapshot_summary(self, workbook_path: str) -> WorkbookSnapshotSummary:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            return WorkbookSnapshotSummary("", "", 0, 0, 0)

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, last_synced_at, record_count, plantio_count, source_mtime_ns, source_size
                FROM workbooks
                WHERE workbook_path = ?
                """,
                (normalized_path,),
            ).fetchone()
            if row is None:
                return WorkbookSnapshotSummary(normalized_path, "", 0, 0, 0)

            workbook_id = int(row["id"])
            return WorkbookSnapshotSummary(
                workbook_path=normalized_path,
                synced_at=_stringify(row["last_synced_at"]),
                record_count=int(row["record_count"] or 0),
                plantio_count=int(row["plantio_count"] or 0),
                audit_event_count=self._count_audit_events(conn, workbook_id),
                source_mtime_ns=int(row["source_mtime_ns"] or 0),
                source_size=int(row["source_size"] or 0),
            )

    def list_records_for_workbook(self, workbook_path: str) -> list[Compensacao]:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            return []

        with self._connect() as conn:
            workbook_id = self._workbook_id_for_path(conn, normalized_path)
            if workbook_id is None:
                return []
            record_rows = self._fetch_record_rows(conn, workbook_id=workbook_id)
            return self._materialize_records(conn, record_rows)

    def find_record_by_uid_for_workbook(self, workbook_path: str, uid: str) -> Compensacao | None:
        normalized_path = _normalize_path(workbook_path)
        normalized_uid = _stringify(uid)
        if not normalized_path or not normalized_uid:
            return None

        with self._connect() as conn:
            workbook_id = self._workbook_id_for_path(conn, normalized_path)
            if workbook_id is None:
                return None
            row = conn.execute(
                """
                SELECT *
                FROM records
                WHERE workbook_id = ? AND uid = ?
                LIMIT 1
                """,
                (workbook_id, normalized_uid),
            ).fetchone()
            if row is None:
                return None
            records = self._materialize_records(conn, [row])
            return records[0] if records else None

    def find_record_by_excel_row_for_workbook(self, workbook_path: str, excel_row: int) -> Compensacao | None:
        normalized_path = _normalize_path(workbook_path)
        normalized_row = int(excel_row or 0)
        if not normalized_path or normalized_row <= 0:
            return None

        with self._connect() as conn:
            workbook_id = self._workbook_id_for_path(conn, normalized_path)
            if workbook_id is None:
                return None
            row = conn.execute(
                """
                SELECT *
                FROM records
                WHERE workbook_id = ? AND excel_row = ?
                LIMIT 1
                """,
                (workbook_id, normalized_row),
            ).fetchone()
            if row is None:
                return None
            records = self._materialize_records(conn, [row])
            return records[0] if records else None

    def find_duplicate_av_tec_for_workbook(
        self,
        workbook_path: str,
        *,
        av_tec: str,
        current_uid: str = "",
    ) -> int | None:
        normalized_path = _normalize_path(workbook_path)
        target_av_tec = _stringify(av_tec).upper()
        normalized_uid = _stringify(current_uid)
        if not normalized_path or not target_av_tec:
            return None

        with self._connect() as conn:
            workbook_id = self._workbook_id_for_path(conn, normalized_path)
            if workbook_id is None:
                return None
            row = conn.execute(
                """
                SELECT excel_row
                FROM records
                WHERE workbook_id = ?
                  AND UPPER(TRIM(av_tec)) = ?
                  AND (? = '' OR uid != ?)
                ORDER BY excel_row ASC
                LIMIT 1
                """,
                (workbook_id, target_av_tec, normalized_uid, normalized_uid),
            ).fetchone()
            if row is None:
                return None
            duplicate_row = int(row["excel_row"] or 0)
            return duplicate_row if duplicate_row > 0 else None

    def query_filter_facets_for_workbook(self, workbook_path: str) -> WorkbookFilterFacets:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            return WorkbookFilterFacets("", "", 0)

        snapshot = self.get_workbook_snapshot_summary(normalized_path)
        with self._connect() as conn:
            workbook_id = self._workbook_id_for_path(conn, normalized_path)
            if workbook_id is None:
                return WorkbookFilterFacets(
                    workbook_path=normalized_path,
                    synced_at=str(snapshot.synced_at or ""),
                    record_count=int(snapshot.record_count or 0),
                )

            micro_rows = conn.execute(
                """
                SELECT DISTINCT TRIM(microbacia) AS microbacia
                FROM records
                WHERE workbook_id = ?
                  AND TRIM(COALESCE(microbacia, '')) != ''
                ORDER BY microbacia_key ASC, microbacia ASC
                """,
                (workbook_id,),
            ).fetchall()
            year_rows = conn.execute(
                """
                SELECT DISTINCT TRIM(oficio_year) AS oficio_year
                FROM records
                WHERE workbook_id = ?
                  AND TRIM(COALESCE(oficio_year, '')) != ''
                ORDER BY oficio_year DESC
                """,
                (workbook_id,),
            ).fetchall()

        return WorkbookFilterFacets(
            workbook_path=normalized_path,
            synced_at=str(snapshot.synced_at or ""),
            record_count=int(snapshot.record_count or 0),
            microbacias=tuple(str(row["microbacia"] or "") for row in micro_rows),
            years=tuple(str(row["oficio_year"] or "") for row in year_rows),
        )

    def query_records_for_workbook(
        self,
        workbook_path: str,
        *,
        search_text: str = "",
        status: str = "Todos",
        selected_micros: Sequence[str] = (),
        selected_eletronicos: Sequence[str] = (),
        micro_all_selected: bool = True,
        eletronico_all_selected: bool = True,
        selected_year: str = "Todos",
    ) -> list[Compensacao]:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            return []

        with self._connect() as conn:
            workbook_id = self._workbook_id_for_path(conn, normalized_path)
            if workbook_id is None:
                return []

            where_clause, params = self._build_filtered_record_where_clause(
                workbook_id=workbook_id,
                search_text=search_text,
                status=status,
                selected_micros=selected_micros,
                selected_eletronicos=selected_eletronicos,
                micro_all_selected=micro_all_selected,
                eletronico_all_selected=eletronico_all_selected,
                selected_year=selected_year,
            )
            if where_clause is None:
                return []
            record_rows = self._fetch_record_rows(
                conn,
                workbook_id=workbook_id,
                where_clause=where_clause,
                params=params,
            )
            return self._materialize_records(conn, record_rows)

    def query_metrics_for_workbook(
        self,
        workbook_path: str,
        *,
        search_text: str = "",
        status: str = "Todos",
        selected_micros: Sequence[str] = (),
        selected_eletronicos: Sequence[str] = (),
        micro_all_selected: bool = True,
        eletronico_all_selected: bool = True,
        selected_year: str = "Todos",
    ) -> dict[str, object]:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            return self._empty_metrics()

        with self._connect() as conn:
            workbook_id = self._workbook_id_for_path(conn, normalized_path)
            if workbook_id is None:
                return self._empty_metrics()

            where_clause, params = self._build_filtered_record_where_clause(
                workbook_id=workbook_id,
                search_text=search_text,
                status=status,
                selected_micros=selected_micros,
                selected_eletronicos=selected_eletronicos,
                micro_all_selected=micro_all_selected,
                eletronico_all_selected=eletronico_all_selected,
                selected_year=selected_year,
            )
            if where_clause is None:
                return self._empty_metrics()

            value_expr = "CAST(REPLACE(TRIM(COALESCE(compensacao, '0')), ',', '.') AS REAL)"
            counts_row = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM({value_expr}), 0.0) AS total_geral,
                    COUNT(*) AS count_total,
                    COALESCE(SUM(CASE WHEN UPPER(TRIM(compensado)) = 'SIM' THEN {value_expr} ELSE 0.0 END), 0.0) AS total_compensado,
                    COALESCE(SUM(CASE WHEN UPPER(TRIM(compensado)) = 'SIM' THEN 0.0 ELSE {value_expr} END), 0.0) AS total_pendente,
                    SUM(CASE WHEN UPPER(TRIM(compensado)) = 'SIM' THEN 1 ELSE 0 END) AS count_comp,
                    SUM(CASE WHEN UPPER(TRIM(compensado)) = 'SIM' THEN 0 ELSE 1 END) AS count_pend
                FROM records
                WHERE {where_clause}
                """,
                params,
            ).fetchone()
            pend_micro_rows = conn.execute(
                f"""
                SELECT
                    CASE
                        WHEN TRIM(COALESCE(microbacia, '')) = '' THEN '(Sem microbacia)'
                        ELSE TRIM(microbacia)
                    END AS label,
                    COALESCE(SUM({value_expr}), 0.0) AS total
                FROM records
                WHERE {where_clause} AND UPPER(TRIM(compensado)) != 'SIM'
                GROUP BY label
                ORDER BY total DESC, label ASC
                """,
                params,
            ).fetchall()
            pend_tipo_rows = conn.execute(
                f"""
                SELECT
                    CASE
                        WHEN TRIM(COALESCE(tipo_key, '')) = '' THEN 'NULO'
                        ELSE TRIM(tipo_key)
                    END AS tipo_key_value,
                    COALESCE(SUM({value_expr}), 0.0) AS total
                FROM records
                WHERE {where_clause} AND UPPER(TRIM(compensado)) != 'SIM'
                GROUP BY tipo_key_value
                ORDER BY total DESC, tipo_key_value ASC
                """,
                params,
            ).fetchall()

        return {
            "total_geral": float((counts_row["total_geral"] if counts_row is not None else 0.0) or 0.0),
            "total_pendente": float((counts_row["total_pendente"] if counts_row is not None else 0.0) or 0.0),
            "total_compensado": float((counts_row["total_compensado"] if counts_row is not None else 0.0) or 0.0),
            "count_total": int((counts_row["count_total"] if counts_row is not None else 0) or 0),
            "count_comp": int((counts_row["count_comp"] if counts_row is not None else 0) or 0),
            "count_pend": int((counts_row["count_pend"] if counts_row is not None else 0) or 0),
            "pend_micro_sorted": [
                (str(row["label"] or ""), float(row["total"] or 0.0))
                for row in pend_micro_rows
            ],
            "pend_ele_sorted": [
                (display_tipo_value(str(row["tipo_key_value"] or "")), float(row["total"] or 0.0))
                for row in pend_tipo_rows
            ],
        }

    def build_workbook_diagnostics(
        self,
        workbook_path: str,
        *,
        top_microbacias_limit: int = 10,
        recent_audit_limit: int = 10,
    ) -> WorkbookMirrorDiagnostics:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            return WorkbookMirrorDiagnostics(
                workbook_path="",
                db_path=str(self.db_path),
                synced_at="",
                record_count=0,
                plantio_count=0,
                audit_event_count=0,
                compensados_count=0,
                pendentes_count=0,
            )

        snapshot = self.get_workbook_snapshot_summary(normalized_path)
        with self._connect() as conn:
            workbook_id = self._workbook_id_for_path(conn, normalized_path)
            if workbook_id is None:
                return WorkbookMirrorDiagnostics(
                    workbook_path=normalized_path,
                    db_path=str(self.db_path),
                    synced_at="",
                    record_count=0,
                    plantio_count=0,
                    audit_event_count=0,
                    compensados_count=0,
                    pendentes_count=0,
                )

            counts_row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN UPPER(TRIM(compensado)) = 'SIM' THEN 1 ELSE 0 END) AS compensados_count,
                    SUM(CASE WHEN UPPER(TRIM(compensado)) = 'SIM' THEN 0 ELSE 1 END) AS pendentes_count
                FROM records
                WHERE workbook_id = ?
                """,
                (workbook_id,),
            ).fetchone()
            microbacias_rows = conn.execute(
                """
                SELECT
                    CASE
                        WHEN TRIM(COALESCE(microbacia, '')) = '' THEN '(sem microbacia)'
                        ELSE TRIM(microbacia)
                    END AS microbacia_label,
                    COUNT(*) AS total
                FROM records
                WHERE workbook_id = ?
                GROUP BY microbacia_label
                ORDER BY total DESC, microbacia_label ASC
                LIMIT ?
                """,
                (workbook_id, max(int(top_microbacias_limit), 0)),
            ).fetchall()
            recent_audit_rows = conn.execute(
                """
                SELECT timestamp, action, summary
                FROM audit_events
                WHERE workbook_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (workbook_id, max(int(recent_audit_limit), 0)),
            ).fetchall()

        top_microbacias = tuple(
            (str(row["microbacia_label"] or ""), int(row["total"] or 0))
            for row in microbacias_rows
        )
        recent_audit_events = tuple(
            {
                "timestamp": str(row["timestamp"] or ""),
                "action": str(row["action"] or ""),
                "summary": str(row["summary"] or ""),
            }
            for row in recent_audit_rows
        )
        return WorkbookMirrorDiagnostics(
            workbook_path=snapshot.workbook_path or normalized_path,
            db_path=str(self.db_path),
            synced_at=snapshot.synced_at,
            record_count=snapshot.record_count,
            plantio_count=snapshot.plantio_count,
            audit_event_count=snapshot.audit_event_count,
            compensados_count=int((counts_row["compensados_count"] if counts_row is not None else 0) or 0),
            pendentes_count=int((counts_row["pendentes_count"] if counts_row is not None else 0) or 0),
            top_microbacias=top_microbacias,
            recent_audit_events=recent_audit_events,
        )

    def build_workbook_record_overview(
        self,
        workbook_path: str,
        *,
        top_microbacias_limit: int = 5,
        sample_limit: int = 5,
    ) -> WorkbookRecordOverview:
        normalized_path = _normalize_path(workbook_path)
        if not normalized_path:
            return WorkbookRecordOverview(
                workbook_path="",
                synced_at="",
                total_records=0,
                compensados_count=0,
                pendentes_count=0,
                records_with_plantios_count=0,
                records_without_microbacia_count=0,
                records_without_coordinates_count=0,
            )

        snapshot = self.get_workbook_snapshot_summary(normalized_path)
        with self._connect() as conn:
            workbook_id = self._workbook_id_for_path(conn, normalized_path)
            if workbook_id is None:
                return WorkbookRecordOverview(
                    workbook_path=normalized_path,
                    synced_at="",
                    total_records=0,
                    compensados_count=0,
                    pendentes_count=0,
                    records_with_plantios_count=0,
                    records_without_microbacia_count=0,
                    records_without_coordinates_count=0,
                )

            counts_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_records,
                    SUM(CASE WHEN UPPER(TRIM(compensado)) = 'SIM' THEN 1 ELSE 0 END) AS compensados_count,
                    SUM(CASE WHEN UPPER(TRIM(compensado)) = 'SIM' THEN 0 ELSE 1 END) AS pendentes_count,
                    SUM(CASE WHEN TRIM(COALESCE(microbacia, '')) = '' THEN 1 ELSE 0 END) AS without_microbacia_count,
                    SUM(
                        CASE
                            WHEN TRIM(COALESCE(latitude, '')) = '' OR TRIM(COALESCE(longitude, '')) = ''
                            THEN 1
                            ELSE 0
                        END
                    ) AS without_coordinates_count
                FROM records
                WHERE workbook_id = ?
                """,
                (workbook_id,),
            ).fetchone()
            records_with_plantios_row = conn.execute(
                """
                SELECT COUNT(DISTINCT records.id) AS total
                FROM records
                JOIN plantios ON plantios.record_id = records.id
                WHERE records.workbook_id = ?
                """,
                (workbook_id,),
            ).fetchone()
            microbacias_rows = conn.execute(
                """
                SELECT
                    CASE
                        WHEN TRIM(COALESCE(microbacia, '')) = '' THEN '(sem microbacia)'
                        ELSE TRIM(microbacia)
                    END AS microbacia_label,
                    COUNT(*) AS total
                FROM records
                WHERE workbook_id = ?
                GROUP BY microbacia_label
                ORDER BY total DESC, microbacia_label ASC
                LIMIT ?
                """,
                (workbook_id, max(int(top_microbacias_limit), 0)),
            ).fetchall()
            sample_rows = conn.execute(
                """
                SELECT
                    records.excel_row,
                    records.uid,
                    records.av_tec,
                    CASE
                        WHEN TRIM(COALESCE(records.microbacia, '')) = '' THEN '(sem microbacia)'
                        ELSE TRIM(records.microbacia)
                    END AS microbacia_label,
                    TRIM(COALESCE(records.compensado, '')) AS compensado_value,
                    COUNT(plantios.id) AS plantio_count
                FROM records
                LEFT JOIN plantios ON plantios.record_id = records.id
                WHERE records.workbook_id = ?
                GROUP BY records.id
                ORDER BY records.excel_row ASC
                LIMIT ?
                """,
                (workbook_id, max(int(sample_limit), 0)),
            ).fetchall()

        top_microbacias = tuple(
            (str(row["microbacia_label"] or ""), int(row["total"] or 0))
            for row in microbacias_rows
        )
        sample_records = tuple(
            MirroredRecordSample(
                excel_row=int(row["excel_row"] or 0),
                uid=str(row["uid"] or ""),
                av_tec=str(row["av_tec"] or ""),
                microbacia=str(row["microbacia_label"] or ""),
                compensado=str(row["compensado_value"] or ""),
                plantio_count=int(row["plantio_count"] or 0),
            )
            for row in sample_rows
        )
        return WorkbookRecordOverview(
            workbook_path=snapshot.workbook_path or normalized_path,
            synced_at=snapshot.synced_at,
            total_records=int((counts_row["total_records"] if counts_row is not None else 0) or 0),
            compensados_count=int((counts_row["compensados_count"] if counts_row is not None else 0) or 0),
            pendentes_count=int((counts_row["pendentes_count"] if counts_row is not None else 0) or 0),
            records_with_plantios_count=int(
                (records_with_plantios_row["total"] if records_with_plantios_row is not None else 0) or 0
            ),
            records_without_microbacia_count=int(
                (counts_row["without_microbacia_count"] if counts_row is not None else 0) or 0
            ),
            records_without_coordinates_count=int(
                (counts_row["without_coordinates_count"] if counts_row is not None else 0) or 0
            ),
            top_microbacias=top_microbacias,
            sample_records=sample_records,
        )

    def sync_session_snapshot(
        self,
        session_path: str,
        records: Sequence[Compensacao],
    ) -> SessionSnapshotSummary:
        return self.sync_workbook_snapshot(session_path, records)

    def sync_local_workspace_snapshot(
        self,
        workspace_path: str,
        records: Sequence[Compensacao],
    ) -> LocalWorkspaceSnapshotSummary:
        return self.sync_workbook_snapshot(workspace_path, records)

    def append_record_to_session(
        self,
        session_path: str,
        record: Compensacao,
    ) -> SessionSnapshotSummary:
        return self.append_record_to_workbook(session_path, record)

    def append_record_to_local_workspace(
        self,
        workspace_path: str,
        record: Compensacao,
    ) -> LocalWorkspaceSnapshotSummary:
        return self.append_record_to_workbook(workspace_path, record)

    def append_records_to_session(
        self,
        session_path: str,
        records: Sequence[Compensacao],
    ) -> SessionSnapshotSummary:
        return self.append_records_to_workbook(session_path, records)

    def append_records_to_local_workspace(
        self,
        workspace_path: str,
        records: Sequence[Compensacao],
    ) -> LocalWorkspaceSnapshotSummary:
        return self.append_records_to_workbook(workspace_path, records)

    def update_record_in_session(
        self,
        session_path: str,
        record: Compensacao,
    ) -> SessionSnapshotSummary:
        return self.update_record_in_workbook(session_path, record)

    def update_record_in_local_workspace(
        self,
        workspace_path: str,
        record: Compensacao,
    ) -> LocalWorkspaceSnapshotSummary:
        return self.update_record_in_workbook(workspace_path, record)

    def delete_record_from_session(
        self,
        session_path: str,
        record: Compensacao,
    ) -> SessionSnapshotSummary:
        return self.delete_record_from_workbook(session_path, record)

    def delete_record_from_local_workspace(
        self,
        workspace_path: str,
        record: Compensacao,
    ) -> LocalWorkspaceSnapshotSummary:
        return self.delete_record_from_workbook(workspace_path, record)

    def list_audit_event_payloads_for_session(
        self,
        session_path: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.list_audit_event_payloads_for_workbook(session_path, limit=limit)

    def list_audit_event_payloads_for_local_workspace(
        self,
        workspace_path: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.list_audit_event_payloads_for_workbook(workspace_path, limit=limit)

    def get_session_snapshot_summary(self, session_path: str) -> SessionSnapshotSummary:
        return self.get_workbook_snapshot_summary(session_path)

    def get_session_display_name(self, session_path: str) -> str:
        entry = self.get_session_entry(session_path)
        if entry is not None:
            return entry.display_name
        return self._display_name_for_path(session_path)

    def get_local_workspace_snapshot_summary(self, workspace_path: str) -> LocalWorkspaceSnapshotSummary:
        return self.get_workbook_snapshot_summary(workspace_path)

    def get_local_workspace_display_name(self, workspace_path: str) -> str:
        entry = self.get_local_workspace(workspace_path)
        if entry is not None:
            return entry.display_name
        return self._display_name_for_path(workspace_path)

    def list_records_for_session(self, session_path: str) -> list[Compensacao]:
        return self.list_records_for_workbook(session_path)

    def list_records_for_local_workspace(self, workspace_path: str) -> list[Compensacao]:
        return self.list_records_for_workbook(workspace_path)

    def find_record_by_uid_for_session(self, session_path: str, uid: str) -> Compensacao | None:
        return self.find_record_by_uid_for_workbook(session_path, uid)

    def find_record_by_uid_for_local_workspace(self, workspace_path: str, uid: str) -> Compensacao | None:
        return self.find_record_by_uid_for_workbook(workspace_path, uid)

    def find_record_by_excel_row_for_session(self, session_path: str, excel_row: int) -> Compensacao | None:
        return self.find_record_by_excel_row_for_workbook(session_path, excel_row)

    def find_record_by_excel_row_for_local_workspace(
        self,
        workspace_path: str,
        excel_row: int,
    ) -> Compensacao | None:
        return self.find_record_by_excel_row_for_workbook(workspace_path, excel_row)

    def find_duplicate_av_tec_for_session(
        self,
        session_path: str,
        *,
        av_tec: str,
        current_uid: str = "",
    ) -> int | None:
        return self.find_duplicate_av_tec_for_workbook(
            session_path,
            av_tec=av_tec,
            current_uid=current_uid,
        )

    def find_duplicate_av_tec_for_local_workspace(
        self,
        workspace_path: str,
        *,
        av_tec: str,
        current_uid: str = "",
    ) -> int | None:
        return self.find_duplicate_av_tec_for_workbook(
            workspace_path,
            av_tec=av_tec,
            current_uid=current_uid,
        )

    def query_filter_facets_for_session(self, session_path: str) -> SessionFilterFacets:
        return self.query_filter_facets_for_workbook(session_path)

    def query_filter_facets_for_local_workspace(self, workspace_path: str) -> LocalWorkspaceFilterFacets:
        return self.query_filter_facets_for_workbook(workspace_path)

    def query_records_for_session(
        self,
        session_path: str,
        *,
        search_text: str = "",
        status: str = "Todos",
        selected_micros: Sequence[str] = (),
        selected_eletronicos: Sequence[str] = (),
        micro_all_selected: bool = True,
        eletronico_all_selected: bool = True,
        selected_year: str = "Todos",
    ) -> list[Compensacao]:
        return self.query_records_for_workbook(
            session_path,
            search_text=search_text,
            status=status,
            selected_micros=selected_micros,
            selected_eletronicos=selected_eletronicos,
            micro_all_selected=micro_all_selected,
            eletronico_all_selected=eletronico_all_selected,
            selected_year=selected_year,
        )

    def query_records_for_local_workspace(
        self,
        workspace_path: str,
        *,
        search_text: str = "",
        status: str = "Todos",
        selected_micros: Sequence[str] = (),
        selected_eletronicos: Sequence[str] = (),
        micro_all_selected: bool = True,
        eletronico_all_selected: bool = True,
        selected_year: str = "Todos",
    ) -> list[Compensacao]:
        return self.query_records_for_workbook(
            workspace_path,
            search_text=search_text,
            status=status,
            selected_micros=selected_micros,
            selected_eletronicos=selected_eletronicos,
            micro_all_selected=micro_all_selected,
            eletronico_all_selected=eletronico_all_selected,
            selected_year=selected_year,
        )

    def query_metrics_for_session(
        self,
        session_path: str,
        *,
        search_text: str = "",
        status: str = "Todos",
        selected_micros: Sequence[str] = (),
        selected_eletronicos: Sequence[str] = (),
        micro_all_selected: bool = True,
        eletronico_all_selected: bool = True,
        selected_year: str = "Todos",
    ) -> dict[str, object]:
        return self.query_metrics_for_workbook(
            session_path,
            search_text=search_text,
            status=status,
            selected_micros=selected_micros,
            selected_eletronicos=selected_eletronicos,
            micro_all_selected=micro_all_selected,
            eletronico_all_selected=eletronico_all_selected,
            selected_year=selected_year,
        )

    def query_metrics_for_local_workspace(
        self,
        workspace_path: str,
        *,
        search_text: str = "",
        status: str = "Todos",
        selected_micros: Sequence[str] = (),
        selected_eletronicos: Sequence[str] = (),
        micro_all_selected: bool = True,
        eletronico_all_selected: bool = True,
        selected_year: str = "Todos",
    ) -> dict[str, object]:
        return self.query_metrics_for_workbook(
            workspace_path,
            search_text=search_text,
            status=status,
            selected_micros=selected_micros,
            selected_eletronicos=selected_eletronicos,
            micro_all_selected=micro_all_selected,
            eletronico_all_selected=eletronico_all_selected,
            selected_year=selected_year,
        )

    def build_session_diagnostics(
        self,
        session_path: str,
        *,
        top_microbacias_limit: int = 10,
        recent_audit_limit: int = 10,
    ) -> SessionMirrorDiagnostics:
        return self.build_workbook_diagnostics(
            session_path,
            top_microbacias_limit=top_microbacias_limit,
            recent_audit_limit=recent_audit_limit,
        )

    def build_local_workspace_diagnostics(
        self,
        workspace_path: str,
        *,
        top_microbacias_limit: int = 10,
        recent_audit_limit: int = 10,
    ) -> LocalWorkspaceDiagnostics:
        return self.build_workbook_diagnostics(
            workspace_path,
            top_microbacias_limit=top_microbacias_limit,
            recent_audit_limit=recent_audit_limit,
        )

    def build_session_record_overview(
        self,
        session_path: str,
        *,
        top_microbacias_limit: int = 5,
        sample_limit: int = 5,
    ) -> SessionRecordOverview:
        return self.build_workbook_record_overview(
            session_path,
            top_microbacias_limit=top_microbacias_limit,
            sample_limit=sample_limit,
        )

    def build_local_workspace_record_overview(
        self,
        workspace_path: str,
        *,
        top_microbacias_limit: int = 5,
        sample_limit: int = 5,
    ) -> LocalWorkspaceOverview:
        return self.build_workbook_record_overview(
            workspace_path,
            top_microbacias_limit=top_microbacias_limit,
            sample_limit=sample_limit,
        )

    def _build_filtered_record_where_clause(
        self,
        *,
        workbook_id: int,
        search_text: str = "",
        status: str = "Todos",
        selected_micros: Sequence[str] = (),
        selected_eletronicos: Sequence[str] = (),
        micro_all_selected: bool = True,
        eletronico_all_selected: bool = True,
        selected_year: str = "Todos",
    ) -> tuple[str | None, tuple[object, ...]]:
        clauses = ["workbook_id = ?"]
        params: list[object] = [workbook_id]

        search_query = _stringify(search_text)
        if search_query:
            clauses.append("search_blob_norm LIKE ?")
            params.append(f"%{remove_accents(search_query).lower()}%")

        normalized_status = _stringify(status)
        if normalized_status == "Compensados":
            clauses.append("UPPER(TRIM(compensado)) = 'SIM'")
        elif normalized_status == "Pendentes":
            clauses.append("UPPER(TRIM(compensado)) != 'SIM'")

        normalized_year = _stringify(selected_year)
        if normalized_year and normalized_year != "Todos":
            clauses.append("oficio_year = ?")
            params.append(normalized_year)

        if not micro_all_selected:
            micro_keys = sorted({_microbacia_key(item) for item in selected_micros if _stringify(item)})
            if not micro_keys:
                return None, ()
            placeholders = ",".join("?" for _ in micro_keys)
            clauses.append(f"microbacia_key IN ({placeholders})")
            params.extend(micro_keys)

        if not eletronico_all_selected:
            tipo_keys = sorted({normalize_tipo_key(item) for item in selected_eletronicos if _stringify(item)})
            if not tipo_keys:
                return None, ()
            placeholders = ",".join("?" for _ in tipo_keys)
            clauses.append(f"tipo_key IN ({placeholders})")
            params.extend(tipo_keys)

        return " AND ".join(clauses), tuple(params)

    @staticmethod
    def _empty_metrics() -> dict[str, object]:
        return {
            "total_geral": 0.0,
            "total_pendente": 0.0,
            "total_compensado": 0.0,
            "count_total": 0,
            "count_comp": 0,
            "count_pend": 0,
            "pend_micro_sorted": [],
            "pend_ele_sorted": [],
        }

    def _fetch_record_rows(
        self,
        conn: sqlite3.Connection,
        *,
        workbook_id: int,
        where_clause: str = "workbook_id = ?",
        params: Sequence[object] = (),
    ) -> list[sqlite3.Row]:
        effective_params = tuple(params) if params else (workbook_id,)
        return list(
            conn.execute(
                f"""
                SELECT
                    id,
                    excel_row,
                    uid,
                    oficio_processo,
                    eletronico,
                    caixa,
                    av_tec,
                    compensacao,
                    endereco,
                    microbacia,
                    compensado,
                    endereco_plantio,
                    latitude_plantio,
                    longitude_plantio,
                    latitude,
                    longitude,
                    updated_at
                FROM records
                WHERE {where_clause}
                ORDER BY excel_row ASC
                """,
                effective_params,
            ).fetchall()
        )

    def _materialize_records(
        self,
        conn: sqlite3.Connection,
        record_rows: Sequence[sqlite3.Row],
    ) -> list[Compensacao]:
        if not record_rows:
            return []

        record_ids = [int(row["id"]) for row in record_rows]
        placeholders = ",".join("?" for _ in record_ids)
        plantio_rows = conn.execute(
            f"""
            SELECT
                record_id,
                sequence,
                endereco,
                qtd_mudas,
                latitude,
                longitude
            FROM plantios
            WHERE record_id IN ({placeholders})
            ORDER BY record_id ASC, sequence ASC
            """,
            record_ids,
        ).fetchall()

        plantios_by_record: dict[int, list[PlantioItem]] = {}
        for row in plantio_rows:
            record_id = int(row["record_id"] or 0)
            plantios_by_record.setdefault(record_id, []).append(
                PlantioItem(
                    sequence=int(row["sequence"] or 0),
                    endereco=_stringify(row["endereco"]),
                    qtd_mudas=_stringify(row["qtd_mudas"]),
                    latitude=_stringify(row["latitude"]),
                    longitude=_stringify(row["longitude"]),
                )
            )

        return [
            Compensacao(
                excel_row=int(row["excel_row"] or 0),
                uid=_stringify(row["uid"]),
                oficio_processo=_stringify(row["oficio_processo"]),
                eletronico=_stringify(row["eletronico"]),
                caixa=_stringify(row["caixa"]),
                av_tec=_stringify(row["av_tec"]),
                compensacao=_stringify(row["compensacao"]),
                endereco=_stringify(row["endereco"]),
                microbacia=_stringify(row["microbacia"]),
                compensado=_stringify(row["compensado"]),
                endereco_plantio=_stringify(row["endereco_plantio"]),
                latitude_plantio=_stringify(row["latitude_plantio"]),
                longitude_plantio=_stringify(row["longitude_plantio"]),
                latitude=_stringify(row["latitude"]),
                longitude=_stringify(row["longitude"]),
                updated_at=_stringify(row["updated_at"]) if "updated_at" in row.keys() else "",
                plantios=plantios_by_record.get(int(row["id"] or 0), []),
            )
            for row in record_rows
        ]

    @staticmethod
    def _record_insert_sql() -> str:
        return """
            INSERT INTO records (
                workbook_id,
                uid,
                excel_row,
                oficio_processo,
                oficio_year,
                eletronico,
                tipo_key,
                caixa,
                av_tec,
                compensacao,
                endereco,
                microbacia,
                microbacia_key,
                compensado,
                endereco_plantio,
                latitude_plantio,
                longitude_plantio,
                latitude,
                longitude,
                updated_at,
                search_blob_norm,
                synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

    def _record_insert_params(
        self,
        *,
        workbook_id: int,
        record: Compensacao,
        synced_at: str,
    ) -> tuple[object, ...]:
        return (
            workbook_id,
            _stringify(record.uid),
            int(record.excel_row),
            _stringify(record.oficio_processo),
            _stringify(extract_year(record.oficio_processo)),
            _stringify(record.eletronico),
            normalize_tipo_key(display_tipo_value(record.eletronico)),
            _stringify(record.caixa),
            _stringify(record.av_tec),
            _stringify(record.compensacao),
            _stringify(record.endereco),
            _stringify(record.microbacia),
            _microbacia_key(record.microbacia),
            _stringify(record.compensado),
            _stringify(record.endereco_plantio),
            _stringify(record.latitude_plantio),
            _stringify(record.longitude_plantio),
            _stringify(record.latitude),
            _stringify(record.longitude),
            _stringify(record.updated_at),
            build_search_blob(record),
            synced_at,
        )

    def _insert_record(
        self,
        conn: sqlite3.Connection,
        *,
        workbook_id: int,
        record: Compensacao,
        synced_at: str,
    ) -> int:
        cursor = conn.execute(
            self._record_insert_sql(),
            self._record_insert_params(
                workbook_id=workbook_id,
                record=record,
                synced_at=synced_at,
            ),
        )
        record_id = int(cursor.lastrowid or 0)
        if record_id <= 0:
            raise RuntimeError("Nao foi possivel persistir o registro no espelho SQLite.")
        self._replace_record_plantios(conn, record_id=record_id, record=record)
        return record_id

    def _replace_record_plantios(
        self,
        conn: sqlite3.Connection,
        *,
        record_id: int,
        record: Compensacao,
    ) -> int:
        conn.execute("DELETE FROM plantios WHERE record_id = ?", (record_id,))
        inserted = 0
        for plantio in record_plantio_items(record):
            conn.execute(
                """
                INSERT INTO plantios (
                    record_id,
                    sequence,
                    endereco,
                    qtd_mudas,
                    latitude,
                    longitude
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    int(plantio.sequence),
                    _stringify(plantio.endereco),
                    _stringify(plantio.qtd_mudas),
                    _stringify(plantio.latitude),
                    _stringify(plantio.longitude),
                ),
            )
            inserted += 1
        return inserted

    def _update_record(
        self,
        conn: sqlite3.Connection,
        *,
        record_id: int,
        record: Compensacao,
        synced_at: str,
    ) -> None:
        conn.execute(
            """
            UPDATE records
            SET
                uid = ?,
                excel_row = ?,
                oficio_processo = ?,
                oficio_year = ?,
                eletronico = ?,
                tipo_key = ?,
                caixa = ?,
                av_tec = ?,
                compensacao = ?,
                endereco = ?,
                microbacia = ?,
                microbacia_key = ?,
                compensado = ?,
                endereco_plantio = ?,
                latitude_plantio = ?,
                longitude_plantio = ?,
                latitude = ?,
                longitude = ?,
                updated_at = ?,
                search_blob_norm = ?,
                synced_at = ?
            WHERE id = ?
            """,
            (
                _stringify(record.uid),
                int(record.excel_row),
                _stringify(record.oficio_processo),
                _stringify(extract_year(record.oficio_processo)),
                _stringify(record.eletronico),
                normalize_tipo_key(display_tipo_value(record.eletronico)),
                _stringify(record.caixa),
                _stringify(record.av_tec),
                _stringify(record.compensacao),
                _stringify(record.endereco),
                _stringify(record.microbacia),
                _microbacia_key(record.microbacia),
                _stringify(record.compensado),
                _stringify(record.endereco_plantio),
                _stringify(record.latitude_plantio),
                _stringify(record.longitude_plantio),
                _stringify(record.latitude),
                _stringify(record.longitude),
                _stringify(record.updated_at),
                build_search_blob(record),
                synced_at,
                record_id,
            ),
        )
        self._replace_record_plantios(conn, record_id=record_id, record=record)

    def _find_record_row_for_mutation(
        self,
        conn: sqlite3.Connection,
        *,
        workbook_id: int,
        record: Compensacao,
    ) -> sqlite3.Row | None:
        uid = _stringify(record.uid)
        if uid:
            row = conn.execute(
                """
                SELECT id, excel_row
                FROM records
                WHERE workbook_id = ? AND uid = ?
                """,
                (workbook_id, uid),
            ).fetchone()
            if row is not None:
                return row

        excel_row = int(record.excel_row or 0)
        if excel_row <= 0:
            return None
        return conn.execute(
            """
            SELECT id, excel_row
            FROM records
            WHERE workbook_id = ? AND excel_row = ?
            """,
            (workbook_id, excel_row),
        ).fetchone()

    def _refresh_workbook_summary(
        self,
        conn: sqlite3.Connection,
        *,
        workbook_id: int,
        workbook_path: str,
        synced_at: str,
        source_mtime_ns: int | None = None,
        source_size: int | None = None,
    ) -> WorkbookSnapshotSummary:
        counts_row = conn.execute(
            """
            SELECT
                COUNT(*) AS record_count,
                (
                    SELECT COUNT(*)
                    FROM plantios
                    JOIN records ON records.id = plantios.record_id
                    WHERE records.workbook_id = ?
                ) AS plantio_count
            FROM records
            WHERE workbook_id = ?
            """,
            (workbook_id, workbook_id),
        ).fetchone()
        record_count = int((counts_row["record_count"] if counts_row is not None else 0) or 0)
        plantio_count = int((counts_row["plantio_count"] if counts_row is not None else 0) or 0)
        if source_mtime_ns is None or source_size is None:
            source_mtime_ns, source_size = _read_workbook_file_identity(workbook_path)
        existing_row = conn.execute(
            "SELECT workbook_name FROM workbooks WHERE id = ?",
            (workbook_id,),
        ).fetchone()
        if _is_session_path(workbook_path):
            resolved_workbook_name = _stringify(existing_row["workbook_name"] if existing_row is not None else "")
            if not resolved_workbook_name:
                resolved_workbook_name = self._display_name_for_path(workbook_path)
        else:
            resolved_workbook_name = os.path.basename(workbook_path) or workbook_path
        conn.execute(
            """
            UPDATE workbooks
            SET
                workbook_name = ?,
                last_loaded_at = ?,
                last_synced_at = ?,
                record_count = ?,
                plantio_count = ?,
                source_mtime_ns = ?,
                source_size = ?
            WHERE id = ?
            """,
            (
                resolved_workbook_name,
                synced_at,
                synced_at,
                record_count,
                plantio_count,
                int(source_mtime_ns or 0),
                int(source_size or 0),
                workbook_id,
            ),
        )
        return WorkbookSnapshotSummary(
            workbook_path=workbook_path,
            synced_at=synced_at,
            record_count=record_count,
            plantio_count=plantio_count,
            audit_event_count=self._count_audit_events(conn, workbook_id),
            source_mtime_ns=int(source_mtime_ns or 0),
            source_size=int(source_size or 0),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _schema_version(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            return 0
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return 0

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workbooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workbook_path TEXT NOT NULL UNIQUE COLLATE NOCASE,
                workbook_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_loaded_at TEXT NOT NULL,
                last_synced_at TEXT NOT NULL,
                record_count INTEGER NOT NULL DEFAULT 0,
                plantio_count INTEGER NOT NULL DEFAULT 0,
                source_mtime_ns INTEGER NOT NULL DEFAULT 0,
                source_size INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workbook_id INTEGER NOT NULL,
                uid TEXT NOT NULL COLLATE NOCASE,
                excel_row INTEGER NOT NULL,
                oficio_processo TEXT NOT NULL,
                oficio_year TEXT NOT NULL DEFAULT '',
                eletronico TEXT NOT NULL,
                tipo_key TEXT NOT NULL DEFAULT '',
                caixa TEXT NOT NULL,
                av_tec TEXT NOT NULL COLLATE NOCASE,
                compensacao TEXT NOT NULL,
                endereco TEXT NOT NULL,
                microbacia TEXT NOT NULL,
                microbacia_key TEXT NOT NULL DEFAULT '',
                compensado TEXT NOT NULL,
                endereco_plantio TEXT NOT NULL DEFAULT '',
                latitude_plantio TEXT NOT NULL DEFAULT '',
                longitude_plantio TEXT NOT NULL DEFAULT '',
                latitude TEXT NOT NULL DEFAULT '',
                longitude TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                search_blob_norm TEXT NOT NULL DEFAULT '',
                synced_at TEXT NOT NULL,
                FOREIGN KEY (workbook_id) REFERENCES workbooks(id) ON DELETE CASCADE,
                CONSTRAINT uq_records_workbook_uid UNIQUE (workbook_id, uid),
                CONSTRAINT uq_records_workbook_row UNIQUE (workbook_id, excel_row)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS plantios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER NOT NULL,
                sequence INTEGER NOT NULL,
                endereco TEXT NOT NULL DEFAULT '',
                qtd_mudas TEXT NOT NULL DEFAULT '',
                latitude TEXT NOT NULL DEFAULT '',
                longitude TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE,
                CONSTRAINT uq_plantios_record_sequence UNIQUE (record_id, sequence)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
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
                mirrored_at TEXT NOT NULL,
                FOREIGN KEY (workbook_id) REFERENCES workbooks(id) ON DELETE SET NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_workbook_row ON records(workbook_id, excel_row)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_workbook_av_tec ON records(workbook_id, av_tec)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_workbook_year ON records(workbook_id, oficio_year)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_workbook_tipo_key ON records(workbook_id, tipo_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_workbook_micro_key ON records(workbook_id, microbacia_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plantios_record_sequence ON plantios(record_id, sequence)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_workbook_timestamp ON audit_events(workbook_id, timestamp DESC)")

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        logger.info("[SQLITE] Migrando espelho local do schema v1 para v2.")
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute("ALTER TABLE plantios RENAME TO plantios_v1")
            conn.execute("ALTER TABLE records RENAME TO records_v1")
            self._create_schema(conn)
            conn.execute(
                """
                INSERT INTO records (
                    id,
                    workbook_id,
                    uid,
                    excel_row,
                    oficio_processo,
                    eletronico,
                    caixa,
                    av_tec,
                    compensacao,
                    endereco,
                    microbacia,
                    compensado,
                    endereco_plantio,
                    latitude_plantio,
                    longitude_plantio,
                    latitude,
                    longitude,
                    synced_at
                )
                SELECT
                    id,
                    workbook_id,
                    uid,
                    excel_row,
                    oficio_processo,
                    eletronico,
                    caixa,
                    av_tec,
                    compensacao,
                    endereco,
                    microbacia,
                    compensado,
                    endereco_plantio,
                    latitude_plantio,
                    longitude_plantio,
                    latitude,
                    longitude,
                    synced_at
                FROM records_v1
                """
            )
            conn.execute(
                """
                INSERT INTO plantios (
                    id,
                    record_id,
                    sequence,
                    endereco,
                    qtd_mudas,
                    latitude,
                    longitude
                )
                SELECT
                    id,
                    record_id,
                    sequence,
                    endereco,
                    qtd_mudas,
                    latitude,
                    longitude
                FROM plantios_v1
                """
            )
            conn.execute("DROP TABLE plantios_v1")
            conn.execute("DROP TABLE records_v1")
            self._backfill_record_query_fields(conn)
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

    def _migrate_v2_to_v3(self, conn: sqlite3.Connection) -> None:
        logger.info("[SQLITE] Migrando espelho local do schema v2 para v3.")
        conn.execute("ALTER TABLE records ADD COLUMN oficio_year TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE records ADD COLUMN tipo_key TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE records ADD COLUMN microbacia_key TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE records ADD COLUMN search_blob_norm TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_workbook_year ON records(workbook_id, oficio_year)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_workbook_tipo_key ON records(workbook_id, tipo_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_workbook_micro_key ON records(workbook_id, microbacia_key)")
        self._backfill_record_query_fields(conn)

    def _migrate_v3_to_v4(self, conn: sqlite3.Connection) -> None:
        logger.info("[SQLITE] Migrando espelho local do schema v3 para v4.")
        conn.execute("ALTER TABLE workbooks ADD COLUMN source_mtime_ns INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE workbooks ADD COLUMN source_size INTEGER NOT NULL DEFAULT 0")
        workbook_rows = conn.execute("SELECT id, workbook_path FROM workbooks ORDER BY id ASC").fetchall()
        for workbook_row in workbook_rows:
            workbook_id = int(workbook_row["id"] or 0)
            workbook_path = _stringify(workbook_row["workbook_path"])
            if workbook_id <= 0 or not workbook_path:
                continue
            source_mtime_ns, source_size = _read_workbook_file_identity(workbook_path)
            conn.execute(
                """
                UPDATE workbooks
                SET source_mtime_ns = ?, source_size = ?
                WHERE id = ?
                """,
                (source_mtime_ns, source_size, workbook_id),
            )

    def _migrate_v4_to_v5(self, conn: sqlite3.Connection) -> None:
        logger.info("[SQLITE] Migrando espelho local do schema v4 para v5.")
        conn.execute("ALTER TABLE records ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _display_name_for_path(workbook_path: str) -> str:
        return _display_name_for_path_helper(workbook_path, session_scheme=SESSION_SCHEME)

    def _build_unique_session_path(self, conn: sqlite3.Connection, session_name: str) -> str:
        rows = conn.execute("SELECT workbook_path FROM workbooks").fetchall()
        existing_paths = [_stringify(row["workbook_path"]) for row in rows]
        return _build_unique_session_path_helper(
            session_name,
            existing_paths=existing_paths,
            session_scheme=SESSION_SCHEME,
        )

    @staticmethod
    def _row_to_named_session_entry(row: sqlite3.Row) -> NamedSessionEntry:
        return NamedSessionEntry(
            session_path=_stringify(row["workbook_path"]),
            display_name=_stringify(row["workbook_name"]),
            record_count=int(row["record_count"] or 0),
            created_at=_stringify(row["created_at"]),
            last_loaded_at=_stringify(row["last_loaded_at"]),
            last_synced_at=_stringify(row["last_synced_at"]),
        )

    def _backfill_record_query_fields(self, conn: sqlite3.Connection) -> None:
        workbook_rows = conn.execute("SELECT id FROM workbooks ORDER BY id ASC").fetchall()
        for workbook_row in workbook_rows:
            workbook_id = int(workbook_row["id"] or 0)
            if workbook_id <= 0:
                continue
            record_rows = conn.execute(
                """
                SELECT *
                FROM records
                WHERE workbook_id = ?
                ORDER BY excel_row ASC
                """,
                (workbook_id,),
            ).fetchall()
            for row in record_rows:
                record = self._materialize_records(conn, [row])[0]
                conn.execute(
                    """
                    UPDATE records
                    SET
                        oficio_year = ?,
                        tipo_key = ?,
                        microbacia_key = ?,
                        search_blob_norm = ?
                    WHERE id = ?
                    """,
                    (
                        _stringify(extract_year(record.oficio_processo)),
                        normalize_tipo_key(display_tipo_value(record.eletronico)),
                        _microbacia_key(record.microbacia),
                        build_search_blob(record),
                        int(row["id"] or 0),
                    ),
                )

    def _upsert_workbook(
        self,
        conn: sqlite3.Connection,
        workbook_path: str,
        timestamp: str,
        *,
        workbook_name: str | None = None,
    ) -> int:
        resolved_workbook_name = _stringify(workbook_name)
        if not resolved_workbook_name:
            existing_row = conn.execute(
                "SELECT workbook_name FROM workbooks WHERE workbook_path = ?",
                (workbook_path,),
            ).fetchone()
            if existing_row is not None and _is_session_path(workbook_path):
                resolved_workbook_name = _stringify(existing_row["workbook_name"])
        if not resolved_workbook_name:
            resolved_workbook_name = self._display_name_for_path(workbook_path)
        conn.execute(
            """
            INSERT INTO workbooks (
                workbook_path,
                workbook_name,
                created_at,
                last_loaded_at,
                last_synced_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(workbook_path) DO UPDATE SET
                workbook_name = excluded.workbook_name
            """,
            (workbook_path, resolved_workbook_name, timestamp, timestamp, timestamp),
        )
        row = conn.execute(
            "SELECT id FROM workbooks WHERE workbook_path = ?",
            (workbook_path,),
        ).fetchone()
        if row is None:
            raise LookupError("Nao foi possivel localizar a planilha espelhada no SQLite.")
        return int(row["id"])

    def _workbook_id_for_path(self, conn: sqlite3.Connection, workbook_path: str) -> int | None:
        row = conn.execute(
            "SELECT id FROM workbooks WHERE workbook_path = ?",
            (workbook_path,),
        ).fetchone()
        if row is None:
            return None
        return int(row["id"])

    def _count_audit_events(self, conn: sqlite3.Connection, workbook_id: int) -> int:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM audit_events WHERE workbook_id = ?",
            (workbook_id,),
        ).fetchone()
        return int(row["total"] if row is not None else 0)

    @staticmethod
    def _decode_json_object(raw_value: object) -> dict[str, Any]:
        return _decode_json_object_helper(raw_value)

    @staticmethod
    def _decode_json_value(raw_value: object) -> Any:
        return _decode_json_value_helper(raw_value)
