from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.tcra_records_service import (
    TcraFilterFacets,
    TcraRecordOverview,
    build_filter_facets,
    build_record_overview,
    build_search_blob,
    build_record_search_index,
    compute_metrics,
    filter_tcras,
    normalize_orgao_label,
    normalize_status_label,
)
from app.utils.app_paths import ensure_dir, resolve_data_path
from app.utils.logger import get_logger


logger = get_logger("Persistence.TCRA")

DEFAULT_DB_NAME = "compensacoes.db"
TCRA_ROW_COLUMNS = """
    uid,
    numero_processo,
    numero_tcra,
    local,
    endereco,
    bairro,
    orgao_acompanhamento,
    status,
    data_assinatura,
    prazo_final,
    periodicidade_relatorio_meses,
    data_ultimo_relatorio,
    data_proximo_relatorio,
    area_m2,
    numero_mudas_previsto,
    servicos_exigidos,
    responsavel_execucao,
    observacoes,
    mpsp_relacionado,
    inquerito_civil
"""
TCRA_DEFAULT_ORDER_BY = """
    CASE WHEN TRIM(numero_tcra) <> '' THEN 0 ELSE 1 END,
    numero_tcra COLLATE NOCASE ASC,
    numero_processo COLLATE NOCASE ASC,
    local COLLATE NOCASE ASC,
    uid ASC
"""


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stringify(value: object) -> str:
    return str(value or "").strip()


def _date_to_storage(value: date | None) -> str:
    return value.isoformat() if isinstance(value, date) else ""


def _date_from_storage(value: object) -> date | None:
    text = _stringify(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _float_from_storage(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_from_storage(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class TcraSqliteService:
    def __init__(self, *, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else resolve_data_path("state", DEFAULT_DB_NAME)
        ensure_dir(self.db_path.parent)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as conn:
            self._create_schema(conn)

    def list_tcras(self) -> list[Tcra]:
        with self._connect() as conn:
            tcra_rows = self._select_tcra_rows(conn)
            if not tcra_rows:
                return []

            eventos_by_uid = self._load_eventos_by_uid(conn, tcra_uids=[_stringify(row["uid"]) for row in tcra_rows])
            return [self._row_to_tcra(row, eventos_by_uid.get(_stringify(row["uid"]), ())) for row in tcra_rows]

    def get_tcra(self, uid: str) -> Tcra | None:
        return self.find_tcra_by_uid(uid)

    def get_tcras_by_uids(self, uids: Sequence[str]) -> list[Tcra]:
        normalized_uids = [_stringify(uid) for uid in uids if _stringify(uid)]
        if not normalized_uids:
            return []
        with self._connect() as conn:
            placeholders = ", ".join("?" for _ in normalized_uids)
            rows = self._select_tcra_rows(
                conn,
                where_clause=f"uid IN ({placeholders})",
                params=tuple(normalized_uids),
            )
            if not rows:
                return []
            eventos_by_uid = self._load_eventos_by_uid(conn, tcra_uids=normalized_uids)
            records_by_uid = {
                _stringify(row["uid"]): self._row_to_tcra(row, eventos_by_uid.get(_stringify(row["uid"]), ()))
                for row in rows
            }
        return [records_by_uid[uid] for uid in normalized_uids if uid in records_by_uid]

    def query_tcras(
        self,
        *,
        text: str = "",
        status: str = "Todos",
        selected_orgaos: Sequence[str] = (),
        selected_bairros: Sequence[str] = (),
        selected_year: str = "Todos",
        only_mpsp: bool = False,
        only_relatorio_pendente: bool = False,
        only_prazo_vencido: bool = False,
        today: date | None = None,
    ) -> list[Tcra]:
        records = self.list_tcras()
        return filter_tcras(
            records,
            text=text,
            status=status,
            selected_orgaos=selected_orgaos,
            selected_bairros=selected_bairros,
            selected_year=selected_year,
            only_mpsp=only_mpsp,
            only_relatorio_pendente=only_relatorio_pendente,
            only_prazo_vencido=only_prazo_vencido,
            search_index=build_record_search_index(records),
            today=today,
        )

    def query_filter_facets(self, *, today: date | None = None) -> TcraFilterFacets:
        return build_filter_facets(self.list_tcras(), today=today)

    def query_metrics(
        self,
        *,
        text: str = "",
        status: str = "Todos",
        selected_orgaos: Sequence[str] = (),
        selected_bairros: Sequence[str] = (),
        selected_year: str = "Todos",
        only_mpsp: bool = False,
        only_relatorio_pendente: bool = False,
        only_prazo_vencido: bool = False,
        today: date | None = None,
    ) -> dict[str, object]:
        records = self.query_tcras(
            text=text,
            status=status,
            selected_orgaos=selected_orgaos,
            selected_bairros=selected_bairros,
            selected_year=selected_year,
            only_mpsp=only_mpsp,
            only_relatorio_pendente=only_relatorio_pendente,
            only_prazo_vencido=only_prazo_vencido,
            today=today,
        )
        return compute_metrics(records, today=today)

    def build_record_overview(self, *, today: date | None = None) -> TcraRecordOverview:
        return build_record_overview(self.list_tcras(), today=today)

    def find_tcra_by_uid(self, uid: str) -> Tcra | None:
        records = self.get_tcras_by_uids([uid])
        return records[0] if records else None

    def find_duplicate_tcra(
        self,
        *,
        numero_processo: str = "",
        numero_tcra: str = "",
        local: str = "",
        exclude_uid: str = "",
    ) -> Tcra | None:
        normalized_uid = _stringify(exclude_uid)
        normalized_numero_tcra = _stringify(numero_tcra)
        normalized_numero_processo = _stringify(numero_processo)
        normalized_local = _stringify(local)

        with self._connect() as conn:
            if normalized_numero_tcra:
                row = self._select_tcra_row(
                    conn,
                    where_clause="numero_tcra = ? AND (? = '' OR uid <> ?)",
                    params=(normalized_numero_tcra, normalized_uid, normalized_uid),
                )
                if row is not None:
                    return self._row_to_tcra(row, self._load_eventos_for_uid(conn, _stringify(row["uid"])))

            if normalized_numero_processo and normalized_local:
                row = self._select_tcra_row(
                    conn,
                    where_clause="numero_processo = ? AND local = ? AND (? = '' OR uid <> ?)",
                    params=(normalized_numero_processo, normalized_local, normalized_uid, normalized_uid),
                )
                if row is not None:
                    return self._row_to_tcra(row, self._load_eventos_for_uid(conn, _stringify(row["uid"])))

        return None

    def upsert_tcra(self, tcra: Tcra) -> str:
        normalized = self._normalize_tcra(tcra)
        timestamp = _utc_timestamp()

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT uid, created_at FROM tcras WHERE uid = ?",
                (normalized.uid,),
            ).fetchone()
            created_at = _stringify(existing["created_at"]) if existing is not None else timestamp
            conn.execute(
                """
                INSERT INTO tcras (
                    uid,
                    numero_processo,
                    numero_tcra,
                    local,
                    endereco,
                    bairro,
                    orgao_acompanhamento,
                    status,
                    data_assinatura,
                    prazo_final,
                    periodicidade_relatorio_meses,
                    data_ultimo_relatorio,
                    data_proximo_relatorio,
                    area_m2,
                    numero_mudas_previsto,
                    servicos_exigidos,
                    responsavel_execucao,
                    observacoes,
                    mpsp_relacionado,
                    inquerito_civil,
                    search_blob_norm,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    numero_processo = excluded.numero_processo,
                    numero_tcra = excluded.numero_tcra,
                    local = excluded.local,
                    endereco = excluded.endereco,
                    bairro = excluded.bairro,
                    orgao_acompanhamento = excluded.orgao_acompanhamento,
                    status = excluded.status,
                    data_assinatura = excluded.data_assinatura,
                    prazo_final = excluded.prazo_final,
                    periodicidade_relatorio_meses = excluded.periodicidade_relatorio_meses,
                    data_ultimo_relatorio = excluded.data_ultimo_relatorio,
                    data_proximo_relatorio = excluded.data_proximo_relatorio,
                    area_m2 = excluded.area_m2,
                    numero_mudas_previsto = excluded.numero_mudas_previsto,
                    servicos_exigidos = excluded.servicos_exigidos,
                    responsavel_execucao = excluded.responsavel_execucao,
                    observacoes = excluded.observacoes,
                    mpsp_relacionado = excluded.mpsp_relacionado,
                    inquerito_civil = excluded.inquerito_civil,
                    search_blob_norm = excluded.search_blob_norm,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized.uid,
                    normalized.numero_processo,
                    normalized.numero_tcra,
                    normalized.local,
                    normalized.endereco,
                    normalized.bairro,
                    normalized.orgao_acompanhamento,
                    normalized.status,
                    _date_to_storage(normalized.data_assinatura),
                    _date_to_storage(normalized.prazo_final),
                    normalized.periodicidade_relatorio_meses,
                    _date_to_storage(normalized.data_ultimo_relatorio),
                    _date_to_storage(normalized.data_proximo_relatorio),
                    normalized.area_m2,
                    normalized.numero_mudas_previsto,
                    normalized.servicos_exigidos,
                    normalized.responsavel_execucao,
                    normalized.observacoes,
                    normalized.mpsp_relacionado,
                    normalized.inquerito_civil,
                    self._build_search_blob(normalized),
                    created_at,
                    timestamp,
                ),
            )
            self._replace_eventos(conn, normalized.uid, normalized.eventos, timestamp=timestamp)
        return normalized.uid

    def replace_all(self, tcras: Sequence[Tcra]) -> int:
        normalized_tcras = [self._normalize_tcra(tcra) for tcra in tcras]
        timestamp = _utc_timestamp()
        with self._connect() as conn:
            conn.execute("DELETE FROM tcra_eventos")
            conn.execute("DELETE FROM tcras")
            for tcra in normalized_tcras:
                conn.execute(
                    """
                    INSERT INTO tcras (
                        uid,
                        numero_processo,
                        numero_tcra,
                        local,
                        endereco,
                        bairro,
                        orgao_acompanhamento,
                        status,
                        data_assinatura,
                        prazo_final,
                        periodicidade_relatorio_meses,
                        data_ultimo_relatorio,
                        data_proximo_relatorio,
                        area_m2,
                        numero_mudas_previsto,
                        servicos_exigidos,
                        responsavel_execucao,
                        observacoes,
                        mpsp_relacionado,
                        inquerito_civil,
                        search_blob_norm,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tcra.uid,
                        tcra.numero_processo,
                        tcra.numero_tcra,
                        tcra.local,
                        tcra.endereco,
                        tcra.bairro,
                        tcra.orgao_acompanhamento,
                        tcra.status,
                        _date_to_storage(tcra.data_assinatura),
                        _date_to_storage(tcra.prazo_final),
                        tcra.periodicidade_relatorio_meses,
                        _date_to_storage(tcra.data_ultimo_relatorio),
                        _date_to_storage(tcra.data_proximo_relatorio),
                        tcra.area_m2,
                        tcra.numero_mudas_previsto,
                        tcra.servicos_exigidos,
                        tcra.responsavel_execucao,
                        tcra.observacoes,
                        tcra.mpsp_relacionado,
                        tcra.inquerito_civil,
                        self._build_search_blob(tcra),
                        timestamp,
                        timestamp,
                    ),
                )
                self._replace_eventos(conn, tcra.uid, tcra.eventos, timestamp=timestamp)
        return len(normalized_tcras)

    def delete_tcra(self, uid: str) -> bool:
        normalized_uid = _stringify(uid)
        if not normalized_uid:
            return False
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM tcras WHERE uid = ?", (normalized_uid,))
        return int(cursor.rowcount or 0) > 0

    def _normalize_tcra(self, tcra: Tcra) -> Tcra:
        normalized_uid = _stringify(tcra.uid) or uuid.uuid4().hex
        normalized_eventos = self._normalize_eventos(tcra.eventos)
        return Tcra(
            uid=normalized_uid,
            numero_processo=_stringify(tcra.numero_processo),
            numero_tcra=_stringify(tcra.numero_tcra),
            local=_stringify(tcra.local),
            endereco=_stringify(tcra.endereco),
            bairro=_stringify(tcra.bairro),
            orgao_acompanhamento=normalize_orgao_label(tcra.orgao_acompanhamento),
            status=normalize_status_label(tcra.status),
            data_assinatura=tcra.data_assinatura,
            prazo_final=tcra.prazo_final,
            periodicidade_relatorio_meses=tcra.periodicidade_relatorio_meses,
            data_ultimo_relatorio=tcra.data_ultimo_relatorio,
            data_proximo_relatorio=tcra.data_proximo_relatorio,
            area_m2=tcra.area_m2,
            numero_mudas_previsto=tcra.numero_mudas_previsto,
            servicos_exigidos=_stringify(tcra.servicos_exigidos),
            responsavel_execucao=_stringify(tcra.responsavel_execucao),
            observacoes=_stringify(tcra.observacoes),
            mpsp_relacionado=_stringify(tcra.mpsp_relacionado),
            inquerito_civil=_stringify(tcra.inquerito_civil),
            eventos=normalized_eventos,
        )

    def _normalize_eventos(self, eventos: Sequence[TcraEvento]) -> list[TcraEvento]:
        normalized = []
        for index, evento in enumerate(eventos, start=1):
            sequence = int(evento.sequence or index)
            normalized.append(
                TcraEvento(
                    sequence=sequence,
                    data_evento=evento.data_evento,
                    tipo_evento=_stringify(evento.tipo_evento),
                    descricao=_stringify(evento.descricao),
                    prazo_resultante=evento.prazo_resultante,
                    status_resultante=normalize_status_label(evento.status_resultante),
                )
            )
        normalized.sort(key=lambda item: (item.sequence, item.data_evento or date.min, item.tipo_evento))
        return normalized

    def _build_search_blob(self, tcra: Tcra) -> str:
        return build_search_blob(tcra)

    def _replace_eventos(
        self,
        conn: sqlite3.Connection,
        tcra_uid: str,
        eventos: Sequence[TcraEvento],
        *,
        timestamp: str,
    ) -> None:
        conn.execute("DELETE FROM tcra_eventos WHERE tcra_uid = ?", (tcra_uid,))
        for evento in self._normalize_eventos(eventos):
            conn.execute(
                """
                INSERT INTO tcra_eventos (
                    tcra_uid,
                    sequence,
                    data_evento,
                    tipo_evento,
                    descricao,
                    prazo_resultante,
                    status_resultante,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tcra_uid,
                    evento.sequence,
                    _date_to_storage(evento.data_evento),
                    evento.tipo_evento,
                    evento.descricao,
                    _date_to_storage(evento.prazo_resultante),
                    evento.status_resultante,
                    timestamp,
                    timestamp,
                ),
            )

    def _load_eventos_by_uid(
        self,
        conn: sqlite3.Connection,
        *,
        tcra_uids: Sequence[str] | None = None,
    ) -> dict[str, tuple[TcraEvento, ...]]:
        normalized_uids = [_stringify(uid) for uid in (tcra_uids or ()) if _stringify(uid)]
        query = """
            SELECT tcra_uid, sequence, data_evento, tipo_evento, descricao, prazo_resultante, status_resultante
            FROM tcra_eventos
        """
        params: tuple[object, ...] = ()
        if normalized_uids:
            placeholders = ", ".join("?" for _ in normalized_uids)
            query += f" WHERE tcra_uid IN ({placeholders})"
            params = tuple(normalized_uids)
        query += " ORDER BY tcra_uid ASC, sequence ASC"
        rows = conn.execute(query, params).fetchall()
        eventos_by_uid: dict[str, list[TcraEvento]] = {}
        for row in rows:
            uid = _stringify(row["tcra_uid"])
            eventos_by_uid.setdefault(uid, []).append(
                TcraEvento(
                    sequence=int(row["sequence"] or 0),
                    data_evento=_date_from_storage(row["data_evento"]),
                    tipo_evento=_stringify(row["tipo_evento"]),
                    descricao=_stringify(row["descricao"]),
                    prazo_resultante=_date_from_storage(row["prazo_resultante"]),
                    status_resultante=_stringify(row["status_resultante"]),
                )
            )
        return {uid: tuple(eventos) for uid, eventos in eventos_by_uid.items()}

    def _load_eventos_for_uid(self, conn: sqlite3.Connection, tcra_uid: str) -> tuple[TcraEvento, ...]:
        rows = conn.execute(
            """
            SELECT sequence, data_evento, tipo_evento, descricao, prazo_resultante, status_resultante
            FROM tcra_eventos
            WHERE tcra_uid = ?
            ORDER BY sequence ASC
            """,
            (tcra_uid,),
        ).fetchall()
        return tuple(
            TcraEvento(
                sequence=int(row["sequence"] or 0),
                data_evento=_date_from_storage(row["data_evento"]),
                tipo_evento=_stringify(row["tipo_evento"]),
                descricao=_stringify(row["descricao"]),
                prazo_resultante=_date_from_storage(row["prazo_resultante"]),
                status_resultante=_stringify(row["status_resultante"]),
            )
            for row in rows
        )

    def _row_to_tcra(self, row: sqlite3.Row, eventos: Sequence[TcraEvento]) -> Tcra:
        return Tcra(
            uid=_stringify(row["uid"]),
            numero_processo=_stringify(row["numero_processo"]),
            numero_tcra=_stringify(row["numero_tcra"]),
            local=_stringify(row["local"]),
            endereco=_stringify(row["endereco"]),
            bairro=_stringify(row["bairro"]),
            orgao_acompanhamento=_stringify(row["orgao_acompanhamento"]),
            status=_stringify(row["status"]),
            data_assinatura=_date_from_storage(row["data_assinatura"]),
            prazo_final=_date_from_storage(row["prazo_final"]),
            periodicidade_relatorio_meses=_int_from_storage(row["periodicidade_relatorio_meses"]),
            data_ultimo_relatorio=_date_from_storage(row["data_ultimo_relatorio"]),
            data_proximo_relatorio=_date_from_storage(row["data_proximo_relatorio"]),
            area_m2=_float_from_storage(row["area_m2"]),
            numero_mudas_previsto=_int_from_storage(row["numero_mudas_previsto"]),
            servicos_exigidos=_stringify(row["servicos_exigidos"]),
            responsavel_execucao=_stringify(row["responsavel_execucao"]),
            observacoes=_stringify(row["observacoes"]),
            mpsp_relacionado=_stringify(row["mpsp_relacionado"]),
            inquerito_civil=_stringify(row["inquerito_civil"]),
            eventos=list(eventos),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(os.fspath(self.db_path), timeout=30)
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

    def _select_tcra_rows(
        self,
        conn: sqlite3.Connection,
        *,
        where_clause: str = "",
        params: Sequence[object] = (),
        order_by: str = TCRA_DEFAULT_ORDER_BY,
    ) -> list[sqlite3.Row]:
        query = f"SELECT {TCRA_ROW_COLUMNS} FROM tcras"
        if where_clause:
            query += f" WHERE {where_clause}"
        if order_by:
            query += f" ORDER BY {order_by}"
        return list(conn.execute(query, tuple(params)).fetchall())

    def _select_tcra_row(
        self,
        conn: sqlite3.Connection,
        *,
        where_clause: str,
        params: Sequence[object] = (),
        order_by: str = TCRA_DEFAULT_ORDER_BY,
    ) -> sqlite3.Row | None:
        query = f"SELECT {TCRA_ROW_COLUMNS} FROM tcras WHERE {where_clause}"
        if order_by:
            query += f" ORDER BY {order_by}"
        query += " LIMIT 1"
        return conn.execute(query, tuple(params)).fetchone()

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tcras (
                uid TEXT PRIMARY KEY,
                numero_processo TEXT NOT NULL DEFAULT '',
                numero_tcra TEXT NOT NULL DEFAULT '',
                local TEXT NOT NULL DEFAULT '',
                endereco TEXT NOT NULL DEFAULT '',
                bairro TEXT NOT NULL DEFAULT '',
                orgao_acompanhamento TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                data_assinatura TEXT NOT NULL DEFAULT '',
                prazo_final TEXT NOT NULL DEFAULT '',
                periodicidade_relatorio_meses INTEGER,
                data_ultimo_relatorio TEXT NOT NULL DEFAULT '',
                data_proximo_relatorio TEXT NOT NULL DEFAULT '',
                area_m2 REAL,
                numero_mudas_previsto INTEGER,
                servicos_exigidos TEXT NOT NULL DEFAULT '',
                responsavel_execucao TEXT NOT NULL DEFAULT '',
                observacoes TEXT NOT NULL DEFAULT '',
                mpsp_relacionado TEXT NOT NULL DEFAULT '',
                inquerito_civil TEXT NOT NULL DEFAULT '',
                search_blob_norm TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tcra_eventos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tcra_uid TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                data_evento TEXT NOT NULL DEFAULT '',
                tipo_evento TEXT NOT NULL DEFAULT '',
                descricao TEXT NOT NULL DEFAULT '',
                prazo_resultante TEXT NOT NULL DEFAULT '',
                status_resultante TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (tcra_uid) REFERENCES tcras(uid) ON DELETE CASCADE,
                CONSTRAINT uq_tcra_eventos_uid_sequence UNIQUE (tcra_uid, sequence)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tcras_numero_processo ON tcras(numero_processo COLLATE NOCASE)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tcras_numero_tcra ON tcras(numero_tcra COLLATE NOCASE)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tcras_status ON tcras(status COLLATE NOCASE)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tcras_prazo_final ON tcras(prazo_final)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tcras_search_blob_norm ON tcras(search_blob_norm)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tcra_eventos_uid_sequence ON tcra_eventos(tcra_uid, sequence)")
