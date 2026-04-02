from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem
from app.services.sqlite_mirror_service import SqliteMirrorService
from app.utils.app_paths import ensure_dir, resolve_data_path
from app.utils.logger import get_logger


logger = get_logger("Audit")


def _normalize_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(str(path or "").strip()))


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    timestamp: str
    workbook_path: str
    action: str
    summary: str
    backup_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class AuditOverview:
    total_events: int
    events_today: int
    available_backups: int
    configured_backups: int
    latest_summary: str = ""
    latest_timestamp: str = ""
    action_counts: tuple[tuple[str, int], ...] = ()


def serialize_plantio(item: PlantioItem) -> dict[str, Any]:
    return {
        "sequence": int(item.sequence),
        "endereco": item.endereco,
        "qtd_mudas": item.qtd_mudas,
        "latitude": item.latitude,
        "longitude": item.longitude,
    }


def serialize_record(record: Compensacao) -> dict[str, Any]:
    return {
        "excel_row": int(record.excel_row),
        "uid": record.uid,
        "oficio_processo": record.oficio_processo,
        "eletronico": record.eletronico,
        "caixa": record.caixa,
        "av_tec": record.av_tec,
        "compensacao": record.compensacao,
        "endereco": record.endereco,
        "microbacia": record.microbacia,
        "compensado": record.compensado,
        "endereco_plantio": record.endereco_plantio,
        "latitude_plantio": record.latitude_plantio,
        "longitude_plantio": record.longitude_plantio,
        "latitude": record.latitude,
        "longitude": record.longitude,
        "plantios": [serialize_plantio(item) for item in record.plantios],
    }


def serialize_records_sample(records: Sequence[Compensacao], *, limit: int = 10) -> list[dict[str, Any]]:
    return [serialize_record(record) for record in list(records)[: max(limit, 0)]]


def parse_audit_timestamp(value: str) -> Optional[datetime]:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_audit_timestamp(value: str) -> str:
    parsed = parse_audit_timestamp(value)
    if parsed is None:
        return str(value or "").strip()
    return parsed.astimezone().strftime("%d/%m/%Y %H:%M:%S")


def audit_backup_path(event: AuditEvent) -> str:
    return str(getattr(event, "backup_path", "") or "").strip()


def audit_backup_available(event: AuditEvent) -> bool:
    backup_path = audit_backup_path(event)
    return bool(backup_path) and os.path.exists(backup_path)


def build_audit_overview(events: Sequence[AuditEvent]) -> AuditOverview:
    action_counter: dict[str, int] = {}
    local_today = datetime.now().astimezone().date()
    events_today = 0
    available_backups = 0
    configured_backups = 0

    for event in events:
        action = str(event.action or "").strip().upper() or "SEM ACAO"
        action_counter[action] = action_counter.get(action, 0) + 1

        backup_path = audit_backup_path(event)
        if backup_path:
            configured_backups += 1
            if audit_backup_available(event):
                available_backups += 1

        parsed = parse_audit_timestamp(event.timestamp)
        if parsed is not None and parsed.astimezone().date() == local_today:
            events_today += 1

    latest_event = events[0] if events else None
    action_counts = tuple(sorted(action_counter.items()))
    return AuditOverview(
        total_events=len(events),
        events_today=events_today,
        available_backups=available_backups,
        configured_backups=configured_backups,
        latest_summary=str(getattr(latest_event, "summary", "") or ""),
        latest_timestamp=format_audit_timestamp(str(getattr(latest_event, "timestamp", "") or "")),
        action_counts=action_counts,
    )


class AuditService:
    def __init__(
        self,
        *,
        audit_log_path: str | Path | None = None,
        persistence_service: SqliteMirrorService | None = None,
    ):
        self.audit_log_path = Path(audit_log_path) if audit_log_path else resolve_data_path("audit", "events.jsonl")
        self.persistence_service = persistence_service
        ensure_dir(self.audit_log_path.parent)

    def append_event(
        self,
        *,
        workbook_path: str,
        action: str,
        summary: str,
        backup_path: str = "",
        metadata: Optional[dict[str, Any]] = None,
        before: Optional[dict[str, Any]] = None,
        after: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            timestamp=_utc_timestamp(),
            workbook_path=_normalize_path(workbook_path),
            action=str(action or "").strip(),
            summary=str(summary or "").strip(),
            backup_path=os.path.abspath(backup_path) if backup_path else "",
            metadata=dict(metadata or {}),
            before=before,
            after=after,
        )

        with self.audit_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=True) + "\n")

        if self.persistence_service is not None:
            try:
                self.persistence_service.mirror_audit_event(
                    event_id=event.event_id,
                    timestamp=event.timestamp,
                    workbook_path=event.workbook_path,
                    action=event.action,
                    summary=event.summary,
                    backup_path=event.backup_path,
                    metadata=event.metadata,
                    before=event.before,
                    after=event.after,
                )
            except Exception as exc:
                logger.warning("Falha ao espelhar evento de auditoria no SQLite: %s", exc, exc_info=True)

        return event

    def list_events_for_workbook(self, workbook_path: str, *, limit: int = 50) -> list[AuditEvent]:
        sqlite_events = self._list_events_from_sqlite(workbook_path, limit=limit)
        if sqlite_events:
            return sqlite_events
        return self._list_events_from_jsonl(workbook_path, limit=limit)

    def _list_events_from_sqlite(self, workbook_path: str, *, limit: int) -> list[AuditEvent]:
        if self.persistence_service is None:
            return []

        try:
            payloads = self.persistence_service.list_audit_event_payloads_for_workbook(workbook_path, limit=limit)
        except Exception as exc:
            logger.warning("Falha ao consultar auditoria pelo SQLite: %s", exc, exc_info=True)
            return []

        events: list[AuditEvent] = []
        for payload in payloads:
            try:
                events.append(
                    AuditEvent(
                        event_id=str(payload.get("event_id") or ""),
                        timestamp=str(payload.get("timestamp") or ""),
                        workbook_path=str(payload.get("workbook_path") or ""),
                        action=str(payload.get("action") or ""),
                        summary=str(payload.get("summary") or ""),
                        backup_path=str(payload.get("backup_path") or ""),
                        metadata=dict(payload.get("metadata") or {}),
                        before=payload.get("before"),
                        after=payload.get("after"),
                    )
                )
            except Exception:
                continue
        return events

    def _list_events_from_jsonl(self, workbook_path: str, *, limit: int) -> list[AuditEvent]:
        target_path = _normalize_path(workbook_path)
        if not self.audit_log_path.exists():
            return []

        events: list[AuditEvent] = []
        with self.audit_log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if _normalize_path(str(payload.get("workbook_path", ""))) != target_path:
                    continue
                try:
                    events.append(
                        AuditEvent(
                            event_id=str(payload.get("event_id") or ""),
                            timestamp=str(payload.get("timestamp") or ""),
                            workbook_path=str(payload.get("workbook_path") or ""),
                            action=str(payload.get("action") or ""),
                            summary=str(payload.get("summary") or ""),
                            backup_path=str(payload.get("backup_path") or ""),
                            metadata=dict(payload.get("metadata") or {}),
                            before=payload.get("before"),
                            after=payload.get("after"),
                        )
                    )
                except Exception:
                    continue

        events.sort(key=lambda event: event.timestamp, reverse=True)
        return events[: max(limit, 0)]
