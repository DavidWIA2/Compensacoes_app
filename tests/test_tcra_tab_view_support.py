from datetime import date

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.tcra_records_service import TcraAgendaItem, TcraQualityQueueItem
from app.ui.tabs.tcra_tab_view_support import (
    MAIN_TABLE_HEADERS,
    MAIN_TABLE_STATUS_COLUMN,
    build_agenda_overview_rows,
    build_main_table_rows,
    build_quality_overview_rows,
    build_selection_state,
)


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
        "observacoes": "Relatório a cada 5 anos",
        "mpsp_relacionado": "Não",
        "inquerito_civil": "",
        "eventos": [
            TcraEvento(
                sequence=1,
                data_evento=date(2024, 4, 11),
                tipo_evento="Relatório",
                descricao="Relatório periódico protocolado",
                prazo_resultante=date(2025, 3, 10),
                status_resultante="Em acompanhamento",
            )
        ],
    }
    base.update(overrides)
    return Tcra(**base)


def test_view_support_builds_main_table_rows_with_operational_values():
    rows = build_main_table_rows(
        [
            make_tcra(uid="tcra-1", mpsp_relacionado="Sim"),
            make_tcra(uid="tcra-2", numero_tcra="", data_proximo_relatorio=None),
        ],
        today=date(2026, 4, 3),
    )

    assert len(rows) == 2
    assert rows[0].uid == "tcra-1"
    assert MAIN_TABLE_HEADERS[MAIN_TABLE_STATUS_COLUMN] == "Status"
    assert rows[0].values[0].startswith("Vencido (")
    assert rows[0].values[1] == "26207/2019"
    assert rows[0].values[3]
    assert rows[0].values[4] == "Cobrar cumprimento / revisar prazo"
    assert rows[0].values[8] == "CETESB + MPSP"
    assert "Status operacional:" in rows[0].tooltip
    assert "Próxima ação:" in rows[0].tooltip


def test_view_support_builds_agenda_and_quality_rows():
    agenda_rows = build_agenda_overview_rows(
        (
            TcraAgendaItem(
                uid="tcra-1",
                priority_rank=0,
                prioridade_label="Prazo vencido",
                termo_label="26207/2019",
                local="Itamarati",
                detalhe="Prazo final vencido",
                risk_score=80,
            ),
        )
    )
    quality_rows = build_quality_overview_rows(
        (
            TcraQualityQueueItem(
                uid="tcra-2",
                severity_rank=1,
                severity_label="Cadastro",
                termo_label="7205/2014",
                local="Santa Fé",
                detalhe="Sem responsável",
                issues=("Sem responsável de execução.",),
            ),
        )
    )

    assert agenda_rows[0].values[0] == "Prazo vencido (80)"
    assert "Prazo final vencido" in agenda_rows[0].tooltip
    assert "Risco 80" in agenda_rows[0].tooltip
    assert quality_rows[0].values[1] == "7205/2014"
    assert "Sem responsável de execução." in quality_rows[0].tooltip


def test_view_support_builds_selection_state_for_empty_single_and_bulk_selection():
    records = [
        make_tcra(uid="tcra-1"),
        make_tcra(uid="tcra-2", numero_processo="7205/2014", numero_tcra=""),
    ]

    empty_state = build_selection_state(
        filtered_records=records,
        selected_rows=[],
        selected_records=[],
        current_row=-1,
    )
    single_state = build_selection_state(
        filtered_records=records,
        selected_rows=[1],
        selected_records=[records[1]],
        current_row=1,
    )
    bulk_state = build_selection_state(
        filtered_records=records,
        selected_rows=[0, 1],
        selected_records=records,
        current_row=-1,
    )

    assert empty_state.has_selection is False
    assert empty_state.selection_summary == "Nenhum termo selecionado"
    assert single_state.has_selection is True
    assert single_state.selection_summary == "1 termo selecionado"
    assert single_state.primary_record is records[1]
    assert bulk_state.bulk_action_text == "Ações em lote (2)"
    assert bulk_state.primary_record is records[0]
