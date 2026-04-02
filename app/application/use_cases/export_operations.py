from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.application.use_cases.persistence_monitoring import (
    PersistenceMonitoringUseCases,
    PersistenceRecordOverviewReport,
)
from app.services.audit_service import format_audit_timestamp
from app.services.records_service import display_tipo_value


@dataclass(frozen=True)
class ExportFilterState:
    search_text: str = ""
    status: str = "Todos"
    selected_micros: tuple[str, ...] = ()
    micro_all_selected: bool = True
    selected_eletronicos: tuple[str, ...] = ()
    eletronico_all_selected: bool = True
    year: str = "Todos"


@dataclass(frozen=True)
class DashboardExportPayload:
    kpi_lines: tuple[str, ...]
    filter_summary: str
    chart_images: tuple[str, ...]
    record_overview: PersistenceRecordOverviewReport | None = None
    record_read_status: LocalRecordReadStatus | None = None


class ExportReportingUseCases:
    def __init__(self, persistence_use_cases: PersistenceMonitoringUseCases | None):
        self.persistence_use_cases = persistence_use_cases

    def build_metrics_kpi_rows(self, metrics: Mapping[str, object]) -> list[tuple[str, str]]:
        return [
            ("Total de Registros", str(metrics["count_total"])),
            ("Total de Mudas", f"{metrics['total_geral']:g}"),
            ("Pendentes", f"{metrics['total_pendente']:g}"),
            ("Compensadas", f"{metrics['total_compensado']:g}"),
        ]

    def build_filter_summary(self, filter_state: ExportFilterState) -> str:
        parts: list[str] = []
        search_text = str(filter_state.search_text or "").strip()
        if search_text:
            parts.append(f"Busca: {search_text}")

        status = str(filter_state.status or "").strip()
        if status and status != "Todos":
            parts.append(f"Status: {status}")

        if not filter_state.micro_all_selected:
            micros = ", ".join(item for item in filter_state.selected_micros if str(item).strip())
            parts.append(f"Microbacias: {micros or 'Nenhuma'}")

        if not filter_state.eletronico_all_selected:
            eletronicos = ", ".join(
                display_tipo_value(item)
                for item in filter_state.selected_eletronicos
                if str(item).strip()
            )
            parts.append(f"Tipo: {eletronicos or 'Nenhum'}")

        year = str(filter_state.year or "").strip()
        if year and year != "Todos":
            parts.append(f"Ano: {year}")

        return "Sem filtros aplicados" if not parts else " | ".join(parts)

    def resolve_dashboard_record_overview(
        self,
        *,
        workbook_path: str,
        cached_report: PersistenceRecordOverviewReport | None = None,
        top_microbacias_limit: int = 3,
        sample_limit: int = 0,
    ) -> PersistenceRecordOverviewReport | None:
        if cached_report is not None:
            return cached_report

        normalized_path = str(workbook_path or "").strip()
        if not normalized_path or self.persistence_use_cases is None:
            return None

        return self.persistence_use_cases.build_record_overview_report(
            normalized_path,
            top_microbacias_limit=top_microbacias_limit,
            sample_limit=sample_limit,
        )

    def build_dashboard_persistence_lines(
        self,
        report: PersistenceRecordOverviewReport | None,
    ) -> list[str]:
        if report is None or report.status in {"indisponivel", "ausente"}:
            return []

        lines = [
            (
                f"Espelho local: {report.total_records} registro(s), "
                f"{report.compensados_count} compensados, {report.pendentes_count} pendentes"
            ),
            (
                f"Cobertura de plantios: {report.records_with_plantios_count} registros com plantios | "
                f"{report.records_without_microbacia_count} sem microbacia | "
                f"{report.records_without_coordinates_count} sem coordenadas"
            ),
        ]
        if report.top_microbacias:
            lines.append(
                "Top microbacias no espelho: "
                + " | ".join(f"{label}: {count}" for label, count in report.top_microbacias)
            )
        return lines

    def build_record_read_lines(self, status: LocalRecordReadStatus | None) -> list[str]:
        if status is None or status.status == "indisponivel":
            return []

        if status.uses_sqlite:
            lines = [
                (
                    f"Leitura operacional: espelho local (SQLite) | "
                    f"{status.filtered_records} registro(s) no recorte atual"
                )
            ]
            if status.strategy == "sqlite_query":
                lines.append("Modo de leitura local: consulta indexada.")
            if status.synced_at:
                lines.append(
                    f"Ultima sincronizacao valida: {format_audit_timestamp(status.synced_at)}"
                )
            return lines

        lines = [
            (
                f"Leitura operacional: sessao em memoria | "
                f"{status.filtered_records} registro(s) no recorte atual"
            )
        ]
        if status.issues:
            lines.append("Motivos do fallback: " + " | ".join(status.issues))
        return lines

    def build_dashboard_export_payload(
        self,
        *,
        metrics: Mapping[str, object],
        filter_state: ExportFilterState,
        chart_images: Iterable[str],
        workbook_path: str,
        cached_report: PersistenceRecordOverviewReport | None = None,
        record_read_status: LocalRecordReadStatus | None = None,
    ) -> DashboardExportPayload:
        report = self.resolve_dashboard_record_overview(
            workbook_path=workbook_path,
            cached_report=cached_report,
            top_microbacias_limit=3,
            sample_limit=0,
        )

        kpi_lines = [
            f"Total de registros: {metrics['count_total']}",
            f"Total de mudas: {metrics['total_geral']:g}",
            f"Pendentes: {metrics['total_pendente']:g}",
            f"Compensadas: {metrics['total_compensado']:g}",
        ]
        kpi_lines.extend(self.build_dashboard_persistence_lines(report))
        kpi_lines.extend(self.build_record_read_lines(record_read_status))

        return DashboardExportPayload(
            kpi_lines=tuple(kpi_lines),
            filter_summary=self.build_filter_summary(filter_state),
            chart_images=tuple(image for image in chart_images if image),
            record_overview=report,
            record_read_status=record_read_status,
        )
