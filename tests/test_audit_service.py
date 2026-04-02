from app.models.compensacao import Compensacao
from datetime import datetime, timedelta, timezone

from app.services.audit_service import AuditService, build_audit_overview, serialize_record
from app.services.sqlite_mirror_service import SqliteMirrorService


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 3,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "Gregorio",
        "compensado": "",
        "uid": "uid-1",
    }
    base.update(overrides)
    return Compensacao(**base)


def test_audit_service_appends_and_filters_events_by_workbook(tmp_path):
    log_path = tmp_path / "audit" / "events.jsonl"
    service = AuditService(audit_log_path=log_path)

    service.append_event(
        workbook_path=str(tmp_path / "base-a.xlsx"),
        action="add",
        summary="Registro cadastrado",
        backup_path=str(tmp_path / "backups" / "a.xlsx"),
        after=serialize_record(make_record(uid="uid-a")),
    )
    service.append_event(
        workbook_path=str(tmp_path / "base-b.xlsx"),
        action="delete",
        summary="Registro excluido",
        backup_path=str(tmp_path / "backups" / "b.xlsx"),
        before=serialize_record(make_record(uid="uid-b")),
    )

    events = service.list_events_for_workbook(str(tmp_path / "base-a.xlsx"))

    assert len(events) == 1
    assert events[0].action == "add"
    assert events[0].summary == "Registro cadastrado"
    assert events[0].after is not None
    assert events[0].after["uid"] == "uid-a"


def test_build_audit_overview_counts_actions_today_and_available_backups(tmp_path):
    available_backup = tmp_path / "available.xlsx"
    available_backup.write_text("backup", encoding="utf-8")

    now = datetime.now(timezone.utc)
    events = [
        service_event("evt-1", now.isoformat(), "edit", "Registro alterado", str(available_backup)),
        service_event("evt-2", now.isoformat(), "import", "Importacao concluida", ""),
        service_event("evt-3", (now - timedelta(days=3)).isoformat(), "edit", "Registro alterado 2", str(tmp_path / "missing.xlsx")),
    ]

    overview = build_audit_overview(events)

    assert overview.total_events == 3
    assert overview.events_today == 2
    assert overview.available_backups == 1
    assert overview.configured_backups == 2
    assert overview.latest_summary == "Registro alterado"
    assert ("EDIT", 2) in overview.action_counts
    assert ("IMPORT", 1) in overview.action_counts


def test_audit_service_prefers_sqlite_when_available(tmp_path):
    log_path = tmp_path / "audit" / "events.jsonl"
    sqlite_service = SqliteMirrorService(db_path=tmp_path / "state" / "mirror.db")
    service = AuditService(audit_log_path=log_path, persistence_service=sqlite_service)
    workbook_path = str(tmp_path / "base-a.xlsx")

    service.append_event(
        workbook_path=workbook_path,
        action="edit",
        summary="Registro alterado no SQLite",
        metadata={"uid": "uid-a"},
    )

    events = service.list_events_for_workbook(workbook_path)

    assert len(events) == 1
    assert events[0].summary == "Registro alterado no SQLite"
    assert events[0].metadata["uid"] == "uid-a"


def test_audit_service_falls_back_to_jsonl_when_sqlite_has_no_rows(tmp_path):
    log_path = tmp_path / "audit" / "events.jsonl"
    sqlite_service = SqliteMirrorService(db_path=tmp_path / "state" / "mirror.db")
    service = AuditService(audit_log_path=log_path, persistence_service=sqlite_service)
    workbook_path = str(tmp_path / "base-a.xlsx")

    service_without_sqlite = AuditService(audit_log_path=log_path)
    service_without_sqlite.append_event(
        workbook_path=workbook_path,
        action="import",
        summary="Evento apenas em JSONL",
        metadata={"source": "legacy"},
    )

    events = service.list_events_for_workbook(workbook_path)

    assert len(events) == 1
    assert events[0].summary == "Evento apenas em JSONL"
    assert events[0].metadata["source"] == "legacy"


def service_event(event_id, timestamp, action, summary, backup_path):
    from app.services.audit_service import AuditEvent

    return AuditEvent(
        event_id=event_id,
        timestamp=timestamp,
        workbook_path="C:/tmp/base.xlsx",
        action=action,
        summary=summary,
        backup_path=backup_path,
        metadata={},
    )
