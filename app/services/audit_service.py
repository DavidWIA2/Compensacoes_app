from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.services.audit_service_support import (
    AuditEvent,
    AuditOverview,  # noqa: F401
    audit_backup_available,  # noqa: F401
    audit_backup_path,  # noqa: F401
    audit_event_matches_path,
    build_audit_event,
    build_audit_event_from_payload,
    build_audit_overview,  # noqa: F401
    format_audit_timestamp,  # noqa: F401
    normalize_audit_path,
    parse_audit_json_line,
    parse_audit_timestamp,  # noqa: F401
    serialize_audit_event,
    serialize_plantio,  # noqa: F401
    serialize_record,  # noqa: F401
    serialize_records_sample,  # noqa: F401
    sort_audit_events,
)
from app.services.sqlite_mirror_service import SqliteMirrorService
from app.utils.app_paths import ensure_dir, resolve_data_path
from app.utils.logger import get_logger


logger = get_logger("Audit")


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
        action: str,
        summary: str,
        workbook_path: str = "",
        session_path: str = "",
        backup_path: str = "",
        metadata: Optional[dict[str, object]] = None,
        before: Optional[dict[str, object]] = None,
        after: Optional[dict[str, object]] = None,
    ) -> AuditEvent:
        event = build_audit_event(
            action=action,
            summary=summary,
            workbook_path=workbook_path,
            session_path=session_path,
            backup_path=backup_path,
            metadata=metadata,
            before=before,
            after=after,
        )

        with self.audit_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(serialize_audit_event(event), ensure_ascii=True) + "\n")

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

    def append_session_event(
        self,
        *,
        session_path: str,
        action: str,
        summary: str,
        backup_path: str = "",
        metadata: Optional[dict[str, object]] = None,
        before: Optional[dict[str, object]] = None,
        after: Optional[dict[str, object]] = None,
    ) -> AuditEvent:
        return self.append_event(
            session_path=session_path,
            action=action,
            summary=summary,
            backup_path=backup_path,
            metadata=metadata,
            before=before,
            after=after,
        )

    def list_events_for_workbook(self, workbook_path: str, *, limit: int = 50) -> list[AuditEvent]:
        sqlite_events = self._list_events_from_sqlite(workbook_path, limit=limit)
        if sqlite_events:
            return sqlite_events
        return self._list_events_from_jsonl(workbook_path, limit=limit)

    def list_events_for_session(self, session_path: str, *, limit: int = 50) -> list[AuditEvent]:
        return self.list_events_for_workbook(session_path, limit=limit)

    def _list_events_from_sqlite(self, workbook_path: str, *, limit: int) -> list[AuditEvent]:
        if self.persistence_service is None:
            return []

        try:
            if hasattr(self.persistence_service, "list_audit_event_payloads_for_session"):
                payloads = self.persistence_service.list_audit_event_payloads_for_session(workbook_path, limit=limit)
            else:
                payloads = self.persistence_service.list_audit_event_payloads_for_workbook(workbook_path, limit=limit)
        except Exception as exc:
            logger.warning("Falha ao consultar auditoria pelo SQLite: %s", exc, exc_info=True)
            return []

        events: list[AuditEvent] = []
        skipped_payloads = 0
        for payload in payloads:
            try:
                events.append(build_audit_event_from_payload(dict(payload or {})))
            except Exception as exc:
                skipped_payloads += 1
                logger.warning("Falha ao converter payload de auditoria do SQLite: %s", exc, exc_info=True)
        if skipped_payloads:
            logger.warning("Auditoria: %s payload(s) do SQLite foram ignorados por estarem invalidos.", skipped_payloads)
        return sort_audit_events(events, limit=limit)

    def _list_events_from_jsonl(self, workbook_path: str, *, limit: int) -> list[AuditEvent]:
        target_path = normalize_audit_path(workbook_path)
        if not self.audit_log_path.exists():
            return []

        events: list[AuditEvent] = []
        skipped_json_lines = 0
        with self.audit_log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = parse_audit_json_line(line)
                except json.JSONDecodeError as exc:
                    skipped_json_lines += 1
                    logger.warning("Falha ao ler linha JSONL de auditoria: %s", exc, exc_info=True)
                    continue
                try:
                    event = build_audit_event_from_payload(payload)
                except Exception as exc:
                    skipped_json_lines += 1
                    logger.warning("Falha ao converter evento JSONL de auditoria: %s", exc, exc_info=True)
                    continue
                if not audit_event_matches_path(event, target_path):
                    continue
                events.append(event)

        if skipped_json_lines:
            logger.warning("Auditoria: %s linha(s) JSONL foram ignoradas por estarem invalidas.", skipped_json_lines)
        return sort_audit_events(events, limit=limit)
