from datetime import date, datetime

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.ui.tabs.tcra_tab_form_support import (
    build_empty_form_snapshot,
    build_form_preview_data,
    build_record_form_snapshot,
    capture_form_state_snapshot,
    issue_supports_safe_fix,
    resolve_issue_focus_field,
    resolve_safe_fix_updates,
    restore_form_eventos_snapshot,
)


def make_tcra(**overrides) -> Tcra:
    base = {
        "uid": "tcra-1",
        "numero_processo": "26207/2019",
        "numero_tcra": "",
        "local": "Sistema de Lazer - Residencial Itamarati",
        "endereco": "Rua Ireneu Couto",
        "bairro": "Residencial Itamarati",
        "orgao_acompanhamento": "",
        "status": "Prazo vencido",
        "data_assinatura": date(2019, 6, 1),
        "prazo_final": date(2024, 4, 1),
        "periodicidade_relatorio_meses": 60,
        "data_ultimo_relatorio": date(2024, 4, 11),
        "data_proximo_relatorio": date(2025, 3, 10),
        "area_m2": 2920.0,
        "numero_mudas_previsto": 486,
        "servicos_exigidos": "Tratos culturais regulares",
        "responsavel_execucao": "",
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


def test_form_support_captures_and_restores_event_rows():
    eventos = [
        TcraEvento(
            sequence=1,
            data_evento=date(2025, 2, 1),
            tipo_evento="Relatorio",
            descricao="Primeiro envio",
            prazo_resultante=date(2025, 8, 1),
            status_resultante="Em acompanhamento",
        )
    ]
    snapshot = capture_form_state_snapshot(
        uid="",
        numero_processo="26207/2019",
        numero_tcra="",
        local="Itamarati",
        endereco="Rua A",
        bairro="Centro",
        orgao="CETESB",
        status="Em acompanhamento",
        data_assinatura="01/06/2019",
        prazo_final="01/04/2026",
        periodicidade="60",
        data_ultimo_relatorio="11/04/2024",
        data_proximo_relatorio="10/03/2025",
        area_m2="2920",
        numero_mudas="486",
        responsavel="Secretaria",
        mpsp=False,
        inquerito="",
        servicos="Tratos culturais",
        observacoes="Observacoes",
        eventos=eventos,
    )

    restored = restore_form_eventos_snapshot(
        snapshot["eventos"],
        parse_date=lambda text, _label: datetime.strptime(text, "%d/%m/%Y").date(),
    )

    assert snapshot["numero_processo"] == "26207/2019"
    assert len(restored) == 1
    assert restored[0].tipo_evento == "Relatório"
    assert restored[0].prazo_resultante == date(2025, 8, 1)


def test_form_support_builds_record_and_empty_snapshots():
    record = make_tcra(
        uid="tcra-9",
        numero_tcra="TCRA-9",
        orgao_acompanhamento="CETESB",
        responsavel_execucao="Secretaria Municipal",
        mpsp_relacionado="Sim",
    )

    record_snapshot = build_record_form_snapshot(record)
    empty_snapshot = build_empty_form_snapshot()

    assert record_snapshot["uid"] == "tcra-9"
    assert record_snapshot["numero_tcra"] == "TCRA-9"
    assert record_snapshot["orgao"] == "CETESB"
    assert record_snapshot["responsavel"] == "Secretaria Municipal"
    assert record_snapshot["mpsp"] is True
    assert empty_snapshot["status"] == "Em acompanhamento"
    assert empty_snapshot["numero_processo"] == ""
    assert empty_snapshot["eventos"] == ()


def test_form_support_builds_preview_and_safe_fix_metadata():
    record = make_tcra()
    snapshot = capture_form_state_snapshot(
        uid=record.uid,
        numero_processo=record.numero_processo,
        numero_tcra=record.numero_tcra,
        local=record.local,
        endereco=record.endereco,
        bairro=record.bairro,
        orgao=record.orgao_acompanhamento,
        status=record.status,
        data_assinatura="01/06/2019",
        prazo_final="01/04/2024",
        periodicidade="60",
        data_ultimo_relatorio="11/04/2024",
        data_proximo_relatorio="10/03/2025",
        area_m2="2920",
        numero_mudas="486",
        responsavel=record.responsavel_execucao,
        mpsp=False,
        inquerito="",
        servicos=record.servicos_exigidos,
        observacoes=record.observacoes,
        eventos=record.eventos,
    )

    preview = build_form_preview_data(
        snapshot=snapshot,
        preview_record=record,
        recent_event_lines=("11/04/2024 - Relatorio - Em acompanhamento",),
        today=date(2026, 4, 3),
    )

    assert "Correção assistida:" in preview.guidance_text
    assert "Processo: 26207/2019" in preview.details_text
    assert "Timeline recente:" in preview.details_text
    assert preview.primary_issue
    assert resolve_issue_focus_field("Sem orgao de acompanhamento informado.") == "orgao"
    assert issue_supports_safe_fix("Proximo relatorio nao pode ser anterior ao ultimo relatorio.")
    assert resolve_safe_fix_updates(
        "Proximo relatorio nao pode ser anterior ao ultimo relatorio.",
        {"data_ultimo_relatorio": "11/04/2024"},
    ) == {"data_proximo_relatorio": "11/04/2024"}
