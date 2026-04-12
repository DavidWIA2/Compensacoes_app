from datetime import date

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.tcra_records_service import (
    AGENDA_SCOPE_30D,
    AGENDA_SCOPE_7D,
    AGENDA_SCOPE_HOJE,
    AGENDA_SCOPE_PENDENTES,
    AGENDA_SCOPE_VENCIDOS,
    QUICK_FILTER_ALERTAS,
    QUICK_FILTER_PROXIMOS,
    QUICK_FILTER_SEM_NUMERO,
    QUICK_FILTER_SEM_MOVIMENTACAO,
    QUICK_FILTER_SEM_RESPONSAVEL,
    TcraAgendaItem,
    TcraOperationalRules,
    TcraQualityQueueItem,
    STATUS_CUMPRIDO,
    STATUS_PRAZO_VENCIDO,
    STATUS_RELATORIO_PENDENTE,
    TCRA_WORKFLOW_EVENT_RESOLVED,
    apply_quick_filter,
    build_operational_agenda,
    build_work_agenda,
    build_filter_facets,
    build_quality_queue,
    build_record_overview,
    compute_metrics,
    filter_agenda_items_by_scope,
    filter_tcras,
    normalize_orgao_label,
    normalize_status_label,
    operational_sort_key,
    resolve_operational_issues,
    resolve_record_consistency_issues,
    suggest_issue_fix,
)


def make_tcra(**overrides) -> Tcra:
    base = {
        "uid": "tcra-1",
        "numero_processo": "26207/2019",
        "numero_tcra": "TCRA-2019-001",
        "local": "Sistema de Lazer",
        "endereco": "Rua Ireneu Couto - Itamarati",
        "bairro": "Itamarati",
        "orgao_acompanhamento": "CETESB",
        "status": "Em acompanhamento",
        "data_assinatura": date(2019, 6, 1),
        "prazo_final": date(2026, 4, 1),
        "periodicidade_relatorio_meses": 60,
        "data_ultimo_relatorio": date(2024, 4, 11),
        "data_proximo_relatorio": date(2026, 3, 10),
        "area_m2": 2920.0,
        "numero_mudas_previsto": 486,
        "servicos_exigidos": "Tratos culturais regulares",
        "responsavel_execucao": "Secretaria Municipal",
        "observacoes": "",
        "mpsp_relacionado": "Nao",
        "inquerito_civil": "",
        "eventos": [
            TcraEvento(
                sequence=1,
                data_evento=date(2024, 4, 11),
                tipo_evento="Relatorio",
                descricao="Relatorio periodico protocolado",
                prazo_resultante=date(2026, 3, 10),
                status_resultante="Em acompanhamento",
            )
        ],
    }
    base.update(overrides)
    return Tcra(**base)


def test_compute_metrics_identifies_operational_buckets():
    today = date(2026, 4, 3)
    records = [
        make_tcra(uid="tcra-1", responsavel_execucao=""),
        make_tcra(
            uid="tcra-2",
            numero_processo="193/2011",
            numero_tcra="TCRA-2011-002",
            local="CEMOSAR",
            bairro="Centro",
            status="Cumprido",
            prazo_final=date(2024, 1, 1),
            data_proximo_relatorio=date(2024, 1, 1),
            mpsp_relacionado="Sim",
            responsavel_execucao="",
        ),
        make_tcra(
            uid="tcra-3",
            numero_processo="444/2022",
            numero_tcra="",
            local="Varjao",
            bairro="Varjao",
            orgao_acompanhamento="MPSP",
            status="Em acompanhamento",
            prazo_final=date(2027, 1, 1),
            data_proximo_relatorio=date(2026, 1, 10),
            inquerito_civil="Procedimento em andamento",
            responsavel_execucao="",
        ),
        make_tcra(
            uid="tcra-4",
            numero_processo="555/2025",
            numero_tcra="TCRA-2025-004",
            local="Parque Linear",
            bairro="Jardim Novo",
            orgao_acompanhamento="CETESB",
            status="Em acompanhamento",
            prazo_final=date(2027, 5, 1),
            data_proximo_relatorio=date(2026, 8, 1),
            eventos=[],
        ),
    ]

    metrics = compute_metrics(records, today=today)

    assert metrics["count_total"] == 4
    assert metrics["count_ativos"] == 3
    assert metrics["count_cumpridos"] == 1
    assert metrics["count_prazo_vencido"] == 1
    assert metrics["count_relatorio_pendente"] == 2
    assert metrics["count_mpsp_relacionados"] == 2
    assert metrics["count_com_eventos"] == 3
    assert metrics["count_sem_numero_tcra"] == 1
    assert metrics["count_alertas"] == 2
    assert metrics["count_relatorio_proximo_30d"] == 0
    assert metrics["count_sem_responsavel"] == 3


def test_filter_tcras_applies_text_status_orgao_year_and_flags():
    today = date(2026, 4, 3)
    records = [
        make_tcra(uid="tcra-1", numero_processo="111/2021", local="Parque Ecologico"),
        make_tcra(
            uid="tcra-2",
            numero_processo="222/2022",
            local="Varjao",
            bairro="Varjao",
            orgao_acompanhamento="MPSP",
            status="Em acompanhamento",
            prazo_final=date(2027, 1, 1),
            data_proximo_relatorio=date(2026, 1, 10),
            mpsp_relacionado="Sim",
        ),
        make_tcra(
            uid="tcra-3",
            numero_processo="333/2022",
            local="Horto",
            bairro="Centro",
            orgao_acompanhamento="CETESB",
            status="Cumprido",
        ),
    ]

    filtered = filter_tcras(
        records,
        text="varjao",
        status=STATUS_RELATORIO_PENDENTE,
        selected_orgaos=["MPSP"],
        selected_bairros=["Varjao"],
        selected_year="2022",
        only_mpsp=True,
        only_relatorio_pendente=True,
        today=today,
    )

    assert [record.uid for record in filtered] == ["tcra-2"]


def test_build_filter_facets_and_overview_return_future_ui_summary():
    today = date(2026, 4, 3)
    records = [
        make_tcra(uid="tcra-1", numero_processo="111/2021", responsavel_execucao=""),
        make_tcra(
            uid="tcra-2",
            numero_processo="222/2022",
            numero_tcra="",
            local="Varjao",
            bairro="Centro",
            orgao_acompanhamento="MPSP",
            status="Em acompanhamento",
            prazo_final=date(2027, 1, 1),
            data_proximo_relatorio=date(2026, 1, 10),
            mpsp_relacionado="Sim",
            responsavel_execucao="",
        ),
        make_tcra(
            uid="tcra-3",
            numero_processo="333/2023",
            local="Horto",
            bairro="Jardim Novo",
            orgao_acompanhamento="CETESB",
            status="Cumprido",
            prazo_final=date(2024, 1, 1),
            data_proximo_relatorio=date(2024, 1, 1),
            responsavel_execucao="",
        ),
        make_tcra(
            uid="tcra-4",
            numero_processo="444/2024",
            local="Parque Linear",
            bairro="Centro",
            orgao_acompanhamento="DAAE",
            status="Em acompanhamento",
            prazo_final=date(2027, 5, 1),
            data_proximo_relatorio=date(2026, 5, 1),
            eventos=[],
            responsavel_execucao="",
        ),
    ]

    facets = build_filter_facets(records, today=today)
    overview = build_record_overview(records, today=today)

    assert facets.total_count == 4
    assert facets.statuses == (
        STATUS_CUMPRIDO,
        "Em acompanhamento",
        STATUS_PRAZO_VENCIDO,
        STATUS_RELATORIO_PENDENTE,
    )
    assert facets.orgaos_acompanhamento == ("CETESB", "DAAE", "MPSP")
    assert facets.anos_processo == ("2024", "2023", "2022", "2021")

    assert overview.total_count == 4
    assert overview.cumpridos_count == 1
    assert overview.prazo_vencido_count == 1
    assert overview.relatorio_pendente_count == 2
    assert overview.sem_numero_tcra_count == 1
    assert overview.upcoming_30d_count == 1
    assert overview.sem_responsavel_count == 4
    assert overview.alertas_count == 2
    assert overview.upcoming_reports[0].uid == "tcra-2"


def test_tcra_normalization_quick_filters_and_operational_sort():
    today = date(2026, 4, 3)
    records = [
        make_tcra(
            uid="tcra-1",
            status="relatorio atrasado",
            orgao_acompanhamento="ministerio publico",
            numero_tcra="",
            responsavel_execucao="",
            data_proximo_relatorio=date(2026, 3, 20),
        ),
        make_tcra(
            uid="tcra-2",
            status="cumprido",
            orgao_acompanhamento="cetesb",
            prazo_final=date(2025, 1, 1),
            data_proximo_relatorio=date(2025, 1, 1),
        ),
        make_tcra(
            uid="tcra-3",
            status="em acompanhamento",
            orgao_acompanhamento="daae sao carlos",
            prazo_final=date(2026, 6, 1),
            data_proximo_relatorio=date(2026, 4, 20),
            responsavel_execucao="Equipe local",
        ),
    ]

    assert normalize_status_label("relatorio atrasado") == STATUS_RELATORIO_PENDENTE
    assert normalize_status_label("cumprido") == STATUS_CUMPRIDO
    assert normalize_orgao_label("ministerio publico") == "MPSP"
    assert normalize_orgao_label("daae sao carlos") == "DAAE"

    assert [record.uid for record in apply_quick_filter(records, mode=QUICK_FILTER_ALERTAS, today=today)] == ["tcra-1"]
    assert [record.uid for record in apply_quick_filter(records, mode=QUICK_FILTER_PROXIMOS, today=today)] == ["tcra-3"]
    assert [record.uid for record in apply_quick_filter(records, mode=QUICK_FILTER_SEM_NUMERO, today=today)] == ["tcra-1"]
    assert [record.uid for record in apply_quick_filter(records, mode=QUICK_FILTER_SEM_RESPONSAVEL, today=today)] == ["tcra-1"]
    assert [record.uid for record in apply_quick_filter(records, mode=QUICK_FILTER_SEM_MOVIMENTACAO, today=today)] == ["tcra-1", "tcra-3"]

    sorted_records = sorted(records, key=lambda record: operational_sort_key(record, today=today))
    assert [record.uid for record in sorted_records] == ["tcra-1", "tcra-3", "tcra-2"]


def test_tcra_operational_agenda_and_consistency_rules():
    today = date(2026, 4, 3)
    records = [
        make_tcra(uid="tcra-1", prazo_final=date(2026, 3, 20), data_proximo_relatorio=date(2026, 4, 10)),
        make_tcra(
            uid="tcra-2",
            numero_tcra="",
            responsavel_execucao="",
            prazo_final=date(2026, 8, 1),
            data_proximo_relatorio=date(2026, 4, 20),
        ),
        make_tcra(uid="tcra-3", status="Cumprido", data_proximo_relatorio=date(2026, 5, 1)),
    ]

    agenda = build_operational_agenda(records, today=today, limit=10)

    assert isinstance(agenda[0], TcraAgendaItem)
    assert [item.uid for item in agenda] == ["tcra-1", "tcra-2", "tcra-3"]
    assert agenda[0].prioridade_label == "Prazo vencido"
    assert "Relatório nos próximos" in agenda[1].detalhe

    issues = resolve_operational_issues(records[1], today=today)
    assert issues == ("Relatório nos próximos 30 dias", "Sem número TCRA", "Sem responsável")

    consistency = resolve_record_consistency_issues(records[2], today=today)
    assert consistency == ("TCRA cumprido/arquivado não deve manter próximo relatório em aberto.",)


def test_tcra_operational_agenda_honors_custom_rules_and_resolved_workflow():
    today = date(2026, 4, 3)
    recent_event = TcraEvento(
        sequence=1,
        data_evento=date(2026, 3, 30),
        tipo_evento="Relatorio",
        descricao="Relatorio recente",
        prazo_resultante=date(2026, 4, 20),
        status_resultante="Em acompanhamento",
    )
    upcoming = make_tcra(
        uid="tcra-window",
        prazo_final=date(2026, 12, 1),
        data_ultimo_relatorio=date(2026, 3, 30),
        data_proximo_relatorio=date(2026, 4, 20),
        eventos=[recent_event],
    )
    assert [item.uid for item in build_operational_agenda([upcoming], today=today, limit=10)] == ["tcra-window"]
    assert (
        build_operational_agenda(
            [upcoming],
            today=today,
            limit=10,
            rules=TcraOperationalRules(upcoming_report_window_days=7, stale_movement_window_days=180),
        )
        == ()
    )

    resolved = make_tcra(
        uid="tcra-resolved",
        prazo_final=date(2026, 3, 20),
        data_proximo_relatorio=date(2026, 4, 10),
        eventos=[
            TcraEvento(
                sequence=1,
                data_evento=today,
                tipo_evento=TCRA_WORKFLOW_EVENT_RESOLVED,
                descricao="issue=prazo_vencido; pendencia tratada",
                status_resultante="Em acompanhamento",
            )
        ],
    )
    assert build_operational_agenda([resolved], today=today, limit=10) == ()


def test_tcra_work_agenda_scopes_and_issue_suggestions():
    today = date(2026, 4, 3)
    records = [
        make_tcra(uid="tcra-1", prazo_final=date(2026, 3, 20), data_proximo_relatorio=date(2026, 4, 10)),
        make_tcra(uid="tcra-2", data_proximo_relatorio=date(2026, 4, 5), prazo_final=date(2026, 8, 1)),
        make_tcra(
            uid="tcra-3",
            numero_tcra="",
            responsavel_execucao="",
            orgao_acompanhamento="",
            prazo_final=date(2026, 8, 1),
            data_proximo_relatorio=date(2026, 8, 1),
        ),
    ]

    agenda = build_operational_agenda(records, today=today, limit=10)

    assert [item.uid for item in filter_agenda_items_by_scope(agenda, scope=AGENDA_SCOPE_VENCIDOS, today=today)] == ["tcra-1"]
    assert [item.uid for item in filter_agenda_items_by_scope(agenda, scope=AGENDA_SCOPE_HOJE, today=today)] == ["tcra-1", "tcra-3"]
    assert [item.uid for item in build_work_agenda(records, scope=AGENDA_SCOPE_7D, today=today, limit=10)] == ["tcra-1", "tcra-2", "tcra-3"]
    assert [item.uid for item in build_work_agenda(records, scope=AGENDA_SCOPE_30D, today=today, limit=10)] == ["tcra-1", "tcra-2", "tcra-3"]
    assert [item.uid for item in build_work_agenda(records, scope=AGENDA_SCOPE_PENDENTES, today=today, limit=10)] == ["tcra-3"]

    assert "número oficial" in suggest_issue_fix("Sem numero TCRA").lower()
    assert "sequência cronológica" in suggest_issue_fix("Proximo relatorio nao pode ser anterior ao ultimo relatorio.").lower()


def test_tcra_quality_queue_prioritizes_critical_and_cadastro_items():
    today = date(2026, 4, 3)
    records = [
        make_tcra(
            uid="tcra-1",
            status="Cumprido",
            data_proximo_relatorio=date(2026, 5, 1),
            responsavel_execucao="Equipe local",
        ),
        make_tcra(
            uid="tcra-2",
            numero_tcra="",
            responsavel_execucao="",
            orgao_acompanhamento="",
            data_proximo_relatorio=date(2026, 8, 1),
        ),
        make_tcra(
            uid="tcra-3",
            numero_tcra="TCRA-2026-003",
            responsavel_execucao="Equipe local",
            orgao_acompanhamento="CETESB",
            data_proximo_relatorio=date(2026, 6, 1),
        ),
    ]

    queue = build_quality_queue(records, today=today, limit=10)

    assert isinstance(queue[0], TcraQualityQueueItem)
    assert [item.uid for item in queue] == ["tcra-1", "tcra-2"]
    assert queue[0].severity_label == "Critico"
    assert "próximo relatório" in queue[0].detalhe.lower()
    assert queue[1].severity_label == "Cadastro"
    assert set(queue[1].issues) == {"Sem número TCRA", "Sem responsável", "Sem órgão"}
