from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem
from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.sqlite_mirror_service import DEFAULT_SINGLETON_SESSION_PATH, SqliteMirrorService
from app.services.tcra_sqlite_service import TcraSqliteService
from app.utils.app_paths import ensure_dir, resolve_data_path
from app.utils.logger import get_logger


logger = get_logger("Supabase.Sync")


PRODUCTION_CACHE_SESSION_PATH = DEFAULT_SINGLETON_SESSION_PATH


class SupabaseWorkspaceSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class SupabaseWorkspaceSyncResult:
    local_db_path: str
    session_path: str
    workbook_name: str
    workbook_path: str
    record_count: int
    plantio_count: int
    audit_event_count: int
    tcra_count: int
    tcra_event_count: int


class SupabaseWorkspaceSyncService:
    def __init__(
        self,
        *,
        production_db_path: str | Path | None = None,
        session_path: str = PRODUCTION_CACHE_SESSION_PATH,
    ) -> None:
        self.production_db_path = Path(production_db_path) if production_db_path else resolve_data_path(
            "state",
            "production",
            "compensacoes-prod.db",
        )
        self.session_path = str(session_path or PRODUCTION_CACHE_SESSION_PATH).strip() or PRODUCTION_CACHE_SESSION_PATH

    def sync_authenticated_client(
        self,
        client: Any,
        *,
        local_db_path: str | Path | None = None,
        session_path: str | None = None,
    ) -> SupabaseWorkspaceSyncResult:
        if client is None:
            raise SupabaseWorkspaceSyncError("Cliente Supabase ausente para sincronizacao da producao.")

        target_db_path = Path(local_db_path) if local_db_path else self.production_db_path
        target_session_path = str(session_path or self.session_path or PRODUCTION_CACHE_SESSION_PATH).strip()
        if not target_session_path:
            target_session_path = PRODUCTION_CACHE_SESSION_PATH

        snapshot = self._fetch_snapshot(client)
        self._reset_local_database(target_db_path)

        sqlite_service = SqliteMirrorService(db_path=target_db_path)
        sqlite_summary = sqlite_service.sync_workbook_snapshot(target_session_path, snapshot.records)
        for audit_payload in snapshot.audit_events:
            sqlite_service.mirror_audit_event(
                event_id=str(audit_payload.get("event_id", "") or ""),
                timestamp=str(audit_payload.get("timestamp", "") or ""),
                workbook_path=target_session_path,
                action=str(audit_payload.get("action", "") or ""),
                summary=str(audit_payload.get("summary", "") or ""),
                backup_path=str(audit_payload.get("backup_path", "") or ""),
                metadata=dict(audit_payload.get("metadata_json") or {}),
                before=dict(audit_payload.get("before_json") or {}) or None,
                after=dict(audit_payload.get("after_json") or {}) or None,
            )

        tcra_service = TcraSqliteService(db_path=target_db_path)
        tcra_service.replace_all(snapshot.tcras)

        logger.info(
            "Snapshot remoto do Supabase sincronizado para %s com %s registro(s) e %s TCRA(s).",
            target_db_path,
            len(snapshot.records),
            len(snapshot.tcras),
        )
        return SupabaseWorkspaceSyncResult(
            local_db_path=str(target_db_path),
            session_path=target_session_path,
            workbook_name=snapshot.workbook_name,
            workbook_path=snapshot.workbook_path,
            record_count=sqlite_summary.record_count,
            plantio_count=sqlite_summary.plantio_count,
            audit_event_count=len(snapshot.audit_events),
            tcra_count=len(snapshot.tcras),
            tcra_event_count=sum(len(record.eventos) for record in snapshot.tcras),
        )

    def _fetch_snapshot(self, client: Any) -> SimpleNamespace:
        workbook_row = self._fetch_workbook_row(client)
        record_rows = self._fetch_table_rows(client, "records", order_by="id")
        plantio_rows = self._fetch_table_rows(client, "plantios", order_by="id")
        audit_rows = self._fetch_table_rows(client, "audit_events", order_by="id")
        tcra_rows = self._fetch_table_rows(client, "tcras", order_by="uid")
        tcra_event_rows = self._fetch_table_rows(client, "tcra_eventos", order_by="id")

        return SimpleNamespace(
            workbook_name=str(workbook_row.get("workbook_name", "") or "Base oficial"),
            workbook_path=str(workbook_row.get("workbook_path", "") or self.session_path),
            records=self._build_records(record_rows, plantio_rows),
            audit_events=tuple(self._normalize_audit_payloads(audit_rows)),
            tcras=self._build_tcras(tcra_rows, tcra_event_rows),
        )

    def _fetch_workbook_row(self, client: Any) -> dict[str, Any]:
        rows = self._fetch_table_rows(client, "workbooks", order_by="id", limit=1)
        if not rows:
            raise SupabaseWorkspaceSyncError(
                "O Supabase nao retornou nenhum workbook de producao. Verifique as politicas RLS e os dados iniciais."
            )
        return dict(rows[0] or {})

    def _fetch_table_rows(
        self,
        client: Any,
        table_name: str,
        *,
        order_by: str,
        page_size: int = 1000,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        start = 0
        remaining = max(int(limit or 0), 0) if limit is not None else None
        while True:
            query = client.table(table_name).select("*").order(order_by)
            if remaining is not None:
                batch_limit = min(page_size, remaining)
                query = query.limit(batch_limit)
            else:
                batch_limit = page_size
                query = query.range(start, start + batch_limit - 1)
            response = query.execute()
            batch = list(getattr(response, "data", []) or [])
            rows.extend(dict(item or {}) for item in batch)
            if remaining is not None:
                break
            if len(batch) < batch_limit:
                break
            start += batch_limit
        return rows

    @staticmethod
    def _build_records(
        record_rows: Sequence[dict[str, Any]],
        plantio_rows: Sequence[dict[str, Any]],
    ) -> tuple[Compensacao, ...]:
        plantios_by_record_id: dict[int, list[PlantioItem]] = {}
        for row in plantio_rows:
            record_id = int(row.get("record_id") or 0)
            if record_id <= 0:
                continue
            plantios_by_record_id.setdefault(record_id, []).append(
                PlantioItem(
                    sequence=int(row.get("sequence") or 0),
                    endereco=str(row.get("endereco", "") or ""),
                    qtd_mudas=str(row.get("qtd_mudas", "") or ""),
                    latitude=str(row.get("latitude", "") or ""),
                    longitude=str(row.get("longitude", "") or ""),
                )
            )

        records: list[Compensacao] = []
        for row in record_rows:
            record_id = int(row.get("id") or 0)
            records.append(
                Compensacao(
                    excel_row=int(row.get("excel_row") or 0),
                    oficio_processo=str(row.get("oficio_processo", "") or ""),
                    eletronico=str(row.get("eletronico", "") or ""),
                    caixa=str(row.get("caixa", "") or ""),
                    av_tec=str(row.get("av_tec", "") or ""),
                    compensacao=str(row.get("compensacao", "") or ""),
                    endereco=str(row.get("endereco", "") or ""),
                    microbacia=str(row.get("microbacia", "") or ""),
                    compensado=str(row.get("compensado", "") or ""),
                    endereco_plantio=str(row.get("endereco_plantio", "") or ""),
                    latitude_plantio=str(row.get("latitude_plantio", "") or ""),
                    longitude_plantio=str(row.get("longitude_plantio", "") or ""),
                    latitude=str(row.get("latitude", "") or ""),
                    longitude=str(row.get("longitude", "") or ""),
                    uid=str(row.get("uid", "") or ""),
                    plantios=sorted(
                        plantios_by_record_id.get(record_id, []),
                        key=lambda item: int(item.sequence or 0),
                    ),
                )
            )
        return tuple(records)

    @classmethod
    def _build_tcras(
        cls,
        tcra_rows: Sequence[dict[str, Any]],
        event_rows: Sequence[dict[str, Any]],
    ) -> tuple[Tcra, ...]:
        events_by_uid: dict[str, list[TcraEvento]] = {}
        for row in event_rows:
            uid = str(row.get("tcra_uid", "") or "").strip()
            if not uid:
                continue
            events_by_uid.setdefault(uid, []).append(
                TcraEvento(
                    sequence=int(row.get("sequence") or 0),
                    data_evento=cls._parse_date(row.get("data_evento")),
                    tipo_evento=str(row.get("tipo_evento", "") or ""),
                    descricao=str(row.get("descricao", "") or ""),
                    prazo_resultante=cls._parse_date(row.get("prazo_resultante")),
                    status_resultante=str(row.get("status_resultante", "") or ""),
                )
            )

        records: list[Tcra] = []
        for row in tcra_rows:
            uid = str(row.get("uid", "") or "")
            records.append(
                Tcra(
                    uid=uid,
                    numero_processo=str(row.get("numero_processo", "") or ""),
                    numero_tcra=str(row.get("numero_tcra", "") or ""),
                    local=str(row.get("local", "") or ""),
                    endereco=str(row.get("endereco", "") or ""),
                    bairro=str(row.get("bairro", "") or ""),
                    orgao_acompanhamento=str(row.get("orgao_acompanhamento", "") or ""),
                    status=str(row.get("status", "") or ""),
                    data_assinatura=cls._parse_date(row.get("data_assinatura")),
                    prazo_final=cls._parse_date(row.get("prazo_final")),
                    periodicidade_relatorio_meses=cls._parse_int(row.get("periodicidade_relatorio_meses")),
                    data_ultimo_relatorio=cls._parse_date(row.get("data_ultimo_relatorio")),
                    data_proximo_relatorio=cls._parse_date(row.get("data_proximo_relatorio")),
                    area_m2=cls._parse_float(row.get("area_m2")),
                    numero_mudas_previsto=cls._parse_int(row.get("numero_mudas_previsto")),
                    servicos_exigidos=str(row.get("servicos_exigidos", "") or ""),
                    responsavel_execucao=str(row.get("responsavel_execucao", "") or ""),
                    observacoes=str(row.get("observacoes", "") or ""),
                    mpsp_relacionado=str(row.get("mpsp_relacionado", "") or ""),
                    inquerito_civil=str(row.get("inquerito_civil", "") or ""),
                    eventos=sorted(
                        events_by_uid.get(uid, []),
                        key=lambda item: int(item.sequence or 0),
                    ),
                )
            )
        return tuple(records)

    @staticmethod
    def _normalize_audit_payloads(rows: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
        payloads: list[dict[str, Any]] = []
        for row in rows:
            payloads.append(
                {
                    "event_id": str(row.get("event_id", "") or ""),
                    "timestamp": str(row.get("timestamp", "") or ""),
                    "action": str(row.get("action", "") or ""),
                    "summary": str(row.get("summary", "") or ""),
                    "backup_path": str(row.get("backup_path", "") or ""),
                    "metadata_json": dict(row.get("metadata_json") or {}),
                    "before_json": dict(row.get("before_json") or {}) or None,
                    "after_json": dict(row.get("after_json") or {}) or None,
                }
            )
        return tuple(payloads)

    @staticmethod
    def _parse_date(value: object) -> date | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None

    @staticmethod
    def _parse_int(value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _reset_local_database(target_path: Path) -> None:
        ensure_dir(target_path.parent)
        if target_path.exists():
            target_path.unlink()

