from types import SimpleNamespace

from app.application.use_cases.authoritative_persistence import (
    AuthoritativePersistenceUseCases,
    AuthoritativeSessionLoadResult,
)
from app.application.use_cases.authoritative_write_coordinator import AuthoritativeWriteCoordinator
from app.application.use_cases.local_mutation_sync import (
    LocalMutationApplyResult,
    LocalMutationSyncStatus,
)
from app.application.use_cases.workbook_session import ImportWorkbookAnalysis
from app.models.compensacao import Compensacao
from app.services.access_service import AccessEnvironment, AppAccessSession


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "",
        "compensado": "",
        "latitude": "",
        "longitude": "",
        "uid": "test-uid-123",
    }
    base.update(overrides)
    return Compensacao(**base)


class FakeWorkbook:
    def __init__(self):
        self.path = "base.xlsx"
        self.wb = object()
        self.ws = object()
        self.plantio_ws = object()
        self.col_map = {"uid": 1}
        self.plantio_col_map = {"plantio": 2}
        self.uid_to_row = {"base-uid": 8}
        self.last_backup_time = "2026-03-31T12:00:00+00:00"
        self.merged_cells_warning = None
        self.backup_labels = []
        self.import_calls = []
        self.batch_calls = []
        self.load_calls = []
        self.loaded_records = []

    def create_operation_backup(self, label: str):
        self.backup_labels.append(label)
        return f"C:/tmp/{label}.xlsx"

    def load(self, path: str):
        self.path = path
        self.load_calls.append(path)
        return list(self.loaded_records)

    def import_records_atomic(self, records, *, progress_callback=None):
        copied = list(records)
        self.import_calls.append(copied)
        total = len(copied)
        for index, _record in enumerate(copied, start=1):
            if progress_callback:
                progress_callback(index, total)
        return total

    def save_batch_edits(self, records):
        copied = list(records)
        self.batch_calls.append(copied)
        return len(copied)


class FakeAuditTrail:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.events = []

    def append_event(self, **payload):
        if self.fail:
            raise RuntimeError("audit offline")
        self.events.append(payload)


class FakeImportSync:
    def __init__(self):
        self.sync_calls = []

    def apply_after_import(self, *, workbook_path, existing_records, imported_records):
        return LocalMutationApplyResult(
            status=LocalMutationSyncStatus(
                status="sqlite",
                operation="import",
                workbook_path=workbook_path,
                strategy="incremental",
                record_count=len(existing_records) + len(imported_records),
            ),
            records=tuple([*existing_records, *imported_records]),
            source="sqlite",
        )

    def project_after_import(self, existing_records, imported_records):
        return [*existing_records, *imported_records]

    def sync_projected_records(self, *, workbook_path, records, operation):
        self.sync_calls.append({"workbook_path": workbook_path, "operation": operation, "records": list(records)})
        return LocalMutationSyncStatus(
            status="sqlite",
            operation=operation,
            workbook_path=workbook_path,
            strategy="snapshot_rebuild",
            record_count=len(records),
        )


class FakeProjectedSync:
    def __init__(self):
        self.sync_calls = []

    def sync_projected_records(self, *, workbook_path, records, operation):
        self.sync_calls.append({"workbook_path": workbook_path, "operation": operation, "records": list(records)})
        return LocalMutationSyncStatus(
            status="sqlite",
            operation=operation,
            workbook_path=workbook_path,
            strategy="snapshot_rebuild",
            record_count=len(records),
        )


class FakeSnapshotPersistence:
    def __init__(
        self,
        *,
        fail: bool = False,
        snapshot_records=None,
        synced_at: str = "",
    ):
        self.fail = fail
        self.sync_calls = []
        self.snapshot_records = list(snapshot_records or [])
        self.synced_at = synced_at

    def get_workbook_snapshot_summary(self, workbook_path):
        return SimpleNamespace(
            workbook_path=workbook_path,
            synced_at=self.synced_at,
            record_count=len(self.snapshot_records),
        )

    def list_records_for_workbook(self, workbook_path):
        return list(self.snapshot_records)

    def sync_workbook_snapshot(self, workbook_path, records):
        copied = list(records)
        self.sync_calls.append({"workbook_path": workbook_path, "records": copied})
        if self.fail:
            raise RuntimeError("sqlite busy")
        self.snapshot_records = copied
        self.synced_at = "2026-03-31T12:00:00+00:00"
        return SimpleNamespace(
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            record_count=len(copied),
        )


class FakeMonitoringPersistence:
    def get_workbook_snapshot_summary(self, workbook_path):
        return SimpleNamespace(
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            record_count=4,
            plantio_count=2,
            audit_event_count=2,
        )

    def build_workbook_record_overview(
        self,
        workbook_path,
        *,
        top_microbacias_limit=5,
        sample_limit=5,
    ):
        return SimpleNamespace(
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            total_records=4,
            compensados_count=1,
            pendentes_count=3,
            records_with_plantios_count=2,
            records_without_microbacia_count=1,
            records_without_coordinates_count=1,
            top_microbacias=(("Gregorio", min(int(top_microbacias_limit), 3)),),
            sample_records=(
                SimpleNamespace(
                    excel_row=2,
                    uid="uid-1",
                    av_tec="AT-1",
                    microbacia="Gregorio",
                    compensado="SIM",
                    plantio_count=1,
                ),
            )[: int(sample_limit)],
        )


class FakeRemoteCompensacoesRpcService:
    def __init__(self, *, save_result=None, delete_result=None, replace_result=None):
        self.save_result = save_result or SimpleNamespace(uid="remote-uid", excel_row=9, record_count=2)
        self.delete_result = delete_result or SimpleNamespace(uid="remote-uid", record_count=0)
        self.replace_result = replace_result or SimpleNamespace(record_count=0, imported_count=0)
        self.save_calls = []
        self.delete_calls = []
        self.replace_calls = []

    def save_record(self, client, **kwargs):
        self.save_calls.append({"client": client, **kwargs})
        return self.save_result

    def delete_record(self, client, **kwargs):
        self.delete_calls.append({"client": client, **kwargs})
        return self.delete_result

    def replace_records(self, client, **kwargs):
        self.replace_calls.append({"client": client, **kwargs})
        return self.replace_result


class FakeRemoteSyncService:
    def __init__(self, persistence, *, synced_records=None, fail: bool = False):
        self.persistence = persistence
        self.synced_records = list(synced_records or [])
        self.fail = fail
        self.calls = []

    def sync_authenticated_client(self, client, *, local_db_path=None, session_path=None):
        self.calls.append(
            {
                "client": client,
                "local_db_path": str(local_db_path or ""),
                "session_path": session_path,
            }
        )
        if self.fail:
            raise RuntimeError("remote cache offline")
        self.persistence.sync_workbook_snapshot(session_path, list(self.synced_records))
        return SimpleNamespace(
            local_db_path=str(local_db_path or ""),
            session_path=session_path,
            record_count=len(self.synced_records),
        )


class FakeAccessService:
    def __init__(self, *, client=None, sync_service=None):
        self.client = client or object()
        self.production_sync_service = sync_service
        self.calls = []

    def create_authenticated_client(self, access_session):
        self.calls.append(access_session)
        return self.client


def make_production_session(**overrides) -> AppAccessSession:
    base = {
        "environment": AccessEnvironment.PRODUCTION,
        "label": "Producao",
        "auth_mode": "password",
        "user_id": "user-123",
        "user_email": "analista@prefeitura.sp.gov.br",
        "supabase_url": "https://yonvcnnkewzoqwnnmcdx.supabase.co",
        "local_db_path": "C:/tmp/producao.db",
        "local_session_path": "session://banco-local",
        "app_role": "editor",
        "access_token": "token",
        "refresh_token": "refresh-token",
    }
    base.update(overrides)
    return AppAccessSession(**base)


def test_execute_import_keeps_success_when_audit_append_fails():
    workbook = FakeWorkbook()
    audit = FakeAuditTrail(fail=True)
    service = AuthoritativePersistenceUseCases(workbook, audit, None, loader_factory=lambda: workbook)
    fake_sync = FakeImportSync()
    service.local_mutation_sync = fake_sync
    service.authoritative_write = AuthoritativeWriteCoordinator(fake_sync)

    existing = [make_record(uid="base-uid", excel_row=8, av_tec="AT-BASE")]
    imported = [make_record(uid="", excel_row=0, av_tec="AT-NOVO")]
    analysis = ImportWorkbookAnalysis(
        import_path="C:/dados/importar.xlsx",
        incoming_records=list(imported),
        records_to_add=list(imported),
        skipped_by_uid=0,
        skipped_by_av_tec=0,
        skipped_uid_details=[],
        skipped_av_tec_details=[],
        invalid_issues=[],
    )

    result = service.execute_import(analysis, base_records=existing)

    assert result.excel_result is not None
    assert result.excel_result.imported_count == 1
    assert result.excel_result.backup_path.endswith(".json")
    assert result.write_status.status == "sqlite_authoritative"
    assert "audit offline" in " | ".join(result.write_status.issues)
    assert fake_sync.sync_calls == []


def test_load_session_alias_returns_session_result():
    workbook = FakeWorkbook()
    workbook.loaded_records = [make_record(uid="sessao-1", excel_row=9)]
    audit = FakeAuditTrail()
    persistence = FakeSnapshotPersistence()
    service = AuthoritativePersistenceUseCases(workbook, audit, persistence, loader_factory=lambda: workbook)

    result = service.load_session("C:/dados/sessao-base.xlsx")

    assert isinstance(result, AuthoritativeSessionLoadResult)
    assert result.session_path == "C:/dados/sessao-base.xlsx"
    assert [record.uid for record in result.records] == ["sessao-1"]
    assert workbook.load_calls == ["C:/dados/sessao-base.xlsx"]


def test_execute_batch_geocode_appends_audit_event():
    workbook = FakeWorkbook()
    audit = FakeAuditTrail()
    service = AuthoritativePersistenceUseCases(workbook, audit, None)
    fake_sync = FakeProjectedSync()
    service.local_mutation_sync = fake_sync
    service.authoritative_write = AuthoritativeWriteCoordinator(fake_sync)

    authoritative_records = [make_record(uid="geo-1", excel_row=12, av_tec="AT-GEO")]
    projected_record = make_record(
        uid="geo-1",
        excel_row=12,
        av_tec="AT-GEO",
        latitude="-22.01",
        longitude="-47.89",
        microbacia="Gregorio",
    )

    result = service.execute_batch_geocode(
        authoritative_records=authoritative_records,
        projected_records=[projected_record],
        updated_records=[projected_record],
    )

    assert len(fake_sync.sync_calls) == 1
    assert fake_sync.sync_calls[0]["operation"] == "batch_geocode"
    assert result.excel_result == 1
    assert result.write_status.status == "sqlite_authoritative"
    assert result.write_status.issues == ()
    assert len(audit.events) == 1
    assert audit.events[0]["action"] == "batch_geocode"
    assert audit.events[0]["backup_path"].endswith("batch_geocode.json")
    assert audit.events[0]["metadata"]["updated_records"] == 1


def test_load_workbook_syncs_snapshot_before_reloading_runtime_session_from_sqlite():
    workbook = FakeWorkbook()
    workbook.loaded_records = [make_record(uid="excel-uid", av_tec="AT-EXCEL")]
    audit = FakeAuditTrail()
    persistence_reader = FakeSnapshotPersistence()
    service = AuthoritativePersistenceUseCases(workbook, audit, persistence_reader, loader_factory=lambda: workbook)

    result = service.load_workbook("C:/dados/base.xlsx")

    assert workbook.load_calls == ["C:/dados/base.xlsx"]
    assert persistence_reader.sync_calls[0]["workbook_path"] == "C:/dados/base.xlsx"
    assert persistence_reader.sync_calls[0]["records"][0].uid == "excel-uid"
    assert [record.uid for record in result.records] == ["excel-uid"]
    assert result.local_session_source_status.source == "sqlite"
    assert result.local_session_source_status.strategy == "sqlite_runtime"
    assert result.issues == ()


def test_load_workbook_falls_back_to_session_when_snapshot_sync_fails(monkeypatch):
    workbook = FakeWorkbook()
    workbook.loaded_records = [make_record(uid="excel-uid", av_tec="AT-EXCEL")]
    audit = FakeAuditTrail()
    persistence_reader = FakeSnapshotPersistence(fail=True)
    service = AuthoritativePersistenceUseCases(workbook, audit, persistence_reader, loader_factory=lambda: workbook)

    monkeypatch.setattr(
        service.local_record_queries,
        "resolve_record_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("nao deveria consultar snapshot stale")),
    )

    result = service.load_workbook("C:/dados/base.xlsx")

    assert [record.uid for record in result.records] == ["excel-uid"]
    assert result.local_session_source_status.source == "session"
    assert "sqlite busy" in " | ".join(result.issues)


def test_snapshot_and_restore_workbook_service_state():
    workbook = FakeWorkbook()
    audit = FakeAuditTrail()
    service = AuthoritativePersistenceUseCases(workbook, audit, None, loader_factory=lambda: workbook)

    snapshot = service.snapshot_workbook_service_state()

    workbook.path = "alterado.xlsx"
    workbook.wb = None
    workbook.ws = None
    workbook.plantio_ws = None
    workbook.col_map = {}
    workbook.plantio_col_map = {}
    workbook.uid_to_row = {}
    workbook.last_backup_time = None
    workbook.merged_cells_warning = "warn"

    service.restore_workbook_service_state(snapshot)

    assert workbook.path == "base.xlsx"
    assert workbook.wb is snapshot.wb
    assert workbook.ws is snapshot.ws
    assert workbook.plantio_ws is snapshot.plantio_ws
    assert workbook.col_map == {"uid": 1}
    assert workbook.plantio_col_map == {"plantio": 2}
    assert workbook.uid_to_row == {"base-uid": 8}
    assert workbook.last_backup_time == "2026-03-31T12:00:00+00:00"
    assert workbook.merged_cells_warning is None


def test_set_persistence_service_rebinds_monitoring_snapshot_reader():
    workbook = FakeWorkbook()
    audit = FakeAuditTrail()
    service = AuthoritativePersistenceUseCases(workbook, audit, None, loader_factory=lambda: workbook)
    swapped = FakeMonitoringPersistence()

    service.set_persistence_service(swapped)

    assert service.persistence_monitoring_use_cases.snapshot_reader is swapped


def test_resolve_monitoring_snapshot_uses_shared_monitoring_gateway():
    workbook = FakeWorkbook()
    audit = FakeAuditTrail()
    service = AuthoritativePersistenceUseCases(
        workbook,
        audit,
        FakeMonitoringPersistence(),
        loader_factory=lambda: workbook,
    )

    snapshot = service.resolve_monitoring_snapshot(
        "C:/dados/base.xlsx",
        expected_records=4,
        expected_audit_events=2,
        top_microbacias_limit=3,
        sample_limit=1,
    )

    assert snapshot.workbook_path == "C:/dados/base.xlsx"
    assert snapshot.persistence_report.status == "sincronizado"
    assert snapshot.persistence_report.mirrored_records == 4
    assert snapshot.persistence_report.expected_audit_events == 2
    assert snapshot.record_overview_report is not None
    assert snapshot.record_overview_report.total_records == 4
    assert snapshot.record_overview_report.top_microbacias == (("Gregorio", 3),)
    assert snapshot.record_overview_report.sample_records[0].uid == "uid-1"


def test_execute_add_uses_supabase_remote_write_in_production():
    workbook = FakeWorkbook()
    workbook.path = "session://banco-local"
    audit = FakeAuditTrail()
    existing = make_record(uid="base-uid", excel_row=8, av_tec="AT-BASE")
    remote_added = make_record(uid="remote-uid", excel_row=9, av_tec="AT-NOVO")
    persistence = FakeSnapshotPersistence(snapshot_records=[existing], synced_at="2026-03-31T12:00:00+00:00")
    remote_sync = FakeRemoteSyncService(persistence, synced_records=[existing, remote_added])
    access_service = FakeAccessService(sync_service=remote_sync)
    remote_rpc = FakeRemoteCompensacoesRpcService(
        save_result=SimpleNamespace(uid="remote-uid", excel_row=9, record_count=2)
    )
    service = AuthoritativePersistenceUseCases(
        workbook,
        audit,
        persistence,
        loader_factory=lambda: workbook,
        access_service=access_service,
        remote_compensacoes_service=remote_rpc,
    )
    service.access_session = make_production_session()

    result = service.execute_add(
        make_record(uid="", excel_row=0, av_tec="AT-NOVO"),
        authoritative_records=[existing],
    )

    assert len(remote_rpc.save_calls) == 1
    assert remote_rpc.save_calls[0]["workbook_path"] == "session://banco-local"
    assert len(remote_sync.calls) == 1
    assert remote_sync.calls[0]["session_path"] == "session://banco-local"
    assert result.write_status.status == "remote_authoritative"
    assert result.status.strategy == "remote_snapshot_refresh"
    assert [record.uid for record in result.records] == ["base-uid", "remote-uid"]
    assert audit.events == []


def test_execute_edit_falls_back_to_local_cache_sync_when_remote_refresh_fails():
    workbook = FakeWorkbook()
    workbook.path = "session://banco-local"
    audit = FakeAuditTrail()
    existing = make_record(uid="base-uid", excel_row=8, av_tec="AT-BASE")
    updated = make_record(uid="base-uid", excel_row=8, av_tec="AT-EDIT")
    persistence = FakeSnapshotPersistence(snapshot_records=[existing], synced_at="2026-03-31T12:00:00+00:00")
    remote_sync = FakeRemoteSyncService(persistence, synced_records=[updated], fail=True)
    access_service = FakeAccessService(sync_service=remote_sync)
    remote_rpc = FakeRemoteCompensacoesRpcService(
        save_result=SimpleNamespace(uid="base-uid", excel_row=8, record_count=1)
    )
    service = AuthoritativePersistenceUseCases(
        workbook,
        audit,
        persistence,
        loader_factory=lambda: workbook,
        access_service=access_service,
        remote_compensacoes_service=remote_rpc,
    )
    service.access_session = make_production_session()

    result = service.execute_edit(
        updated,
        authoritative_records=[existing],
        before_record=existing,
    )

    assert len(remote_rpc.save_calls) == 1
    assert result.write_status.status == "remote_authoritative"
    assert result.status.strategy == "snapshot_rebuild"
    assert "cache local" in " | ".join(result.write_status.issues).lower()
    assert persistence.snapshot_records[0].av_tec == "AT-EDIT"


def test_execute_delete_keeps_local_authority_outside_production():
    workbook = FakeWorkbook()
    workbook.path = "session://banco-local"
    audit = FakeAuditTrail()
    existing = make_record(uid="base-uid", excel_row=8, av_tec="AT-BASE")
    persistence = FakeSnapshotPersistence(snapshot_records=[existing], synced_at="2026-03-31T12:00:00+00:00")
    remote_rpc = FakeRemoteCompensacoesRpcService()
    service = AuthoritativePersistenceUseCases(
        workbook,
        audit,
        persistence,
        loader_factory=lambda: workbook,
        access_service=FakeAccessService(sync_service=FakeRemoteSyncService(persistence)),
        remote_compensacoes_service=remote_rpc,
    )

    result = service.execute_delete(
        existing,
        authoritative_records=[existing],
    )

    assert result.write_status.status == "sqlite_authoritative"
    assert remote_rpc.delete_calls == []
