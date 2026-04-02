from app.application.use_cases.local_mutation_sync import LocalMutationSyncUseCases
from app.models.compensacao import Compensacao
from app.services.sqlite_mirror_service import WorkbookSnapshotSummary


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
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


class StubSnapshotWriter:
    def __init__(self):
        self.calls = []
        self.records_by_workbook = {}

    def sync_workbook_snapshot(self, workbook_path, records):
        self.calls.append(("snapshot", workbook_path, list(records)))
        self.records_by_workbook[workbook_path] = list(records)
        return WorkbookSnapshotSummary(
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            record_count=len(records),
            plantio_count=0,
            audit_event_count=0,
        )

    def append_record_to_workbook(self, workbook_path, record):
        self.calls.append(("add", workbook_path, record.uid))
        current = list(self.records_by_workbook.get(workbook_path, [make_record(uid="u-1", av_tec="AT-1")]))
        current.append(record)
        self.records_by_workbook[workbook_path] = current
        return WorkbookSnapshotSummary(
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            record_count=2,
            plantio_count=0,
            audit_event_count=0,
        )

    def append_records_to_workbook(self, workbook_path, records):
        self.calls.append(("import", workbook_path, [record.uid for record in records]))
        current = list(self.records_by_workbook.get(workbook_path, [make_record(uid="u-1", av_tec="AT-1")]))
        current.extend(records)
        self.records_by_workbook[workbook_path] = current
        return WorkbookSnapshotSummary(
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            record_count=len(records) + 1,
            plantio_count=0,
            audit_event_count=0,
        )

    def update_record_in_workbook(self, workbook_path, record):
        self.calls.append(("edit", workbook_path, record.uid))
        current = list(self.records_by_workbook.get(workbook_path, [make_record(uid="u-1", av_tec="AT-1")]))
        updated = []
        replaced = False
        for existing in current:
            if existing.uid == record.uid:
                updated.append(record)
                replaced = True
            else:
                updated.append(existing)
        if not replaced:
            updated.append(record)
        self.records_by_workbook[workbook_path] = updated
        return WorkbookSnapshotSummary(
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            record_count=1,
            plantio_count=0,
            audit_event_count=0,
        )

    def delete_record_from_workbook(self, workbook_path, record):
        self.calls.append(("delete", workbook_path, record.uid))
        current = list(self.records_by_workbook.get(workbook_path, []))
        updated = [existing for existing in current if existing.uid != record.uid]
        for index, existing in enumerate(updated, start=2):
            existing.excel_row = index
        self.records_by_workbook[workbook_path] = updated
        return WorkbookSnapshotSummary(
            workbook_path=workbook_path,
            synced_at="2026-03-31T12:00:00+00:00",
            record_count=len(updated),
            plantio_count=0,
            audit_event_count=0,
        )

    def list_records_for_workbook(self, workbook_path):
        return list(self.records_by_workbook.get(workbook_path, []))


def test_local_mutation_sync_projects_delete_and_resequences_rows():
    use_cases = LocalMutationSyncUseCases(None)
    records = [
        make_record(excel_row=2, uid="u-1", av_tec="AT-1"),
        make_record(excel_row=3, uid="u-2", av_tec="AT-2"),
        make_record(excel_row=4, uid="u-3", av_tec="AT-3"),
    ]

    projected = use_cases.project_after_delete(records, records[1])

    assert [record.uid for record in projected] == ["u-1", "u-3"]
    assert [record.excel_row for record in projected] == [2, 3]


def test_local_mutation_sync_updates_sqlite_after_import_projection():
    writer = StubSnapshotWriter()
    use_cases = LocalMutationSyncUseCases(writer)
    existing = [make_record(excel_row=2, uid="u-1", av_tec="AT-1")]
    imported = [make_record(excel_row=3, uid="u-2", av_tec="AT-2")]

    status = use_cases.sync_after_import(
        workbook_path="C:/tmp/base.xlsx",
        existing_records=existing,
        imported_records=imported,
    )

    assert status.status == "sqlite"
    assert status.operation == "import"
    assert status.record_count == 2
    assert status.strategy == "incremental"
    assert writer.calls[0] == ("import", "C:/tmp/base.xlsx", ["u-2"])


def test_local_mutation_sync_prefers_incremental_sqlite_write_for_single_record():
    writer = StubSnapshotWriter()
    use_cases = LocalMutationSyncUseCases(writer)

    status = use_cases.sync_after_edit(
        workbook_path="C:/tmp/base.xlsx",
        existing_records=[make_record(uid="u-1")],
        updated_record=make_record(uid="u-1", endereco="Rua B"),
    )

    assert status.status == "sqlite"
    assert status.strategy == "incremental"
    assert writer.calls[0] == ("edit", "C:/tmp/base.xlsx", "u-1")


def test_local_mutation_sync_apply_after_edit_uses_sqlite_runtime_records():
    writer = StubSnapshotWriter()
    writer.records_by_workbook["C:/tmp/base.xlsx"] = [make_record(uid="u-1", endereco="Rua A")]
    use_cases = LocalMutationSyncUseCases(writer)

    result = use_cases.apply_after_edit(
        workbook_path="C:/tmp/base.xlsx",
        existing_records=[make_record(uid="u-1", endereco="Sessao Stale")],
        updated_record=make_record(uid="u-1", endereco="Rua B"),
    )

    assert result.source == "sqlite"
    assert result.status.status == "sqlite"
    assert result.status.strategy == "incremental"
    assert len(result.records) == 1
    assert result.records[0].endereco == "Rua B"


def test_local_mutation_sync_apply_after_add_falls_back_to_projection_when_sqlite_read_fails():
    class ReadFailingWriter(StubSnapshotWriter):
        def list_records_for_workbook(self, workbook_path):
            raise RuntimeError("sqlite read offline")

    writer = ReadFailingWriter()
    use_cases = LocalMutationSyncUseCases(writer)
    existing = [make_record(uid="u-1", av_tec="AT-1")]
    added = make_record(excel_row=3, uid="u-2", av_tec="AT-2")

    result = use_cases.apply_after_add(
        workbook_path="C:/tmp/base.xlsx",
        existing_records=existing,
        added_record=added,
    )

    assert result.source == "projection"
    assert result.status.status == "sqlite"
    assert result.status.strategy == "incremental"
    assert result.status.issues[-1] == "Leitura pos-mutacao do espelho local falhou: sqlite read offline"
    assert [record.uid for record in result.records] == ["u-1", "u-2"]


def test_local_mutation_sync_falls_back_to_snapshot_rebuild_when_incremental_write_fails():
    class PartiallyFailingWriter(StubSnapshotWriter):
        def append_record_to_workbook(self, workbook_path, record):
            raise RuntimeError("incremental offline")

    writer = PartiallyFailingWriter()
    use_cases = LocalMutationSyncUseCases(writer)

    status = use_cases.sync_after_add(
        workbook_path="C:/tmp/base.xlsx",
        existing_records=[make_record(uid="u-1")],
        added_record=make_record(excel_row=3, uid="u-2", av_tec="AT-2"),
    )

    assert status.status == "sqlite"
    assert status.strategy == "snapshot_rebuild"
    assert status.issues == ("Sincronizacao incremental falhou: incremental offline",)
    assert writer.calls[0][0] == "snapshot"
    assert [record.uid for record in writer.calls[0][2]] == ["u-1", "u-2"]


def test_local_mutation_sync_reports_failure_without_writer_crash():
    class FailingWriter:
        def sync_workbook_snapshot(self, workbook_path, records):
            raise RuntimeError("sqlite offline")

    use_cases = LocalMutationSyncUseCases(FailingWriter())

    status = use_cases.sync_after_add(
        workbook_path="C:/tmp/base.xlsx",
        existing_records=[make_record(uid="u-1")],
        added_record=make_record(excel_row=3, uid="u-2", av_tec="AT-2"),
    )

    assert status.status == "falha"
    assert status.operation == "add"
    assert status.issues
