from datetime import date

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.tcra_records_service import AGENDA_SCOPE_HOJE, build_record_search_index
from app.ui.tabs.tcra_tab_workspace import TcraWorkspaceFilters, build_workspace_snapshot


def make_tcra(**overrides) -> Tcra:
    base = {
        "uid": "tcra-1",
        "numero_processo": "26207/2019",
        "numero_tcra": "TCRA-2019-001",
        "local": "Sistema de Lazer - Residencial Itamarati",
        "endereco": "Rua Ireneu Couto",
        "bairro": "Residencial Itamarati",
        "orgao_acompanhamento": "CETESB",
        "status": "Em acompanhamento",
        "data_assinatura": date(2019, 6, 1),
        "prazo_final": date(2026, 4, 1),
        "periodicidade_relatorio_meses": 60,
        "data_ultimo_relatorio": date(2024, 4, 11),
        "data_proximo_relatorio": date(2025, 3, 10),
        "area_m2": 2920.0,
        "numero_mudas_previsto": 486,
        "servicos_exigidos": "Tratos culturais regulares",
        "responsavel_execucao": "Secretaria Municipal",
        "observacoes": "Relatorio a cada 5 anos",
        "mpsp_relacionado": "Nao",
        "inquerito_civil": "",
        "eventos": [
            TcraEvento(
                sequence=1,
                data_evento=date(2024, 4, 11),
                tipo_evento="Relatorio",
                descricao="Relatorio periodico protocolado",
                prazo_resultante=date(2025, 3, 10),
                status_resultante="Em acompanhamento",
            )
        ],
    }
    base.update(overrides)
    return Tcra(**base)


def test_build_workspace_snapshot_summarizes_counts_and_preview_limits():
    records = [
        make_tcra(uid="tcra-1", prazo_final=date(2024, 4, 1), data_proximo_relatorio=date(2025, 3, 10)),
        make_tcra(
            uid="tcra-2",
            numero_tcra="",
            numero_processo="7205/2014",
            local="Nascente Santa Fe",
            responsavel_execucao="",
            data_proximo_relatorio=date(2025, 4, 21),
        ),
        make_tcra(
            uid="tcra-3",
            numero_tcra="25129/2014",
            numero_processo="25129/2014",
            local="Sistema de Lazer - Jardim Gilbertoni",
            orgao_acompanhamento="",
            data_proximo_relatorio=date(2025, 4, 30),
        ),
    ]

    snapshot = build_workspace_snapshot(
        records,
        filters=TcraWorkspaceFilters(),
        search_index=build_record_search_index(records),
        agenda_scope=AGENDA_SCOPE_HOJE,
        agenda_expanded=False,
        quality_expanded=False,
        preview_limit=2,
        today=date(2026, 4, 3),
    )

    assert snapshot.results_text == "3 exibidos | 3 no recorte base | 3 no banco"
    assert snapshot.quick_filter_labels["all"] == "Todos (3)"
    assert snapshot.quick_filter_labels["alertas"] == "Alertas (3)"
    assert snapshot.context_text.startswith("3 termos |")
    assert snapshot.agenda_total_count >= 2
    assert len(snapshot.agenda_items) == 2
    assert snapshot.agenda_view_all_enabled is True
    assert "mostrando 2" in snapshot.agenda_summary_text
    assert snapshot.quality_total_count >= 2
    assert len(snapshot.quality_items) == min(snapshot.quality_total_count, 2)
    assert snapshot.quality_view_all_enabled is (snapshot.quality_total_count > 2)
    assert snapshot.upcoming_button_enabled is False


def test_build_workspace_snapshot_handles_empty_database():
    snapshot = build_workspace_snapshot(
        [],
        filters=TcraWorkspaceFilters(),
        search_index={},
        agenda_scope=AGENDA_SCOPE_HOJE,
        agenda_expanded=False,
        quality_expanded=False,
        preview_limit=3,
        today=date(2026, 4, 3),
    )

    assert snapshot.context_text == "Banco local de TCRA sem registros."
    assert snapshot.data_quality_text == "Qualidade cadastral: sem registros."
    assert snapshot.results_text == "0 exibidos | 0 no recorte base | 0 no banco"
    assert snapshot.agenda_items == ()
    assert snapshot.quality_items == ()
    assert snapshot.upcoming_button_enabled is False


def test_build_workspace_snapshot_filters_by_responsavel_and_stale_movement():
    records = [
        make_tcra(
            uid="tcra-1",
            numero_processo="111/2026",
            responsavel_execucao="Equipe Norte",
            data_ultimo_relatorio=date(2026, 3, 1),
            data_proximo_relatorio=date(2026, 12, 1),
        ),
        make_tcra(
            uid="tcra-2",
            numero_processo="222/2026",
            responsavel_execucao="Equipe Sul",
            data_ultimo_relatorio=date(2025, 1, 1),
            data_proximo_relatorio=date(2026, 12, 1),
            eventos=[],
        ),
    ]

    snapshot = build_workspace_snapshot(
        records,
        filters=TcraWorkspaceFilters(selected_responsaveis=("Equipe Sul",), quick_filter_mode="sem_movimentacao"),
        search_index=build_record_search_index(records),
        agenda_scope=AGENDA_SCOPE_HOJE,
        agenda_expanded=False,
        quality_expanded=False,
        preview_limit=3,
        today=date(2026, 4, 3),
    )

    assert [record.uid for record in snapshot.filtered_records] == ["tcra-2"]
    assert "Sem mov. (1)" in snapshot.quick_filter_labels["sem_movimentacao"]
