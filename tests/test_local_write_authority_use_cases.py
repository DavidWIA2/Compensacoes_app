from app.application.use_cases.local_write_authority import LocalWriteAuthorityUseCases
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


class StubLocalWriteReader:
    def __init__(self, *, summary: WorkbookSnapshotSummary, records: list[Compensacao]):
        self.summary = summary
        self.records = list(records)

    def get_workbook_snapshot_summary(self, workbook_path: str) -> WorkbookSnapshotSummary:
        return self.summary

    def list_records_for_workbook(self, workbook_path: str) -> list[Compensacao]:
        return list(self.records)

    def find_record_by_uid_for_workbook(self, workbook_path: str, uid: str) -> Compensacao | None:
        for record in self.records:
            if record.uid == uid:
                return record
        return None

    def find_record_by_excel_row_for_workbook(self, workbook_path: str, excel_row: int) -> Compensacao | None:
        for record in self.records:
            if int(record.excel_row or 0) == int(excel_row or 0):
                return record
        return None

    def find_duplicate_av_tec_for_workbook(
        self,
        workbook_path: str,
        *,
        av_tec: str,
        current_uid: str = "",
    ) -> int | None:
        target = str(av_tec or "").strip().upper()
        for record in self.records:
            if current_uid and record.uid == current_uid:
                continue
            if str(record.av_tec or "").strip().upper() == target:
                return int(record.excel_row or 0) or None
        return None


def test_local_write_authority_prepare_create_uses_sqlite_base_and_duplicate_lookup(tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("snapshot-base", encoding="utf-8")
    stat_result = workbook_path.stat()
    sqlite_records = [
        make_record(uid="u-1", excel_row=2, av_tec="AT-1"),
        make_record(uid="u-2", excel_row=3, av_tec="AT-2"),
    ]
    session_records = [make_record(uid="session-only", excel_row=99, av_tec="AT-X")]
    use_cases = LocalWriteAuthorityUseCases(
        StubLocalWriteReader(
            summary=WorkbookSnapshotSummary(
                workbook_path=str(workbook_path),
                synced_at="2026-04-01T12:00:00+00:00",
                record_count=2,
                plantio_count=0,
                audit_event_count=0,
                source_mtime_ns=stat_result.st_mtime_ns,
                source_size=stat_result.st_size,
            ),
            records=sqlite_records,
        )
    )

    preparation = use_cases.prepare_create(
        str(workbook_path),
        fallback_records=session_records,
        draft_record=make_record(uid="", excel_row=-1, av_tec="AT-2"),
    )

    assert preparation.uses_sqlite is True
    assert [record.uid for record in preparation.base_records] == ["u-1", "u-2"]
    assert preparation.duplicate_row == 3
    assert preparation.issues


def test_local_write_authority_prepare_update_returns_effective_record_with_authoritative_identity(tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("snapshot-base", encoding="utf-8")
    stat_result = workbook_path.stat()
    sqlite_records = [
        make_record(uid="u-1", excel_row=2, av_tec="AT-1"),
        make_record(uid="u-2", excel_row=5, av_tec="AT-2", endereco="SQLite"),
    ]
    session_selected = make_record(uid="u-2", excel_row=99, av_tec="AT-2", endereco="Sessao")
    use_cases = LocalWriteAuthorityUseCases(
        StubLocalWriteReader(
            summary=WorkbookSnapshotSummary(
                workbook_path=str(workbook_path),
                synced_at="2026-04-01T12:00:00+00:00",
                record_count=2,
                plantio_count=0,
                audit_event_count=0,
                source_mtime_ns=stat_result.st_mtime_ns,
                source_size=stat_result.st_size,
            ),
            records=sqlite_records,
        )
    )

    preparation = use_cases.prepare_update(
        str(workbook_path),
        fallback_records=[session_selected],
        fallback_selected=session_selected,
        draft_record=make_record(uid="u-2", excel_row=99, av_tec="AT-2", endereco="Rua Nova"),
    )

    assert preparation.uses_sqlite is True
    assert preparation.selected_record is not None
    assert preparation.selected_record.excel_row == 5
    assert preparation.effective_record is not None
    assert preparation.effective_record.uid == "u-2"
    assert preparation.effective_record.excel_row == 5
    assert preparation.effective_record.endereco == "Rua Nova"
    assert preparation.duplicate_row is None


def test_local_write_authority_prepare_delete_uses_authoritative_selected_record(tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("snapshot-base", encoding="utf-8")
    stat_result = workbook_path.stat()
    sqlite_records = [
        make_record(uid="u-1", excel_row=2, av_tec="AT-1"),
        make_record(uid="u-2", excel_row=4, av_tec="AT-2"),
    ]
    session_selected = make_record(uid="u-2", excel_row=99, av_tec="AT-2")
    use_cases = LocalWriteAuthorityUseCases(
        StubLocalWriteReader(
            summary=WorkbookSnapshotSummary(
                workbook_path=str(workbook_path),
                synced_at="2026-04-01T12:00:00+00:00",
                record_count=2,
                plantio_count=0,
                audit_event_count=0,
                source_mtime_ns=stat_result.st_mtime_ns,
                source_size=stat_result.st_size,
            ),
            records=sqlite_records,
        )
    )

    preparation = use_cases.prepare_delete(
        str(workbook_path),
        fallback_records=[session_selected],
        fallback_selected=session_selected,
    )

    assert preparation.uses_sqlite is True
    assert preparation.selected_record is not None
    assert preparation.selected_record.uid == "u-2"
    assert preparation.selected_record.excel_row == 4
    assert [record.uid for record in preparation.base_records] == ["u-1", "u-2"]


def test_local_write_authority_prepare_base_falls_back_when_workbook_changes_after_snapshot(tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("versao-1", encoding="utf-8")
    stat_result = workbook_path.stat()
    session_records = [make_record(uid="u-1", excel_row=2, av_tec="AT-1")]
    use_cases = LocalWriteAuthorityUseCases(
        StubLocalWriteReader(
            summary=WorkbookSnapshotSummary(
                workbook_path=str(workbook_path),
                synced_at="2026-04-01T12:00:00+00:00",
                record_count=1,
                plantio_count=0,
                audit_event_count=0,
                source_mtime_ns=stat_result.st_mtime_ns,
                source_size=stat_result.st_size,
            ),
            records=[make_record(uid="u-sqlite", excel_row=5, av_tec="AT-SQLITE")],
        )
    )

    workbook_path.write_text("versao-2-com-tamanho-diferente", encoding="utf-8")

    preparation = use_cases.prepare_base(
        str(workbook_path),
        fallback_records=session_records,
    )

    assert preparation.uses_sqlite is False
    assert [record.uid for record in preparation.base_records] == ["u-1"]
    assert preparation.issues == ("Arquivo foi alterado desde a ultima sincronizacao do espelho local.",)
