from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.models.compensacao import Compensacao
from app.services.records_service import STANDARD_TIPO_OPTIONS, compute_metrics, extract_year, unique_non_empty
from app.services.sqlite_mirror_service import WorkbookSnapshotSummary
from app.services.sqlite_mirror_service_support import normalize_session_path, read_source_file_identity


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

    @property
    def session_path(self) -> str:
        return self.workbook_path


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

    @property
    def session_path(self) -> str:
        return self.workbook_path


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

    @property
    def session_path(self) -> str:
        return self.workbook_path


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

    @property
    def session_path(self) -> str:
        return self.workbook_path


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

    @property
    def session_path(self) -> str:
        return self.workbook_path


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

    @property
    def session_path(self) -> str:
        return self.workbook_path


def build_session_record_result(
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


def find_record_in_sequence(
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


def find_duplicate_av_tec_in_records(
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


def build_filter_facets_from_records(records: Sequence[Compensacao]) -> tuple[tuple[str, ...], tuple[str, ...]]:
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


def resolve_read_status_key(*, workbook_path: str, uses_sqlite: bool, issues: Sequence[str]) -> str:
    normalized_path = str(workbook_path or "").strip()
    if not normalized_path:
        return "indisponivel"
    if uses_sqlite:
        return "sqlite"
    if issues:
        return "fallback"
    return "session"


def build_read_status(read_result: LocalRecordReadResult, *, filtered_records: int) -> LocalRecordReadStatus:
    return LocalRecordReadStatus(
        status=resolve_read_status_key(
            workbook_path=str(read_result.workbook_path or ""),
            uses_sqlite=read_result.uses_sqlite,
            issues=read_result.issues,
        ),
        source=str(read_result.source or "session"),
        strategy=str(read_result.strategy or "session_filter"),
        workbook_path=str(read_result.workbook_path or "").strip(),
        synced_at=str(read_result.synced_at or ""),
        mirrored_records=int(read_result.mirrored_records),
        session_records=int(read_result.session_records or len(read_result.records)),
        filtered_records=max(int(filtered_records), 0),
        issues=tuple(read_result.issues),
    )


def build_filter_facets_status(facets_result: LocalFilterFacetsResult) -> LocalFilterFacetsStatus:
    return LocalFilterFacetsStatus(
        status=resolve_read_status_key(
            workbook_path=str(facets_result.workbook_path or ""),
            uses_sqlite=facets_result.uses_sqlite,
            issues=facets_result.issues,
        ),
        source=str(facets_result.source or "session"),
        workbook_path=str(facets_result.workbook_path or "").strip(),
        synced_at=str(facets_result.synced_at or ""),
        mirrored_records=int(facets_result.mirrored_records),
        session_records=int(facets_result.session_records),
        micro_count=len(facets_result.microbacias),
        year_count=len(facets_result.years),
        issues=tuple(facets_result.issues),
    )


def build_session_filter_facets_result(
    *,
    workbook_path: str,
    synced_at: str,
    mirrored_records: int,
    session_records: int,
    microbacias: Sequence[str],
    years: Sequence[str],
    issues: Sequence[str] = (),
) -> LocalFilterFacetsResult:
    return LocalFilterFacetsResult(
        source="session",
        workbook_path=workbook_path,
        synced_at=synced_at,
        mirrored_records=mirrored_records,
        session_records=session_records,
        microbacias=tuple(microbacias),
        years=tuple(years),
        issues=tuple(issues),
    )


def build_sqlite_filter_facets_result(
    *,
    workbook_path: str,
    synced_at: str,
    mirrored_records: int,
    session_records: int,
    microbacias: Sequence[str],
    years: Sequence[str],
) -> LocalFilterFacetsResult:
    return LocalFilterFacetsResult(
        source="sqlite",
        workbook_path=workbook_path,
        synced_at=synced_at,
        mirrored_records=mirrored_records,
        session_records=session_records,
        microbacias=tuple(microbacias),
        years=tuple(years),
    )


def build_session_selected_record_result(
    *,
    record: Compensacao | None,
    workbook_path: str,
    synced_at: str,
    mirrored_records: int,
    session_records: int,
    issues: Sequence[str] = (),
    strategy: str = "session_selection",
) -> LocalSelectedRecordResult:
    return LocalSelectedRecordResult(
        source="session",
        record=record,
        strategy=strategy,
        workbook_path=workbook_path,
        synced_at=synced_at,
        mirrored_records=mirrored_records,
        session_records=session_records,
        issues=tuple(issues),
    )


def build_sqlite_selected_record_result(
    *,
    record: Compensacao | None,
    workbook_path: str,
    synced_at: str,
    mirrored_records: int,
    session_records: int,
    strategy: str = "sqlite_detail",
) -> LocalSelectedRecordResult:
    return LocalSelectedRecordResult(
        source="sqlite",
        record=record,
        strategy=strategy,
        workbook_path=workbook_path,
        synced_at=synced_at,
        mirrored_records=mirrored_records,
        session_records=session_records,
    )


def build_session_duplicate_check_result(
    *,
    duplicate_row: int | None,
    workbook_path: str,
    synced_at: str,
    mirrored_records: int,
    session_records: int,
    issues: Sequence[str] = (),
    strategy: str = "session_duplicate",
) -> LocalDuplicateCheckResult:
    return LocalDuplicateCheckResult(
        source="session",
        duplicate_row=duplicate_row,
        strategy=strategy,
        workbook_path=workbook_path,
        synced_at=synced_at,
        mirrored_records=mirrored_records,
        session_records=session_records,
        issues=tuple(issues),
    )


def build_sqlite_duplicate_check_result(
    *,
    duplicate_row: int | None,
    workbook_path: str,
    synced_at: str,
    mirrored_records: int,
    session_records: int,
    strategy: str = "sqlite_duplicate",
) -> LocalDuplicateCheckResult:
    return LocalDuplicateCheckResult(
        source="sqlite",
        duplicate_row=duplicate_row,
        strategy=strategy,
        workbook_path=workbook_path,
        synced_at=synced_at,
        mirrored_records=mirrored_records,
        session_records=session_records,
    )


def validate_snapshot_against_runtime(
    workbook_path: str,
    *,
    fallback_records: Sequence[Compensacao],
    snapshot_reader_available: bool,
    snapshot: WorkbookSnapshotSummary | None,
    strategy: str,
) -> tuple[str, tuple[Compensacao, ...], WorkbookSnapshotSummary | None, LocalRecordReadResult | None]:
    normalized_path = normalize_session_path(workbook_path)
    fallback = tuple(fallback_records)
    if not normalized_path or not snapshot_reader_available:
        return (
            normalized_path,
            fallback,
            None,
            build_session_record_result(
                fallback,
                workbook_path=normalized_path,
                strategy=strategy,
            ),
        )
    assert snapshot is not None

    expected_count = len(fallback)
    if not snapshot.synced_at:
        return (
            normalized_path,
            fallback,
            None,
            build_session_record_result(
                fallback,
                workbook_path=normalized_path,
                strategy=strategy,
                mirrored_records=int(snapshot.record_count),
                synced_at=str(snapshot.synced_at or ""),
                issues=("Espelho local ainda nao sincronizado para esta planilha.",),
            ),
        )
    if int(snapshot.record_count) != expected_count:
        return (
            normalized_path,
            fallback,
            None,
            build_session_record_result(
                fallback,
                workbook_path=normalized_path,
                strategy=strategy,
                mirrored_records=int(snapshot.record_count),
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
        current_mtime_ns, current_size = read_source_file_identity(normalized_path)
        if current_mtime_ns <= 0 and current_size <= 0:
            return (
                normalized_path,
                fallback,
                None,
                build_session_record_result(
                    fallback,
                    workbook_path=normalized_path,
                    strategy=strategy,
                    mirrored_records=int(snapshot.record_count),
                    synced_at=str(snapshot.synced_at or ""),
                    issues=("Nao foi possivel validar o arquivo da planilha contra o espelho local.",),
                ),
            )
        if current_mtime_ns != snapshot_mtime_ns or current_size != snapshot_size:
            return (
                normalized_path,
                fallback,
                None,
                build_session_record_result(
                    fallback,
                    workbook_path=normalized_path,
                    strategy=strategy,
                    mirrored_records=int(snapshot.record_count),
                    synced_at=str(snapshot.synced_at or ""),
                    issues=("Arquivo foi alterado desde a ultima sincronizacao do espelho local.",),
                ),
            )
    return normalized_path, fallback, snapshot, None
