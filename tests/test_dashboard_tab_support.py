from app.application.use_cases.local_record_queries import LocalRecordReadStatus
from app.application.use_cases.persistence_monitoring import PersistenceRecordOverviewReport
from app.services.tcra_records_service import TcraAgendaItem, TcraRecordOverview
from app.ui.tabs.dashboard_tab_support import (
    build_compensation_chart_payload,
    build_dashboard_agenda_summary_text,
    build_dashboard_micro_palette_keys,
    build_local_overview_text,
    build_read_source_text,
    build_tcra_chart_payload,
    build_tcra_dashboard_export_context,
    build_tcra_agenda_text,
    build_tcra_summary_text,
)


def test_dashboard_tab_support_builds_local_overview_and_read_source_texts():
    report = PersistenceRecordOverviewReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-30T12:00:00+00:00",
        total_records=12,
        compensados_count=4,
        pendentes_count=8,
        records_with_plantios_count=3,
        records_without_microbacia_count=2,
        records_without_coordinates_count=5,
        top_microbacias=(("Gregorio", 7), ("Medeiros", 5)),
    )
    read_status = LocalRecordReadStatus(
        status="sqlite",
        source="sqlite",
        strategy="sqlite_query",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-31T12:00:00+00:00",
        mirrored_records=12,
        session_records=12,
        filtered_records=6,
    )

    overview_text = build_local_overview_text(report)
    read_text = build_read_source_text(read_status)

    assert "Cache local sincronizado: 12 registro(s)" in overview_text
    assert "Qualidade dos dados: 2 sem microbacia | 5 sem coordenadas" in overview_text
    assert "Top microbacias: Gregorio: 7 | Medeiros: 5" in overview_text
    assert "cache local sincronizado" in read_text
    assert "6 registro(s) no recorte" in read_text
    assert "consulta indexada no cache" in read_text


def test_dashboard_tab_support_builds_tcra_agenda_summary_and_palette_keys():
    overview = TcraRecordOverview(
        total_count=18,
        ativos_count=12,
        cumpridos_count=6,
        prazo_vencido_count=2,
        relatorio_pendente_count=3,
        mpsp_relacionados_count=5,
        com_eventos_count=10,
        sem_numero_tcra_count=4,
        upcoming_30d_count=2,
        sem_responsavel_count=3,
        alertas_count=5,
    )
    agenda = (
        TcraAgendaItem(
            uid="tcra-1",
            priority_rank=0,
            prioridade_label="Prazo vencido",
            termo_label="TCRA-2024-001",
            local="Parque Linear",
            detalhe="Prazo final em 01/04/2026.",
            status_operacional="Prazo vencido",
        ),
        TcraAgendaItem(
            uid="tcra-2",
            priority_rank=1,
            prioridade_label="Relatório pendente",
            termo_label="26207/2019",
            local="Sistema de Lazer",
            detalhe="Relatório previsto em 03/04/2026.",
            status_operacional="Relatório pendente",
        ),
    )
    metrics = {
        "count_total": 12,
        "total_pendente": 8,
        "pend_micro_sorted": (("Gregorio", 5), ("Gregorio", 3), ("Medeiros", 2)),
    }
    report = PersistenceRecordOverviewReport(
        status="sincronizado",
        workbook_path="dummy.xlsx",
        synced_at="2026-03-30T12:00:00+00:00",
        total_records=12,
        compensados_count=4,
        pendentes_count=8,
        records_with_plantios_count=3,
        records_without_microbacia_count=2,
        records_without_coordinates_count=5,
        top_microbacias=(("Gregorio", 7), ("Medeiros", 5)),
    )

    assert "18 | 12 ativos" in build_tcra_summary_text(overview)
    assert "Prazo vencido: TCRA-2024-001" in build_tcra_agenda_text(agenda)
    summary_text = build_dashboard_agenda_summary_text(metrics, overview, agenda)
    assert "Compensações: 12 registro(s) | 8 pendentes" in summary_text
    assert "TCRAs: 5 alerta(s)" in summary_text
    assert "Foco TCRA de hoje: Prazo vencido: TCRA-2024-001" in summary_text
    assert build_dashboard_micro_palette_keys(metrics, report) == ["Gregorio", "Medeiros"]


def test_dashboard_tab_support_builds_chart_payloads_and_tcra_export_context():
    overview = TcraRecordOverview(
        total_count=18,
        ativos_count=12,
        cumpridos_count=6,
        prazo_vencido_count=2,
        relatorio_pendente_count=3,
        mpsp_relacionados_count=5,
        com_eventos_count=10,
        sem_numero_tcra_count=4,
        upcoming_30d_count=2,
        sem_responsavel_count=3,
        alertas_count=5,
    )
    agenda = (
        TcraAgendaItem(
            uid="tcra-1",
            priority_rank=0,
            prioridade_label="Prazo vencido",
            termo_label="TCRA-2024-001",
            local="Parque Linear",
            detalhe="Prazo final em 01/04/2026.",
            status_operacional="Prazo vencido",
        ),
    )

    comp_payload = build_compensation_chart_payload(
        {"count_total": 12, "total_pendente": 8, "total_compensado": 4},
        is_dark=False,
        micro_palette_keys=["Gregorio", "Medeiros"],
    )
    tcra_payload = build_tcra_chart_payload(overview, is_dark=True)
    export_context = build_tcra_dashboard_export_context(overview, agenda)

    assert comp_payload["kind"] == "compensacoes"
    assert comp_payload["micro_palette_keys"] == ["Gregorio", "Medeiros"]
    assert tcra_payload["kind"] == "tcra"
    assert tcra_payload["status_rows"][0]["name"] == "Em acompanhamento"
    assert tcra_payload["attention_rows"][0]["label"] == "Alertas"
    assert export_context.title == "Painel TCRA"
    assert "Total de TCRAs: 18" in export_context.kpi_lines
    assert "Prazo vencido: TCRA-2024-001" in export_context.filter_summary
