import pytest

from app.application.use_cases.authoritative_write_coordinator import (
    AuthoritativeWriteCoordinator,
    AuthoritativeWriteError,
)
from app.application.use_cases.local_mutation_sync import (
    LocalMutationApplyResult,
    LocalMutationSyncStatus,
)
from app.models.compensacao import Compensacao


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


class FakeLocalMutationSync:
    def __init__(self):
        self.sync_calls = []

    def sync_projected_records(self, *, workbook_path, records, operation):
        self.sync_calls.append(
            {
                "workbook_path": workbook_path,
                "operation": operation,
                "records": list(records),
            }
        )
        return LocalMutationSyncStatus(
            status="sqlite",
            operation=operation,
            workbook_path=workbook_path,
            strategy="snapshot_rebuild",
            record_count=len(records),
        )


def test_execute_sqlite_first_rolls_back_sqlite_when_excel_write_fails():
    sync = FakeLocalMutationSync()
    coordinator = AuthoritativeWriteCoordinator(sync)
    base_records = [make_record(uid="base-uid", excel_row=8)]
    projected_records = tuple([*base_records, make_record(uid="added-uid", excel_row=9)])

    with pytest.raises(AuthoritativeWriteError) as exc_info:
        coordinator.execute_sqlite_first(
            workbook_path="base.xlsx",
            operation="add",
            base_records=base_records,
            sqlite_apply=lambda: LocalMutationApplyResult(
                status=LocalMutationSyncStatus(
                    status="sqlite",
                    operation="add",
                    workbook_path="base.xlsx",
                    strategy="incremental",
                    record_count=len(projected_records),
                ),
                records=projected_records,
                source="sqlite",
            ),
            excel_write=lambda: (_ for _ in ()).throw(RuntimeError("excel exploded")),
        )

    assert str(exc_info.value) == "excel exploded"
    assert exc_info.value.write_status.status == "rolled_back_after_excel_failure"
    assert exc_info.value.write_status.rollback_applied is True
    assert "excel exploded" in " | ".join(exc_info.value.write_status.issues)

    assert len(sync.sync_calls) == 1
    assert sync.sync_calls[0]["operation"] == "add_rollback"
    assert [record.uid for record in sync.sync_calls[0]["records"]] == ["base-uid"]


def test_execute_sqlite_first_finalizes_sqlite_when_excel_identity_changes():
    sync = FakeLocalMutationSync()
    coordinator = AuthoritativeWriteCoordinator(sync)
    base_records = [make_record(uid="base-uid", excel_row=8)]
    provisional_record = make_record(uid="added-uid", excel_row=9, av_tec="AT-NEW")
    finalized_record = make_record(uid="added-uid", excel_row=12, av_tec="AT-NEW")

    result = coordinator.execute_sqlite_first(
        workbook_path="base.xlsx",
        operation="add",
        base_records=base_records,
        sqlite_apply=lambda: LocalMutationApplyResult(
            status=LocalMutationSyncStatus(
                status="sqlite",
                operation="add",
                workbook_path="base.xlsx",
                strategy="incremental",
                record_count=2,
            ),
            records=tuple([*base_records, provisional_record]),
            source="sqlite",
        ),
        excel_write=lambda: 12,
        finalized_records_factory=lambda: [*base_records, finalized_record],
    )

    assert result.finalized is True
    assert result.excel_result == 12
    assert result.write_status.status == "sqlite_primary"
    assert result.write_status.finalized is True
    assert [record.excel_row for record in result.records] == [8, 12]
    assert len(sync.sync_calls) == 1
    assert sync.sync_calls[0]["operation"] == "add_finalize"
    assert [record.excel_row for record in sync.sync_calls[0]["records"]] == [8, 12]
