from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError as exc:  # pragma: no cover - mensagem operacional
    raise SystemExit(
        "Instale a dependencia administrativa com `pip install \"psycopg[binary]\"` "
        "ou `pip install -r requirements-dev.txt` para sincronizar o SQLite com o Supabase."
    ) from exc


DEFAULT_SQLITE_PATH = Path("data/state/compensacoes.db")
DEFAULT_ENV_FILE = Path(".env.supabase")
RESET_TABLES = (
    "tcra_eventos",
    "tcras",
    "audit_events",
    "plantios",
    "records",
    "workbooks",
    "meta",
)
IDENTITY_TABLES = (
    "workbooks",
    "records",
    "plantios",
    "audit_events",
    "tcra_eventos",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sincroniza o banco SQLite local do app com o Postgres do Supabase."
    )
    parser.add_argument(
        "--sqlite-path",
        default=str(DEFAULT_SQLITE_PATH),
        help="Caminho do banco SQLite local. Padrao: data/state/compensacoes.db",
    )
    parser.add_argument(
        "--db-url",
        default="",
        help="Connection string Postgres do Supabase. Tambem aceita SUPABASE_DB_URL ou DATABASE_URL.",
    )
    parser.add_argument(
        "--schema",
        default="public",
        help="Schema de destino no Postgres. Padrao: public",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas mostra as contagens que seriam sincronizadas, sem gravar no Supabase.",
    )
    return parser.parse_args()


def load_local_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    loaded: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        loaded[key.strip()] = value.strip().strip('"').strip("'")
    return loaded


def resolve_db_url(explicit_value: str) -> str:
    if str(explicit_value or "").strip():
        return str(explicit_value).strip()
    env_file_values = load_local_env(DEFAULT_ENV_FILE)
    return (
        str(env_file_values.get("SUPABASE_DB_URL", "")).strip()
        or str(os.getenv("SUPABASE_DB_URL", "")).strip()
        or str(os.getenv("DATABASE_URL", "")).strip()
    )


def open_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def fetch_rows(conn: sqlite3.Connection, table: str, *, order_by: str | None = None) -> list[dict[str, Any]]:
    query = f"SELECT * FROM {table}"
    if order_by:
        query += f" ORDER BY {order_by}"
    return [dict(row) for row in conn.execute(query).fetchall()]


def parse_json_text(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def blank_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def prepare_dataset(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    dataset = {
        "meta": fetch_rows(conn, "meta", order_by="key"),
        "workbooks": fetch_rows(conn, "workbooks", order_by="id"),
        "records": fetch_rows(conn, "records", order_by="id"),
        "plantios": fetch_rows(conn, "plantios", order_by="id"),
        "audit_events": fetch_rows(conn, "audit_events", order_by="id"),
        "tcras": fetch_rows(conn, "tcras", order_by="uid"),
        "tcra_eventos": fetch_rows(conn, "tcra_eventos", order_by="id"),
    }

    for row in dataset["audit_events"]:
        row["metadata_json"] = parse_json_text(row.get("metadata_json")) or {}
        row["before_json"] = parse_json_text(row.get("before_json"))
        row["after_json"] = parse_json_text(row.get("after_json"))

    for row in dataset["tcras"]:
        for field in (
            "data_assinatura",
            "prazo_final",
            "data_ultimo_relatorio",
            "data_proximo_relatorio",
            "periodicidade_relatorio_meses",
            "area_m2",
            "numero_mudas_previsto",
        ):
            row[field] = blank_to_none(row.get(field))

    for row in dataset["tcra_eventos"]:
        for field in ("data_evento", "prazo_resultante"):
            row[field] = blank_to_none(row.get(field))

    return dataset


def print_summary(dataset: dict[str, list[dict[str, Any]]]) -> None:
    for table in ("meta", "workbooks", "records", "plantios", "audit_events", "tcras", "tcra_eventos"):
        print(f"{table}: {len(dataset[table])}")


def truncate_target(conn: psycopg.Connection, schema: str) -> None:
    qualified_tables = ", ".join(f"{schema}.{table}" for table in RESET_TABLES)
    conn.execute(f"TRUNCATE TABLE {qualified_tables} RESTART IDENTITY CASCADE")


def insert_many(
    conn: psycopg.Connection,
    schema: str,
    table: str,
    columns: Iterable[str],
    rows: list[dict[str, Any]],
) -> None:
    rows = list(rows)
    if not rows:
        return

    column_list = list(columns)
    placeholders = ", ".join(["%s"] * len(column_list))
    columns_sql = ", ".join(column_list)
    sql = f"INSERT INTO {schema}.{table} ({columns_sql}) VALUES ({placeholders})"

    values: list[tuple[Any, ...]] = []
    for row in rows:
        record: list[Any] = []
        for column in column_list:
            value = row.get(column)
            if table == "audit_events" and column in {"metadata_json", "before_json", "after_json"}:
                value = Jsonb(value) if value is not None else None
            record.append(value)
        values.append(tuple(record))

    with conn.cursor() as cur:
        cur.executemany(sql, values)


def sync_identity_sequences(conn: psycopg.Connection, schema: str) -> None:
    with conn.cursor() as cur:
        for table in IDENTITY_TABLES:
            cur.execute(
                f"""
                SELECT setval(
                    pg_get_serial_sequence(%s, 'id'),
                    COALESCE((SELECT MAX(id) FROM {schema}.{table}), 1),
                    (SELECT COUNT(*) > 0 FROM {schema}.{table})
                )
                """,
                (f"{schema}.{table}",),
            )


def validate_target_schema(conn: psycopg.Connection, schema: str) -> None:
    with conn.cursor() as cur:
        tables = {
            row[0]
            for row in cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                """,
                (schema,),
            ).fetchall()
        }
    missing = [table for table in RESET_TABLES if table not in tables]
    if missing:
        raise RuntimeError(
            "Schema Postgres incompleto. Rode as migrations do Supabase antes da carga. "
            f"Tabelas ausentes: {', '.join(missing)}."
        )


def main() -> int:
    args = parse_args()
    sqlite_path = Path(args.sqlite_path).resolve()
    if not sqlite_path.exists():
        raise SystemExit(f"Banco SQLite nao encontrado: {sqlite_path}")

    with open_sqlite(sqlite_path) as sqlite_conn:
        dataset = prepare_dataset(sqlite_conn)

    print(f"SQLite origem: {sqlite_path}")
    print_summary(dataset)
    if args.dry_run:
        print("Dry-run concluido. Nenhum dado foi enviado ao Supabase.")
        return 0

    db_url = resolve_db_url(args.db_url)
    if not db_url:
        raise SystemExit(
            "Informe a connection string do Supabase via --db-url, .env.supabase ou pela variavel SUPABASE_DB_URL."
        )

    with psycopg.connect(db_url, autocommit=False) as pg_conn:
        validate_target_schema(pg_conn, args.schema)
        truncate_target(pg_conn, args.schema)
        insert_many(pg_conn, args.schema, "meta", ("key", "value"), dataset["meta"])
        insert_many(
            pg_conn,
            args.schema,
            "workbooks",
            (
                "id",
                "workbook_path",
                "workbook_name",
                "created_at",
                "last_loaded_at",
                "last_synced_at",
                "record_count",
                "plantio_count",
                "source_mtime_ns",
                "source_size",
            ),
            dataset["workbooks"],
        )
        insert_many(
            pg_conn,
            args.schema,
            "records",
            (
                "id",
                "workbook_id",
                "uid",
                "excel_row",
                "oficio_processo",
                "eletronico",
                "caixa",
                "av_tec",
                "compensacao",
                "endereco",
                "microbacia",
                "compensado",
                "endereco_plantio",
                "latitude_plantio",
                "longitude_plantio",
                "latitude",
                "longitude",
                "synced_at",
                "oficio_year",
                "tipo_key",
                "microbacia_key",
                "search_blob_norm",
            ),
            dataset["records"],
        )
        insert_many(
            pg_conn,
            args.schema,
            "plantios",
            ("id", "record_id", "sequence", "endereco", "qtd_mudas", "latitude", "longitude"),
            dataset["plantios"],
        )
        insert_many(
            pg_conn,
            args.schema,
            "audit_events",
            (
                "id",
                "event_id",
                "workbook_id",
                "workbook_path",
                "timestamp",
                "action",
                "summary",
                "backup_path",
                "metadata_json",
                "before_json",
                "after_json",
                "mirrored_at",
            ),
            dataset["audit_events"],
        )
        insert_many(
            pg_conn,
            args.schema,
            "tcras",
            (
                "uid",
                "numero_processo",
                "numero_tcra",
                "local",
                "endereco",
                "bairro",
                "orgao_acompanhamento",
                "status",
                "data_assinatura",
                "prazo_final",
                "periodicidade_relatorio_meses",
                "data_ultimo_relatorio",
                "data_proximo_relatorio",
                "area_m2",
                "numero_mudas_previsto",
                "servicos_exigidos",
                "responsavel_execucao",
                "observacoes",
                "mpsp_relacionado",
                "inquerito_civil",
                "search_blob_norm",
                "created_at",
                "updated_at",
            ),
            dataset["tcras"],
        )
        insert_many(
            pg_conn,
            args.schema,
            "tcra_eventos",
            (
                "id",
                "tcra_uid",
                "sequence",
                "data_evento",
                "tipo_evento",
                "descricao",
                "prazo_resultante",
                "status_resultante",
                "created_at",
                "updated_at",
            ),
            dataset["tcra_eventos"],
        )
        sync_identity_sequences(pg_conn, args.schema)
        pg_conn.commit()

    print("Sincronizacao concluida com sucesso no Supabase.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
