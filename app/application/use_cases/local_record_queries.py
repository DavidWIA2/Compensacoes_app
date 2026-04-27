from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from app.models.compensacao import Compensacao
from app.services.records_service import compute_metrics, filter_records
from app.services.sqlite_mirror_service import WorkbookFilterFacets, WorkbookSnapshotSummary
from app.services.sqlite_mirror_service_support import read_source_file_identity as _read_workbook_file_identity
from app.application.use_cases.local_record_queries_support import (
    LocalDuplicateCheckResult,
    LocalFilterFacetsResult,
    LocalFilterFacetsStatus,
    LocalRecordReadResult,
    LocalRecordReadStatus,
    LocalSelectedRecordResult,
    build_filter_facets_from_records as _build_filter_facets_from_records_helper,
    build_filter_facets_status as _build_filter_facets_status_helper,
    build_read_status as _build_read_status_helper,
    build_session_duplicate_check_result,
    build_session_filter_facets_result,
    build_session_record_result as _build_session_record_result_helper,
    build_session_selected_record_result,
    build_sqlite_duplicate_check_result,
    build_sqlite_filter_facets_result,
    build_sqlite_selected_record_result,
    find_duplicate_av_tec_in_records as _find_duplicate_av_tec_in_records_helper,
    find_record_in_sequence as _find_record_in_sequence_helper,
    validate_snapshot_against_runtime,
)


class LocalRecordSnapshotReader(Protocol):
    def get_workbook_snapshot_summary(self, workbook_path: str) -> WorkbookSnapshotSummary: ...

    def list_records_for_workbook(self, workbook_path: str) -> list[Compensacao]: ...

    def find_record_by_uid_for_workbook(self, workbook_path: str, uid: str) -> Compensacao | None: ...

    def find_record_by_excel_row_for_workbook(self, workbook_path: str, excel_row: int) -> Compensacao | None: ...

    def find_duplicate_av_tec_for_workbook(
        self,
        workbook_path: str,
        *,
        av_tec: str,
        current_uid: str = "",
    ) -> int | None: ...

    def query_filter_facets_for_workbook(self, workbook_path: str) -> WorkbookFilterFacets: ...

    def query_records_for_workbook(
        self,
        workbook_path: str,
        *,
        search_text: str = "",
        status: str = "Todos",
        selected_micros: Sequence[str] = (),
        selected_eletronicos: Sequence[str] = (),
        micro_all_selected: bool = True,
        eletronico_all_selected: bool = True,
        selected_caixas: Sequence[str] = (),
        caixa_all_selected: bool = True,
        selected_year: str = "Todos",
    ) -> list[Compensacao]: ...

    def query_metrics_for_workbook(
        self,
        workbook_path: str,
        *,
        search_text: str = "",
        status: str = "Todos",
        selected_micros: Sequence[str] = (),
        selected_eletronicos: Sequence[str] = (),
        micro_all_selected: bool = True,
        eletronico_all_selected: bool = True,
        selected_caixas: Sequence[str] = (),
        caixa_all_selected: bool = True,
        selected_year: str = "Todos",
    ) -> dict[str, object]: ...

class LocalRecordQueriesUseCases:
    def __init__(self, snapshot_reader: LocalRecordSnapshotReader | None):
        self.snapshot_reader = snapshot_reader

    def _get_snapshot_summary(self, workbook_path: str) -> WorkbookSnapshotSummary:
        reader = self.snapshot_reader
        if reader is None:
            raise RuntimeError("Snapshot reader indisponivel.")
        if hasattr(reader, "get_session_snapshot_summary"):
            return reader.get_session_snapshot_summary(workbook_path)
        return reader.get_workbook_snapshot_summary(workbook_path)

    def _list_session_records(self, workbook_path: str) -> list[Compensacao]:
        reader = self.snapshot_reader
        if reader is None:
            return []
        if hasattr(reader, "list_records_for_session"):
            return reader.list_records_for_session(workbook_path)
        return reader.list_records_for_workbook(workbook_path)

    def _find_record_by_uid(self, workbook_path: str, uid: str) -> Compensacao | None:
        reader = self.snapshot_reader
        if reader is None:
            return None
        if hasattr(reader, "find_record_by_uid_for_session"):
            return reader.find_record_by_uid_for_session(workbook_path, uid)
        return reader.find_record_by_uid_for_workbook(workbook_path, uid)

    def _find_record_by_excel_row(self, workbook_path: str, excel_row: int) -> Compensacao | None:
        reader = self.snapshot_reader
        if reader is None:
            return None
        if hasattr(reader, "find_record_by_excel_row_for_session"):
            return reader.find_record_by_excel_row_for_session(workbook_path, excel_row)
        return reader.find_record_by_excel_row_for_workbook(workbook_path, excel_row)

    def _find_duplicate_av_tec(
        self,
        workbook_path: str,
        *,
        av_tec: str,
        current_uid: str = "",
    ) -> int | None:
        reader = self.snapshot_reader
        if reader is None:
            return None
        if hasattr(reader, "find_duplicate_av_tec_for_session"):
            return reader.find_duplicate_av_tec_for_session(
                workbook_path,
                av_tec=av_tec,
                current_uid=current_uid,
            )
        return reader.find_duplicate_av_tec_for_workbook(
            workbook_path,
            av_tec=av_tec,
            current_uid=current_uid,
        )

    def _query_filter_facets(self, workbook_path: str) -> WorkbookFilterFacets:
        reader = self.snapshot_reader
        if reader is None:
            raise RuntimeError("Snapshot reader indisponivel.")
        if hasattr(reader, "query_filter_facets_for_session"):
            return reader.query_filter_facets_for_session(workbook_path)
        return reader.query_filter_facets_for_workbook(workbook_path)

    def _query_records(
        self,
        workbook_path: str,
        *,
        search_text: str,
        status: str,
        selected_micros: Sequence[str],
        selected_eletronicos: Sequence[str],
        micro_all_selected: bool,
        eletronico_all_selected: bool,
        selected_caixas: Sequence[str],
        caixa_all_selected: bool,
        selected_year: str,
    ) -> list[Compensacao]:
        reader = self.snapshot_reader
        if reader is None:
            return []
        kwargs = {
            "search_text": search_text,
            "status": status,
            "selected_micros": selected_micros,
            "selected_eletronicos": selected_eletronicos,
            "micro_all_selected": micro_all_selected,
            "eletronico_all_selected": eletronico_all_selected,
            "selected_caixas": selected_caixas,
            "caixa_all_selected": caixa_all_selected,
            "selected_year": selected_year,
        }
        if hasattr(reader, "query_records_for_session"):
            return reader.query_records_for_session(workbook_path, **kwargs)
        return reader.query_records_for_workbook(workbook_path, **kwargs)

    def _query_metrics(
        self,
        workbook_path: str,
        *,
        search_text: str,
        status: str,
        selected_micros: Sequence[str],
        selected_eletronicos: Sequence[str],
        micro_all_selected: bool,
        eletronico_all_selected: bool,
        selected_caixas: Sequence[str],
        caixa_all_selected: bool,
        selected_year: str,
    ) -> dict[str, object]:
        reader = self.snapshot_reader
        if reader is None:
            return compute_metrics(())
        kwargs = {
            "search_text": search_text,
            "status": status,
            "selected_micros": selected_micros,
            "selected_eletronicos": selected_eletronicos,
            "micro_all_selected": micro_all_selected,
            "eletronico_all_selected": eletronico_all_selected,
            "selected_caixas": selected_caixas,
            "caixa_all_selected": caixa_all_selected,
            "selected_year": selected_year,
        }
        if hasattr(reader, "query_metrics_for_session"):
            return reader.query_metrics_for_session(workbook_path, **kwargs)
        return reader.query_metrics_for_workbook(workbook_path, **kwargs)

    @staticmethod
    def _build_session_record_result(
        fallback_records: Sequence[Compensacao],
        *,
        workbook_path: str,
        strategy: str,
        mirrored_records: int = 0,
        synced_at: str = "",
        issues: Sequence[str] = (),
    ) -> LocalRecordReadResult:
        return _build_session_record_result_helper(
            fallback_records,
            workbook_path=workbook_path,
            strategy=strategy,
            mirrored_records=mirrored_records,
            synced_at=synced_at,
            issues=issues,
        )

    @staticmethod
    def _find_record_in_sequence(
        records: Sequence[Compensacao],
        *,
        uid: str = "",
        excel_row: int = 0,
    ) -> Compensacao | None:
        return _find_record_in_sequence_helper(records, uid=uid, excel_row=excel_row)

    @staticmethod
    def _find_duplicate_av_tec_in_records(
        records: Sequence[Compensacao],
        *,
        av_tec: str,
        current_uid: str = "",
    ) -> int | None:
        return _find_duplicate_av_tec_in_records_helper(
            records,
            av_tec=av_tec,
            current_uid=current_uid,
        )

    def _build_filter_facets_from_records(
        self,
        records: Sequence[Compensacao],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return _build_filter_facets_from_records_helper(records)

    def _resolve_snapshot_context(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
    ) -> tuple[str, tuple[Compensacao, ...], WorkbookSnapshotSummary | None, LocalRecordReadResult | None]:
        snapshot = self._get_snapshot_summary(workbook_path) if self.snapshot_reader is not None and str(workbook_path or "").strip() else None
        return validate_snapshot_against_runtime(
            workbook_path,
            fallback_records=fallback_records,
            snapshot_reader_available=self.snapshot_reader is not None,
            snapshot=snapshot,
            strategy="session_filter",
        )

    def resolve_record_source(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
    ) -> LocalRecordReadResult:
        normalized_path, fallback, snapshot, early_result = self._resolve_snapshot_context(
            workbook_path,
            fallback_records=fallback_records,
        )
        if early_result is not None:
            return early_result
        reader = self.snapshot_reader
        assert reader is not None
        assert snapshot is not None

        try:
            records = tuple(self._list_session_records(normalized_path))
        except Exception as exc:
            return LocalRecordReadResult(
                source="session",
                records=fallback,
                strategy="session_filter",
                metrics=compute_metrics(fallback),
                workbook_path=normalized_path,
                mirrored_records=int(snapshot.record_count),
                session_records=len(fallback),
                synced_at=str(snapshot.synced_at or ""),
                issues=(f"Falha ao consultar o espelho local: {exc}",),
            )

        if len(records) != len(fallback):
            return LocalRecordReadResult(
                source="session",
                records=fallback,
                strategy="session_filter",
                metrics=compute_metrics(fallback),
                workbook_path=normalized_path,
                mirrored_records=len(records),
                session_records=len(fallback),
                synced_at=str(snapshot.synced_at or ""),
                issues=(
                    (
                        f"Consulta local retornou {len(records)} registro(s), "
                        f"mas a sessao atual possui {len(fallback)}."
                    ),
                ),
            )

        return LocalRecordReadResult(
            source="sqlite",
            records=records,
            strategy="sqlite_snapshot",
            metrics=compute_metrics(records),
            workbook_path=normalized_path,
            synced_at=str(snapshot.synced_at or ""),
            mirrored_records=int(snapshot.record_count),
            session_records=len(fallback),
        )

    def resolve_authoritative_record_source(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
    ) -> LocalRecordReadResult:
        normalized_path = str(workbook_path or "").strip()
        fallback = tuple(fallback_records)
        reader = self.snapshot_reader
        if not normalized_path or reader is None:
            return self._build_session_record_result(
                fallback,
                workbook_path=normalized_path,
                strategy="session_authoritative_base",
            )

        snapshot = self._get_snapshot_summary(normalized_path)
        synced_at = str(snapshot.synced_at or "")
        mirrored_records = int(snapshot.record_count)
        if not synced_at:
            return self._build_session_record_result(
                fallback,
                workbook_path=normalized_path,
                strategy="session_authoritative_base",
                mirrored_records=mirrored_records,
                issues=("Espelho local ainda nao sincronizado para esta planilha.",),
            )

        snapshot_mtime_ns = int(snapshot.source_mtime_ns or 0)
        snapshot_size = int(snapshot.source_size or 0)
        if snapshot_mtime_ns <= 0 and snapshot_size <= 0:
            return self._build_session_record_result(
                fallback,
                workbook_path=normalized_path,
                strategy="session_authoritative_base",
                mirrored_records=mirrored_records,
                synced_at=synced_at,
                issues=("Espelho local sem fingerprint confiavel para esta planilha.",),
            )

        current_mtime_ns, current_size = _read_workbook_file_identity(normalized_path)
        if current_mtime_ns <= 0 and current_size <= 0:
            return self._build_session_record_result(
                fallback,
                workbook_path=normalized_path,
                strategy="session_authoritative_base",
                mirrored_records=mirrored_records,
                synced_at=synced_at,
                issues=("Nao foi possivel validar o arquivo da planilha contra o espelho local.",),
            )
        if current_mtime_ns != snapshot_mtime_ns or current_size != snapshot_size:
            return self._build_session_record_result(
                fallback,
                workbook_path=normalized_path,
                strategy="session_authoritative_base",
                mirrored_records=mirrored_records,
                synced_at=synced_at,
                issues=("Arquivo foi alterado desde a ultima sincronizacao do espelho local.",),
            )

        try:
            records = tuple(self._list_session_records(normalized_path))
        except Exception as exc:
            return self._build_session_record_result(
                fallback,
                workbook_path=normalized_path,
                strategy="session_authoritative_base",
                mirrored_records=mirrored_records,
                synced_at=synced_at,
                issues=(f"Falha ao consultar o espelho local: {exc}",),
            )

        if len(records) != mirrored_records:
            return self._build_session_record_result(
                fallback,
                workbook_path=normalized_path,
                strategy="session_authoritative_base",
                mirrored_records=mirrored_records,
                synced_at=synced_at,
                issues=(
                    (
                        f"Espelho local informou {mirrored_records} registro(s), "
                        f"mas retornou {len(records)} na leitura."
                    ),
                ),
            )

        issues: tuple[str, ...] = ()
        if len(records) != len(fallback):
            issues = (
                (
                    f"Sessao atual diverge do espelho local ({len(fallback)} x {len(records)}); "
                    "usando a base autoritativa validada pelo arquivo."
                ),
            )

        return LocalRecordReadResult(
            source="sqlite",
            records=records,
            strategy="sqlite_authoritative_base",
            metrics=compute_metrics(records),
            workbook_path=normalized_path,
            synced_at=synced_at,
            mirrored_records=mirrored_records,
            session_records=len(fallback),
            issues=issues,
        )

    def resolve_filtered_record_source(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
        text: str,
        status: str,
        selected_micros: Sequence[str],
        selected_eletronicos: Sequence[str],
        micro_all_selected: bool,
        eletronico_all_selected: bool,
        selected_caixas: Sequence[str] = (),
        caixa_all_selected: bool = True,
        selected_year: str = "Todos",
        fallback_search_index: Mapping[str, str] | None = None,
    ) -> LocalRecordReadResult:
        normalized_path, fallback, snapshot, early_result = self._resolve_snapshot_context(
            workbook_path,
            fallback_records=fallback_records,
        )

        filtered_fallback = tuple(
            filter_records(
                fallback,
                text=text,
                status=status,
                selected_micros=selected_micros,
                selected_eletronicos=selected_eletronicos,
                micro_all_selected=micro_all_selected,
                eletronico_all_selected=eletronico_all_selected,
                selected_caixas=selected_caixas,
                caixa_all_selected=caixa_all_selected,
                selected_year=selected_year,
                search_index=dict(fallback_search_index or {}),
            )
        )
        fallback_metrics = compute_metrics(filtered_fallback)
        if early_result is not None:
            return LocalRecordReadResult(
                source="session",
                records=filtered_fallback,
                strategy="session_filter",
                metrics=fallback_metrics,
                workbook_path=early_result.workbook_path,
                synced_at=early_result.synced_at,
                mirrored_records=early_result.mirrored_records,
                session_records=early_result.session_records,
                issues=early_result.issues,
            )
        reader = self.snapshot_reader
        assert reader is not None
        assert snapshot is not None

        try:
            filtered_records = tuple(
                self._query_records(
                    normalized_path,
                    search_text=text,
                    status=status,
                    selected_micros=selected_micros,
                    selected_eletronicos=selected_eletronicos,
                    micro_all_selected=micro_all_selected,
                    eletronico_all_selected=eletronico_all_selected,
                    selected_caixas=selected_caixas,
                    caixa_all_selected=caixa_all_selected,
                    selected_year=selected_year,
                )
            )
        except Exception as exc:
            return LocalRecordReadResult(
                source="session",
                records=filtered_fallback,
                strategy="session_filter",
                metrics=fallback_metrics,
                workbook_path=normalized_path,
                synced_at=str(snapshot.synced_at or ""),
                mirrored_records=int(snapshot.record_count),
                session_records=len(fallback),
                issues=(f"Falha ao consultar filtros no espelho local: {exc}",),
            )

        try:
            filtered_metrics = self._query_metrics(
                normalized_path,
                search_text=text,
                status=status,
                selected_micros=selected_micros,
                selected_eletronicos=selected_eletronicos,
                micro_all_selected=micro_all_selected,
                eletronico_all_selected=eletronico_all_selected,
                selected_caixas=selected_caixas,
                caixa_all_selected=caixa_all_selected,
                selected_year=selected_year,
            )
        except Exception:
            filtered_metrics = compute_metrics(filtered_records)

        return LocalRecordReadResult(
            source="sqlite",
            records=filtered_records,
            strategy="sqlite_query",
            metrics=filtered_metrics,
            workbook_path=normalized_path,
            synced_at=str(snapshot.synced_at or ""),
            mirrored_records=int(snapshot.record_count),
            session_records=len(fallback),
        )

    def resolve_filter_facets(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
    ) -> LocalFilterFacetsResult:
        normalized_path, fallback, snapshot, early_result = self._resolve_snapshot_context(
            workbook_path,
            fallback_records=fallback_records,
        )
        fallback_micros, fallback_years = self._build_filter_facets_from_records(fallback)

        if early_result is not None:
            return build_session_filter_facets_result(
                workbook_path=early_result.workbook_path,
                synced_at=early_result.synced_at,
                mirrored_records=early_result.mirrored_records,
                session_records=early_result.session_records,
                microbacias=fallback_micros,
                years=fallback_years,
                issues=early_result.issues,
            )

        reader = self.snapshot_reader
        assert reader is not None
        assert snapshot is not None

        try:
            facets = self._query_filter_facets(normalized_path)
        except Exception as exc:
            return build_session_filter_facets_result(
                workbook_path=normalized_path,
                synced_at=str(snapshot.synced_at or ""),
                mirrored_records=int(snapshot.record_count),
                session_records=len(fallback),
                microbacias=fallback_micros,
                years=fallback_years,
                issues=(f"Falha ao consultar facetas no espelho local: {exc}",),
            )

        return build_sqlite_filter_facets_result(
            workbook_path=normalized_path,
            synced_at=str(facets.synced_at or snapshot.synced_at or ""),
            mirrored_records=int(facets.record_count or snapshot.record_count),
            session_records=len(fallback),
            microbacias=tuple(facets.microbacias),
            years=tuple(facets.years),
        )

    def resolve_selected_record(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
        uid: str = "",
        excel_row: int = 0,
    ) -> LocalSelectedRecordResult:
        normalized_path, fallback, snapshot, early_result = self._resolve_snapshot_context(
            workbook_path,
            fallback_records=fallback_records,
        )
        fallback_record = self._find_record_in_sequence(
            fallback,
            uid=uid,
            excel_row=excel_row,
        )
        if early_result is not None:
            return build_session_selected_record_result(
                record=fallback_record,
                workbook_path=early_result.workbook_path,
                synced_at=early_result.synced_at,
                mirrored_records=early_result.mirrored_records,
                session_records=early_result.session_records,
                issues=early_result.issues,
            )

        reader = self.snapshot_reader
        assert reader is not None
        assert snapshot is not None

        try:
            record = None
            normalized_uid = str(uid or "").strip()
            if normalized_uid:
                record = self._find_record_by_uid(normalized_path, normalized_uid)
            if record is None and int(excel_row or 0) > 0:
                record = self._find_record_by_excel_row(normalized_path, int(excel_row))
        except Exception as exc:
            return build_session_selected_record_result(
                record=fallback_record,
                workbook_path=normalized_path,
                synced_at=str(snapshot.synced_at or ""),
                mirrored_records=int(snapshot.record_count),
                session_records=len(fallback),
                issues=(f"Falha ao consultar detalhe do registro no espelho local: {exc}",),
            )

        if record is None:
            return build_session_selected_record_result(
                record=fallback_record,
                workbook_path=normalized_path,
                synced_at=str(snapshot.synced_at or ""),
                mirrored_records=int(snapshot.record_count),
                session_records=len(fallback),
                issues=("Registro selecionado nao foi encontrado no espelho local.",),
            )

        return build_sqlite_selected_record_result(
            record=record,
            workbook_path=normalized_path,
            synced_at=str(snapshot.synced_at or ""),
            mirrored_records=int(snapshot.record_count),
            session_records=len(fallback),
        )

    def resolve_duplicate_av_tec(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
        av_tec: str,
        current_uid: str = "",
    ) -> LocalDuplicateCheckResult:
        normalized_path, fallback, snapshot, early_result = self._resolve_snapshot_context(
            workbook_path,
            fallback_records=fallback_records,
        )
        fallback_duplicate = self._find_duplicate_av_tec_in_records(
            fallback,
            av_tec=av_tec,
            current_uid=current_uid,
        )
        if early_result is not None:
            return build_session_duplicate_check_result(
                duplicate_row=fallback_duplicate,
                workbook_path=early_result.workbook_path,
                synced_at=early_result.synced_at,
                mirrored_records=early_result.mirrored_records,
                session_records=early_result.session_records,
                issues=early_result.issues,
            )

        reader = self.snapshot_reader
        assert reader is not None
        assert snapshot is not None

        try:
            duplicate_row = self._find_duplicate_av_tec(
                normalized_path,
                av_tec=av_tec,
                current_uid=current_uid,
            )
        except Exception as exc:
            return build_session_duplicate_check_result(
                duplicate_row=fallback_duplicate,
                workbook_path=normalized_path,
                synced_at=str(snapshot.synced_at or ""),
                mirrored_records=int(snapshot.record_count),
                session_records=len(fallback),
                issues=(f"Falha ao consultar duplicidade no espelho local: {exc}",),
            )

        return build_sqlite_duplicate_check_result(
            duplicate_row=duplicate_row,
            workbook_path=normalized_path,
            synced_at=str(snapshot.synced_at or ""),
            mirrored_records=int(snapshot.record_count),
            session_records=len(fallback),
        )

    def build_read_status(
        self,
        read_result: LocalRecordReadResult,
        *,
        filtered_records: int,
    ) -> LocalRecordReadStatus:
        return _build_read_status_helper(read_result, filtered_records=filtered_records)

    def build_filter_facets_status(
        self,
        facets_result: LocalFilterFacetsResult,
    ) -> LocalFilterFacetsStatus:
        return _build_filter_facets_status_helper(facets_result)
