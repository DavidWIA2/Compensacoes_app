from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.services.sqlite_mirror_service import WorkbookRecordOverview, WorkbookSnapshotSummary


class WorkbookSnapshotReader(Protocol):
    def get_workbook_snapshot_summary(self, workbook_path: str) -> WorkbookSnapshotSummary: ...


class WorkbookRecordOverviewReader(Protocol):
    def build_workbook_record_overview(
        self,
        workbook_path: str,
        *,
        top_microbacias_limit: int = 5,
        sample_limit: int = 5,
    ) -> WorkbookRecordOverview: ...


@dataclass(frozen=True)
class PersistenceStatusReport:
    status: str
    workbook_path: str
    synced_at: str
    mirrored_records: int
    mirrored_plantios: int
    mirrored_audit_events: int
    expected_records: int
    expected_audit_events: int
    issues: tuple[str, ...] = ()

    @property
    def is_healthy(self) -> bool:
        return self.status == "sincronizado"


@dataclass(frozen=True)
class PersistenceRecordSampleReport:
    excel_row: int
    uid: str
    av_tec: str
    microbacia: str
    compensado: str
    plantio_count: int


@dataclass(frozen=True)
class PersistenceRecordOverviewReport:
    status: str
    workbook_path: str
    synced_at: str
    total_records: int
    compensados_count: int
    pendentes_count: int
    records_with_plantios_count: int
    records_without_microbacia_count: int
    records_without_coordinates_count: int
    top_microbacias: tuple[tuple[str, int], ...] = ()
    sample_records: tuple[PersistenceRecordSampleReport, ...] = ()

    @property
    def is_available(self) -> bool:
        return self.status == "sincronizado"


class PersistenceMonitoringUseCases:
    def __init__(self, snapshot_reader: WorkbookSnapshotReader | None):
        self.snapshot_reader = snapshot_reader

    def build_status_report(
        self,
        workbook_path: str,
        *,
        expected_records: int,
        expected_audit_events: int,
    ) -> PersistenceStatusReport:
        normalized_path = str(workbook_path or "").strip()
        if not normalized_path:
            return PersistenceStatusReport(
                status="indisponivel",
                workbook_path="",
                synced_at="",
                mirrored_records=0,
                mirrored_plantios=0,
                mirrored_audit_events=0,
                expected_records=int(expected_records),
                expected_audit_events=int(expected_audit_events),
                issues=("Nenhuma planilha ativa para validar o espelho local.",),
            )

        if self.snapshot_reader is None:
            return PersistenceStatusReport(
                status="indisponivel",
                workbook_path=normalized_path,
                synced_at="",
                mirrored_records=0,
                mirrored_plantios=0,
                mirrored_audit_events=0,
                expected_records=int(expected_records),
                expected_audit_events=int(expected_audit_events),
                issues=("O espelho local em SQLite nao esta disponivel nesta sessao.",),
            )

        snapshot = self.snapshot_reader.get_workbook_snapshot_summary(normalized_path)
        issues: list[str] = []

        if not snapshot.synced_at:
            issues.append("A planilha ainda nao foi sincronizada para o espelho local.")
        if snapshot.record_count != int(expected_records):
            issues.append(
                f"Espelho local com {snapshot.record_count} registro(s), mas a sessao atual tem {int(expected_records)}."
            )
        if snapshot.audit_event_count != int(expected_audit_events):
            issues.append(
                (
                    f"Espelho local com {snapshot.audit_event_count} evento(s) auditados, "
                    f"mas a sessao atual possui {int(expected_audit_events)}."
                )
            )

        status = "sincronizado" if not issues else "atencao"
        if not snapshot.synced_at and snapshot.record_count <= 0 and snapshot.audit_event_count <= 0:
            status = "ausente"

        return PersistenceStatusReport(
            status=status,
            workbook_path=snapshot.workbook_path or normalized_path,
            synced_at=snapshot.synced_at,
            mirrored_records=int(snapshot.record_count),
            mirrored_plantios=int(snapshot.plantio_count),
            mirrored_audit_events=int(snapshot.audit_event_count),
            expected_records=int(expected_records),
            expected_audit_events=int(expected_audit_events),
            issues=tuple(issues),
        )

    def build_record_overview_report(
        self,
        workbook_path: str,
        *,
        top_microbacias_limit: int = 3,
        sample_limit: int = 3,
    ) -> PersistenceRecordOverviewReport:
        normalized_path = str(workbook_path or "").strip()
        if not normalized_path:
            return PersistenceRecordOverviewReport(
                status="indisponivel",
                workbook_path="",
                synced_at="",
                total_records=0,
                compensados_count=0,
                pendentes_count=0,
                records_with_plantios_count=0,
                records_without_microbacia_count=0,
                records_without_coordinates_count=0,
            )

        if self.snapshot_reader is None or not hasattr(self.snapshot_reader, "build_workbook_record_overview"):
            return PersistenceRecordOverviewReport(
                status="indisponivel",
                workbook_path=normalized_path,
                synced_at="",
                total_records=0,
                compensados_count=0,
                pendentes_count=0,
                records_with_plantios_count=0,
                records_without_microbacia_count=0,
                records_without_coordinates_count=0,
            )

        reader = self.snapshot_reader
        overview = reader.build_workbook_record_overview(
            normalized_path,
            top_microbacias_limit=int(top_microbacias_limit),
            sample_limit=int(sample_limit),
        )
        status = "sincronizado" if overview.synced_at or overview.total_records > 0 else "ausente"
        sample_records = tuple(
            PersistenceRecordSampleReport(
                excel_row=int(sample.excel_row),
                uid=str(sample.uid or ""),
                av_tec=str(sample.av_tec or ""),
                microbacia=str(sample.microbacia or ""),
                compensado=str(sample.compensado or ""),
                plantio_count=int(sample.plantio_count),
            )
            for sample in overview.sample_records
        )
        return PersistenceRecordOverviewReport(
            status=status,
            workbook_path=overview.workbook_path or normalized_path,
            synced_at=overview.synced_at,
            total_records=int(overview.total_records),
            compensados_count=int(overview.compensados_count),
            pendentes_count=int(overview.pendentes_count),
            records_with_plantios_count=int(overview.records_with_plantios_count),
            records_without_microbacia_count=int(overview.records_without_microbacia_count),
            records_without_coordinates_count=int(overview.records_without_coordinates_count),
            top_microbacias=tuple(overview.top_microbacias),
            sample_records=sample_records,
        )
