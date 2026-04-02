from app.application.use_cases.export_operations import (
    ExportFilterState,
    ExportReportingUseCases,
)
from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.application.use_cases.persistence_monitoring import PersistenceRecordOverviewReport


class FakePersistenceUseCases:
    def __init__(self, report):
        self.report = report
        self.calls = []

    def build_record_overview_report(self, workbook_path, *, top_microbacias_limit=3, sample_limit=0):
        self.calls.append((workbook_path, top_microbacias_limit, sample_limit))
        return self.report


def test_export_reporting_builds_filter_summary():
    use_cases = ExportReportingUseCases(None)

    summary = use_cases.build_filter_summary(
        ExportFilterState(
            search_text="Gregorio",
            status="Pendentes",
            selected_micros=("Gregorio",),
            micro_all_selected=False,
            selected_eletronicos=("SIM",),
            eletronico_all_selected=False,
            year="2026",
        )
    )

    assert summary == "Busca: Gregorio | Status: Pendentes | Microbacias: Gregorio | Tipo: Eletrônico | Ano: 2026"


def test_export_reporting_builds_dashboard_payload_with_persistence_summary():
    report = PersistenceRecordOverviewReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-31T12:00:00+00:00",
        total_records=8,
        compensados_count=3,
        pendentes_count=5,
        records_with_plantios_count=2,
        records_without_microbacia_count=1,
        records_without_coordinates_count=4,
        top_microbacias=(("Gregorio", 5), ("Medeiros", 3)),
    )
    persistence_use_cases = FakePersistenceUseCases(report)
    use_cases = ExportReportingUseCases(persistence_use_cases)

    payload = use_cases.build_dashboard_export_payload(
        metrics={
            "count_total": 8,
            "total_geral": 50.0,
            "total_pendente": 30.0,
            "total_compensado": 20.0,
        },
        filter_state=ExportFilterState(search_text="Gregorio"),
        chart_images=["pie.png", "", "bar.png"],
        workbook_path="dummy.xlsx",
        record_read_status=LocalRecordReadStatus(
            status="sqlite",
            source="sqlite",
            strategy="sqlite_query",
            workbook_path="dummy.xlsx",
            synced_at="2026-03-31T12:00:00+00:00",
            mirrored_records=8,
            session_records=8,
            filtered_records=5,
        ),
    )

    assert persistence_use_cases.calls == [("dummy.xlsx", 3, 0)]
    assert payload.filter_summary == "Busca: Gregorio"
    assert payload.chart_images == ("pie.png", "bar.png")
    assert any("Espelho local: 8 registro(s)" in line for line in payload.kpi_lines)
    assert any("Top microbacias no espelho: Gregorio: 5 | Medeiros: 3" in line for line in payload.kpi_lines)
    assert any("Leitura operacional: espelho local (SQLite)" in line for line in payload.kpi_lines)
