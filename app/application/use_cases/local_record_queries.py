from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from app.models.compensacao import Compensacao
from app.services.records_service import STANDARD_TIPO_OPTIONS, compute_metrics, extract_year, filter_records, unique_non_empty
from app.services.sqlite_mirror_service import WorkbookFilterFacets, WorkbookSnapshotSummary


def _read_workbook_file_identity(workbook_path: str) -> tuple[int, int]:
    normalized_path = os.path.normcase(os.path.abspath(str(workbook_path or "").strip()))
    if not normalized_path or not os.path.exists(normalized_path):
        return 0, 0
    try:
        stat_result = os.stat(normalized_path)
    except OSError:
        return 0, 0
    return int(getattr(stat_result, "st_mtime_ns", 0) or 0), int(getattr(stat_result, "st_size", 0) or 0)


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
        selected_year: str = "Todos",
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class LocalRecordReadResult:
    source: str
    records: tuple[Compensacao, ...]
    strategy: str = "session_filter"
    metrics: Mapping[str, object] | None = None
    workbook_path: str = ""
    synced_at: str = ""
    mirrored_records: int = 0
    session_records: int = 0
    issues: tuple[str, ...] = ()

    @property
    def uses_sqlite(self) -> bool:
        return self.source == "sqlite"


@dataclass(frozen=True)
class LocalRecordReadStatus:
    status: str
    source: str
    strategy: str
    workbook_path: str
    synced_at: str
    mirrored_records: int
    session_records: int
    filtered_records: int
    issues: tuple[str, ...] = ()

    @property
    def uses_sqlite(self) -> bool:
        return self.source == "sqlite"


@dataclass(frozen=True)
class LocalFilterFacetsResult:
    source: str
    workbook_path: str = ""
    synced_at: str = ""
    mirrored_records: int = 0
    session_records: int = 0
    microbacias: tuple[str, ...] = ()
    years: tuple[str, ...] = ()
    tipos: tuple[str, ...] = STANDARD_TIPO_OPTIONS
    issues: tuple[str, ...] = ()

    @property
    def uses_sqlite(self) -> bool:
        return self.source == "sqlite"


@dataclass(frozen=True)
class LocalFilterFacetsStatus:
    status: str
    source: str
    workbook_path: str
    synced_at: str
    mirrored_records: int
    session_records: int
    micro_count: int
    year_count: int
    issues: tuple[str, ...] = ()

    @property
    def uses_sqlite(self) -> bool:
        return self.source == "sqlite"


@dataclass(frozen=True)
class LocalSelectedRecordResult:
    source: str
    record: Compensacao | None
    strategy: str = "session_selection"
    workbook_path: str = ""
    synced_at: str = ""
    mirrored_records: int = 0
    session_records: int = 0
    issues: tuple[str, ...] = ()

    @property
    def uses_sqlite(self) -> bool:
        return self.source == "sqlite"


@dataclass(frozen=True)
class LocalDuplicateCheckResult:
    source: str
    duplicate_row: int | None
    strategy: str = "session_duplicate"
    workbook_path: str = ""
    synced_at: str = ""
    mirrored_records: int = 0
    session_records: int = 0
    issues: tuple[str, ...] = ()

    @property
    def uses_sqlite(self) -> bool:
        return self.source == "sqlite"


class LocalRecordQueriesUseCases:
    def __init__(self, snapshot_reader: LocalRecordSnapshotReader | None):
        self.snapshot_reader = snapshot_reader

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
        fallback = tuple(fallback_records)
        return LocalRecordReadResult(
            source="session",
            records=fallback,
            strategy=strategy,
            metrics=compute_metrics(fallback),
            workbook_path=workbook_path,
            mirrored_records=mirrored_records,
            session_records=len(fallback),
            synced_at=synced_at,
            issues=tuple(issues),
        )

    @staticmethod
    def _find_record_in_sequence(
        records: Sequence[Compensacao],
        *,
        uid: str = "",
        excel_row: int = 0,
    ) -> Compensacao | None:
        normalized_uid = str(uid or "").strip()
        normalized_row = int(excel_row or 0)
        for record in records:
            if normalized_uid and str(getattr(record, "uid", "") or "").strip() == normalized_uid:
                return record
            if normalized_row > 0 and int(getattr(record, "excel_row", 0) or 0) == normalized_row:
                return record
        return None

    @staticmethod
    def _find_duplicate_av_tec_in_records(
        records: Sequence[Compensacao],
        *,
        av_tec: str,
        current_uid: str = "",
    ) -> int | None:
        target = str(av_tec or "").strip().upper()
        normalized_uid = str(current_uid or "").strip()
        if not target:
            return None
        for record in records:
            if normalized_uid and str(getattr(record, "uid", "") or "").strip() == normalized_uid:
                continue
            if str(getattr(record, "av_tec", "") or "").strip().upper() != target:
                continue
            return int(getattr(record, "excel_row", 0) or 0) or None
        return None

    def _build_filter_facets_from_records(
        self,
        records: Sequence[Compensacao],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        micros = tuple(unique_non_empty(record.microbacia for record in records))
        years = tuple(
            sorted(
                {
                    year
                    for year in (extract_year(record.oficio_processo) for record in records)
                    if year
                },
                reverse=True,
            )
        )
        return micros, years

    def _resolve_snapshot_context(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
    ) -> tuple[str, tuple[Compensacao, ...], WorkbookSnapshotSummary | None, LocalRecordReadResult | None]:
        fallback = tuple(fallback_records)
        normalized_path = str(workbook_path or "").strip()
        if not normalized_path or self.snapshot_reader is None:
            return (
                normalized_path,
                fallback,
                None,
                LocalRecordReadResult(
                    source="session",
                    records=fallback,
                    strategy="session_filter",
                    metrics=compute_metrics(fallback),
                    workbook_path=normalized_path,
                    session_records=len(fallback),
                ),
            )

        snapshot = self.snapshot_reader.get_workbook_snapshot_summary(normalized_path)
        expected_count = len(fallback)
        if not snapshot.synced_at:
            return (
                normalized_path,
                fallback,
                None,
                LocalRecordReadResult(
                    source="session",
                    records=fallback,
                    strategy="session_filter",
                    metrics=compute_metrics(fallback),
                    workbook_path=normalized_path,
                    mirrored_records=int(snapshot.record_count),
                    session_records=expected_count,
                    synced_at=str(snapshot.synced_at or ""),
                    issues=("Espelho local ainda nao sincronizado para esta planilha.",),
                ),
            )
        if int(snapshot.record_count) != expected_count:
            return (
                normalized_path,
                fallback,
                None,
                LocalRecordReadResult(
                    source="session",
                    records=fallback,
                    strategy="session_filter",
                    metrics=compute_metrics(fallback),
                    workbook_path=normalized_path,
                    mirrored_records=int(snapshot.record_count),
                    session_records=expected_count,
                    synced_at=str(snapshot.synced_at or ""),
                    issues=(
                        (
                            f"Espelho local com {int(snapshot.record_count)} registro(s), "
                            f"mas a sessao atual possui {expected_count}."
                        ),
                    ),
                ),
            )
        snapshot_mtime_ns = int(snapshot.source_mtime_ns or 0)
        snapshot_size = int(snapshot.source_size or 0)
        if snapshot_mtime_ns > 0 or snapshot_size > 0:
            current_mtime_ns, current_size = _read_workbook_file_identity(normalized_path)
            if current_mtime_ns <= 0 and current_size <= 0:
                return (
                    normalized_path,
                    fallback,
                    None,
                    LocalRecordReadResult(
                        source="session",
                        records=fallback,
                        strategy="session_filter",
                        metrics=compute_metrics(fallback),
                        workbook_path=normalized_path,
                        mirrored_records=int(snapshot.record_count),
                        session_records=expected_count,
                        synced_at=str(snapshot.synced_at or ""),
                        issues=("Nao foi possivel validar o arquivo da planilha contra o espelho local.",),
                    ),
                )
            if current_mtime_ns != snapshot_mtime_ns or current_size != snapshot_size:
                return (
                    normalized_path,
                    fallback,
                    None,
                    LocalRecordReadResult(
                        source="session",
                        records=fallback,
                        strategy="session_filter",
                        metrics=compute_metrics(fallback),
                        workbook_path=normalized_path,
                        mirrored_records=int(snapshot.record_count),
                        session_records=expected_count,
                        synced_at=str(snapshot.synced_at or ""),
                        issues=("Arquivo foi alterado desde a ultima sincronizacao do espelho local.",),
                    ),
                )

        return normalized_path, fallback, snapshot, None

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
            records = tuple(reader.list_records_for_workbook(normalized_path))
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

        snapshot = reader.get_workbook_snapshot_summary(normalized_path)
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
            records = tuple(reader.list_records_for_workbook(normalized_path))
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
                reader.query_records_for_workbook(
                    normalized_path,
                    search_text=text,
                    status=status,
                    selected_micros=selected_micros,
                    selected_eletronicos=selected_eletronicos,
                    micro_all_selected=micro_all_selected,
                    eletronico_all_selected=eletronico_all_selected,
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
            filtered_metrics = reader.query_metrics_for_workbook(
                normalized_path,
                search_text=text,
                status=status,
                selected_micros=selected_micros,
                selected_eletronicos=selected_eletronicos,
                micro_all_selected=micro_all_selected,
                eletronico_all_selected=eletronico_all_selected,
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
            return LocalFilterFacetsResult(
                source="session",
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
            facets = reader.query_filter_facets_for_workbook(normalized_path)
        except Exception as exc:
            return LocalFilterFacetsResult(
                source="session",
                workbook_path=normalized_path,
                synced_at=str(snapshot.synced_at or ""),
                mirrored_records=int(snapshot.record_count),
                session_records=len(fallback),
                microbacias=fallback_micros,
                years=fallback_years,
                issues=(f"Falha ao consultar facetas no espelho local: {exc}",),
            )

        return LocalFilterFacetsResult(
            source="sqlite",
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
            return LocalSelectedRecordResult(
                source="session",
                record=fallback_record,
                strategy="session_selection",
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
                record = reader.find_record_by_uid_for_workbook(normalized_path, normalized_uid)
            if record is None and int(excel_row or 0) > 0:
                record = reader.find_record_by_excel_row_for_workbook(normalized_path, int(excel_row))
        except Exception as exc:
            return LocalSelectedRecordResult(
                source="session",
                record=fallback_record,
                strategy="session_selection",
                workbook_path=normalized_path,
                synced_at=str(snapshot.synced_at or ""),
                mirrored_records=int(snapshot.record_count),
                session_records=len(fallback),
                issues=(f"Falha ao consultar detalhe do registro no espelho local: {exc}",),
            )

        if record is None:
            return LocalSelectedRecordResult(
                source="session",
                record=fallback_record,
                strategy="session_selection",
                workbook_path=normalized_path,
                synced_at=str(snapshot.synced_at or ""),
                mirrored_records=int(snapshot.record_count),
                session_records=len(fallback),
                issues=("Registro selecionado nao foi encontrado no espelho local.",),
            )

        return LocalSelectedRecordResult(
            source="sqlite",
            record=record,
            strategy="sqlite_detail",
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
            return LocalDuplicateCheckResult(
                source="session",
                duplicate_row=fallback_duplicate,
                strategy="session_duplicate",
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
            duplicate_row = reader.find_duplicate_av_tec_for_workbook(
                normalized_path,
                av_tec=av_tec,
                current_uid=current_uid,
            )
        except Exception as exc:
            return LocalDuplicateCheckResult(
                source="session",
                duplicate_row=fallback_duplicate,
                strategy="session_duplicate",
                workbook_path=normalized_path,
                synced_at=str(snapshot.synced_at or ""),
                mirrored_records=int(snapshot.record_count),
                session_records=len(fallback),
                issues=(f"Falha ao consultar duplicidade no espelho local: {exc}",),
            )

        return LocalDuplicateCheckResult(
            source="sqlite",
            duplicate_row=duplicate_row,
            strategy="sqlite_duplicate",
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
        normalized_path = str(read_result.workbook_path or "").strip()
        status = "session"
        if not normalized_path:
            status = "indisponivel"
        elif read_result.uses_sqlite:
            status = "sqlite"
        elif read_result.issues:
            status = "fallback"

        return LocalRecordReadStatus(
            status=status,
            source=str(read_result.source or "session"),
            strategy=str(read_result.strategy or "session_filter"),
            workbook_path=normalized_path,
            synced_at=str(read_result.synced_at or ""),
            mirrored_records=int(read_result.mirrored_records),
            session_records=int(read_result.session_records or len(read_result.records)),
            filtered_records=max(int(filtered_records), 0),
            issues=tuple(read_result.issues),
        )

    def build_filter_facets_status(
        self,
        facets_result: LocalFilterFacetsResult,
    ) -> LocalFilterFacetsStatus:
        normalized_path = str(facets_result.workbook_path or "").strip()
        status = "session"
        if not normalized_path:
            status = "indisponivel"
        elif facets_result.uses_sqlite:
            status = "sqlite"
        elif facets_result.issues:
            status = "fallback"

        return LocalFilterFacetsStatus(
            status=status,
            source=str(facets_result.source or "session"),
            workbook_path=normalized_path,
            synced_at=str(facets_result.synced_at or ""),
            mirrored_records=int(facets_result.mirrored_records),
            session_records=int(facets_result.session_records),
            micro_count=len(facets_result.microbacias),
            year_count=len(facets_result.years),
            issues=tuple(facets_result.issues),
        )
