from app.application.use_cases.local_record_queries import LocalRecordQueriesUseCases
from app.models.compensacao import Compensacao
from app.services.sqlite_mirror_service import WorkbookFilterFacets, WorkbookSnapshotSummary


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
        "latitude": "",
        "longitude": "",
        "uid": "uid-1",
    }
    base.update(overrides)
    return Compensacao(**base)


class StubLocalRecordReader:
    def __init__(self, *, summary: WorkbookSnapshotSummary, records: list[Compensacao]):
        self.summary = summary
        self.records = records
        self.query_calls = []
        self.metrics_calls = []

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

    def query_filter_facets_for_workbook(self, workbook_path: str) -> WorkbookFilterFacets:
        years = tuple(
            sorted(
                {
                    str(record.oficio_processo).split("/")[-1]
                    for record in self.records
                    if "/" in str(record.oficio_processo)
                },
                reverse=True,
            )
        )
        micros = tuple(sorted({str(record.microbacia or "").strip() for record in self.records if str(record.microbacia or "").strip()}))
        return WorkbookFilterFacets(
            workbook_path=workbook_path,
            synced_at=self.summary.synced_at,
            record_count=self.summary.record_count,
            microbacias=micros,
            years=years,
        )

    def query_records_for_workbook(
        self,
        workbook_path: str,
        *,
        search_text: str = "",
        status: str = "Todos",
        selected_micros=(),
        selected_eletronicos=(),
        micro_all_selected: bool = True,
        eletronico_all_selected: bool = True,
        selected_year: str = "Todos",
    ) -> list[Compensacao]:
        self.query_calls.append(
            {
                "workbook_path": workbook_path,
                "search_text": search_text,
                "status": status,
                "selected_micros": tuple(selected_micros),
                "selected_eletronicos": tuple(selected_eletronicos),
                "micro_all_selected": micro_all_selected,
                "eletronico_all_selected": eletronico_all_selected,
                "selected_year": selected_year,
            }
        )
        return [
            record
            for record in self.records
            if search_text.lower() in record.oficio_processo.lower()
        ]

    def query_metrics_for_workbook(
        self,
        workbook_path: str,
        *,
        search_text: str = "",
        status: str = "Todos",
        selected_micros=(),
        selected_eletronicos=(),
        micro_all_selected: bool = True,
        eletronico_all_selected: bool = True,
        selected_year: str = "Todos",
    ) -> dict[str, object]:
        self.metrics_calls.append(
            {
                "workbook_path": workbook_path,
                "search_text": search_text,
                "status": status,
                "selected_micros": tuple(selected_micros),
                "selected_eletronicos": tuple(selected_eletronicos),
                "micro_all_selected": micro_all_selected,
                "eletronico_all_selected": eletronico_all_selected,
                "selected_year": selected_year,
            }
        )
        matched = [
            record
            for record in self.records
            if search_text.lower() in record.oficio_processo.lower()
        ]
        return {
            "total_geral": float(len(matched) * 10),
            "total_pendente": float(len(matched) * 10),
            "total_compensado": 0.0,
            "count_total": len(matched),
            "count_comp": 0,
            "count_pend": len(matched),
            "pend_micro_sorted": [("Gregorio", float(len(matched) * 10))] if matched else [],
            "pend_ele_sorted": [("Eletrônico", float(len(matched) * 10))] if matched else [],
        }


def test_local_record_queries_prefers_sqlite_when_snapshot_matches_session():
    session_records = [make_record(uid="u-1"), make_record(excel_row=3, uid="u-2", av_tec="AT-2")]
    use_cases = LocalRecordQueriesUseCases(
        StubLocalRecordReader(
            summary=WorkbookSnapshotSummary(
                workbook_path="C:/tmp/base.xlsx",
                synced_at="2026-03-31T12:00:00+00:00",
                record_count=2,
                plantio_count=0,
                audit_event_count=0,
            ),
            records=session_records,
        )
    )

    result = use_cases.resolve_record_source("C:/tmp/base.xlsx", fallback_records=session_records)

    assert result.uses_sqlite is True
    assert len(result.records) == 2
    assert result.mirrored_records == 2
    assert result.session_records == 2
    assert result.issues == ()


def test_local_record_queries_falls_back_when_snapshot_diverges():
    session_records = [make_record(uid="u-1"), make_record(excel_row=3, uid="u-2", av_tec="AT-2")]
    use_cases = LocalRecordQueriesUseCases(
        StubLocalRecordReader(
            summary=WorkbookSnapshotSummary(
                workbook_path="C:/tmp/base.xlsx",
                synced_at="2026-03-31T12:00:00+00:00",
                record_count=1,
                plantio_count=0,
                audit_event_count=0,
            ),
            records=[make_record(uid="u-1")],
        )
    )

    result = use_cases.resolve_record_source("C:/tmp/base.xlsx", fallback_records=session_records)

    assert result.source == "session"
    assert len(result.records) == 2
    assert result.mirrored_records == 1
    assert result.issues


def test_local_record_queries_can_resolve_authoritative_base_from_sqlite_even_when_session_diverges(tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("snapshot-base", encoding="utf-8")
    sqlite_records = [
        make_record(uid="u-1"),
        make_record(excel_row=3, uid="u-2", av_tec="AT-2"),
    ]
    session_records = [make_record(uid="session-only", av_tec="AT-SESSION")]
    stat_result = workbook_path.stat()
    use_cases = LocalRecordQueriesUseCases(
        StubLocalRecordReader(
            summary=WorkbookSnapshotSummary(
                workbook_path=str(workbook_path),
                synced_at="2026-03-31T12:00:00+00:00",
                record_count=2,
                plantio_count=0,
                audit_event_count=0,
                source_mtime_ns=stat_result.st_mtime_ns,
                source_size=stat_result.st_size,
            ),
            records=sqlite_records,
        )
    )

    result = use_cases.resolve_authoritative_record_source(
        str(workbook_path),
        fallback_records=session_records,
    )

    assert result.source == "sqlite"
    assert result.strategy == "sqlite_authoritative_base"
    assert [record.uid for record in result.records] == ["u-1", "u-2"]
    assert result.session_records == 1
    assert result.mirrored_records == 2
    assert result.issues


def test_local_record_queries_builds_runtime_status_for_sqlite_and_fallback():
    session_records = [make_record(uid="u-1"), make_record(excel_row=3, uid="u-2", av_tec="AT-2")]
    sqlite_use_cases = LocalRecordQueriesUseCases(
        StubLocalRecordReader(
            summary=WorkbookSnapshotSummary(
                workbook_path="C:/tmp/base.xlsx",
                synced_at="2026-03-31T12:00:00+00:00",
                record_count=2,
                plantio_count=0,
                audit_event_count=0,
            ),
            records=session_records,
        )
    )
    sqlite_result = sqlite_use_cases.resolve_record_source("C:/tmp/base.xlsx", fallback_records=session_records)
    sqlite_status = sqlite_use_cases.build_read_status(sqlite_result, filtered_records=1)

    assert sqlite_status.status == "sqlite"
    assert sqlite_status.uses_sqlite is True
    assert sqlite_status.strategy == "sqlite_snapshot"
    assert sqlite_status.filtered_records == 1

    fallback_use_cases = LocalRecordQueriesUseCases(
        StubLocalRecordReader(
            summary=WorkbookSnapshotSummary(
                workbook_path="C:/tmp/base.xlsx",
                synced_at="2026-03-31T12:00:00+00:00",
                record_count=1,
                plantio_count=0,
                audit_event_count=0,
            ),
            records=[make_record(uid="u-1")],
        )
    )
    fallback_result = fallback_use_cases.resolve_record_source(
        "C:/tmp/base.xlsx",
        fallback_records=session_records,
    )
    fallback_status = fallback_use_cases.build_read_status(fallback_result, filtered_records=2)

    assert fallback_status.status == "fallback"
    assert fallback_status.uses_sqlite is False
    assert fallback_status.strategy == "session_filter"
    assert fallback_status.filtered_records == 2
    assert fallback_status.issues


def test_local_record_queries_can_use_indexed_sqlite_query_for_filtered_result():
    session_records = [make_record(oficio_processo="ABC-1", uid="u-1"), make_record(oficio_processo="XYZ-2", uid="u-2")]
    reader = StubLocalRecordReader(
        summary=WorkbookSnapshotSummary(
            workbook_path="C:/tmp/base.xlsx",
            synced_at="2026-03-31T12:00:00+00:00",
            record_count=2,
            plantio_count=0,
            audit_event_count=0,
        ),
        records=session_records,
    )
    use_cases = LocalRecordQueriesUseCases(reader)

    result = use_cases.resolve_filtered_record_source(
        "C:/tmp/base.xlsx",
        fallback_records=session_records,
        text="ABC",
        status="Todos",
        selected_micros=(),
        selected_eletronicos=(),
        micro_all_selected=True,
        eletronico_all_selected=True,
        selected_year="Todos",
        fallback_search_index=None,
    )

    assert result.source == "sqlite"
    assert result.strategy == "sqlite_query"
    assert [record.uid for record in result.records] == ["u-1"]
    assert result.metrics is not None
    assert result.metrics["count_total"] == 1
    assert reader.query_calls[0]["search_text"] == "ABC"
    assert reader.metrics_calls[0]["search_text"] == "ABC"


def test_local_record_queries_can_resolve_filter_facets_from_sqlite_snapshot():
    session_records = [
        make_record(oficio_processo="ABC/2026", microbacia="Gregorio", uid="u-1"),
        make_record(oficio_processo="XYZ/2025", microbacia="Medeiros", uid="u-2"),
    ]
    reader = StubLocalRecordReader(
        summary=WorkbookSnapshotSummary(
            workbook_path="C:/tmp/base.xlsx",
            synced_at="2026-03-31T12:00:00+00:00",
            record_count=2,
            plantio_count=0,
            audit_event_count=0,
        ),
        records=session_records,
    )
    use_cases = LocalRecordQueriesUseCases(reader)

    result = use_cases.resolve_filter_facets(
        "C:/tmp/base.xlsx",
        fallback_records=session_records,
    )
    status = use_cases.build_filter_facets_status(result)

    assert result.source == "sqlite"
    assert result.microbacias == ("Gregorio", "Medeiros")
    assert result.years == ("2026", "2025")
    assert status.status == "sqlite"
    assert status.uses_sqlite is True
    assert status.micro_count == 2
    assert status.year_count == 2


def test_local_record_queries_fall_back_to_session_for_filter_facets_when_snapshot_diverges():
    session_records = [
        make_record(oficio_processo="ABC/2026", microbacia="Gregorio", uid="u-1"),
        make_record(oficio_processo="XYZ/2025", microbacia="Medeiros", uid="u-2"),
    ]
    use_cases = LocalRecordQueriesUseCases(
        StubLocalRecordReader(
            summary=WorkbookSnapshotSummary(
                workbook_path="C:/tmp/base.xlsx",
                synced_at="2026-03-31T12:00:00+00:00",
                record_count=1,
                plantio_count=0,
                audit_event_count=0,
            ),
            records=[session_records[0]],
        )
    )

    result = use_cases.resolve_filter_facets(
        "C:/tmp/base.xlsx",
        fallback_records=session_records,
    )
    status = use_cases.build_filter_facets_status(result)

    assert result.source == "session"
    assert result.microbacias == ("Gregorio", "Medeiros")
    assert result.years == ("2026", "2025")
    assert result.issues
    assert status.status == "fallback"
    assert status.uses_sqlite is False


def test_local_record_queries_fall_back_when_workbook_file_changes_after_snapshot(tmp_path):
    workbook_path = tmp_path / "base.xlsx"
    workbook_path.write_text("versao-1", encoding="utf-8")
    initial_stat = workbook_path.stat()
    session_records = [make_record(uid="u-1"), make_record(excel_row=3, uid="u-2", av_tec="AT-2")]
    reader = StubLocalRecordReader(
        summary=WorkbookSnapshotSummary(
            workbook_path=str(workbook_path),
            synced_at="2026-03-31T12:00:00+00:00",
            record_count=2,
            plantio_count=0,
            audit_event_count=0,
            source_mtime_ns=int(initial_stat.st_mtime_ns),
            source_size=int(initial_stat.st_size),
        ),
        records=session_records,
    )
    use_cases = LocalRecordQueriesUseCases(reader)

    workbook_path.write_text("versao-2-com-conteudo-diferente", encoding="utf-8")

    result = use_cases.resolve_record_source(str(workbook_path), fallback_records=session_records)

    assert result.source == "session"
    assert result.strategy == "session_filter"
    assert result.records == tuple(session_records)
    assert result.issues == ("Arquivo foi alterado desde a ultima sincronizacao do espelho local.",)


def test_local_record_queries_can_resolve_selected_record_from_sqlite_snapshot():
    session_records = [make_record(uid="u-1", endereco="Sessao"), make_record(excel_row=3, uid="u-2", endereco="Sessao 2")]
    mirrored_records = [make_record(uid="u-1", endereco="SQLite"), make_record(excel_row=3, uid="u-2", endereco="SQLite 2")]
    use_cases = LocalRecordQueriesUseCases(
        StubLocalRecordReader(
            summary=WorkbookSnapshotSummary(
                workbook_path="C:/tmp/base.xlsx",
                synced_at="2026-03-31T12:00:00+00:00",
                record_count=2,
                plantio_count=0,
                audit_event_count=0,
            ),
            records=mirrored_records,
        )
    )

    result = use_cases.resolve_selected_record(
        "C:/tmp/base.xlsx",
        fallback_records=session_records,
        uid="u-1",
        excel_row=2,
    )

    assert result.source == "sqlite"
    assert result.strategy == "sqlite_detail"
    assert result.record is not None
    assert result.record.endereco == "SQLite"


def test_local_record_queries_can_resolve_duplicate_from_sqlite_snapshot():
    session_records = [
        make_record(uid="u-1", av_tec="AT-9", excel_row=2),
        make_record(uid="u-2", av_tec="AT-8", excel_row=3),
    ]
    mirrored_records = [
        make_record(uid="u-10", av_tec="AT-9", excel_row=9),
        make_record(uid="u-20", av_tec="AT-1", excel_row=10),
    ]
    use_cases = LocalRecordQueriesUseCases(
        StubLocalRecordReader(
            summary=WorkbookSnapshotSummary(
                workbook_path="C:/tmp/base.xlsx",
                synced_at="2026-03-31T12:00:00+00:00",
                record_count=2,
                plantio_count=0,
                audit_event_count=0,
            ),
            records=mirrored_records,
        )
    )

    result = use_cases.resolve_duplicate_av_tec(
        "C:/tmp/base.xlsx",
        fallback_records=session_records,
        av_tec="AT-1",
        current_uid="",
    )

    assert result.source == "sqlite"
    assert result.strategy == "sqlite_duplicate"
    assert result.duplicate_row == 10
