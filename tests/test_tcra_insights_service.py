from datetime import date

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.audit_service import AuditEvent
from app.services.tcra_insights_service import (
    build_audit_trend_summary,
    build_record_change_timeline_text,
    build_responsavel_digests,
    build_sla_queue,
    build_sla_summary,
    build_workload_snapshot,
    find_potential_duplicate_tcras,
    resolve_tcra_sla_profile,
)
from app.services.tcra_records_service import TcraOperationalRules


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
        "responsavel_execucao": "Equipe Norte",
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


def test_sla_queue_and_summary_capture_overdue_items():
    rules = TcraOperationalRules(treatment_sla_days=5, escalation_sla_days=10)
    overdue = make_tcra(uid="tcra-overdue", prazo_final=date(2026, 3, 1))
    due_today = make_tcra(uid="tcra-due", prazo_final=date(2026, 3, 29))

    overdue_profile = resolve_tcra_sla_profile(overdue, today=date(2026, 4, 12), rules=rules)
    due_today_profile = resolve_tcra_sla_profile(due_today, today=date(2026, 4, 3), rules=rules)
    queue = build_sla_queue([overdue, due_today], today=date(2026, 4, 3), rules=rules)
    summary = build_sla_summary([overdue, due_today], today=date(2026, 4, 3), rules=rules)

    assert overdue_profile.status == "escalated"
    assert due_today_profile.status == "due_today"
    assert queue[0].uid == "tcra-overdue"
    assert summary.total_items == 2
    assert "Prazo interno de tratamento" in summary.summary_text
    assert "Prazo interno de tratamento" in overdue_profile.summary


def test_duplicate_detection_flags_similar_context():
    reference = make_tcra(uid="tcra-ref")
    imported = make_tcra(
        uid="novo",
        numero_tcra="TCRA-2019-001A",
        numero_processo="26207/2019",
        local="Sistema de Lazer - Itamarati",
        endereco="Rua Ireneu Couto",
    )

    matches = find_potential_duplicate_tcras(imported, [reference], limit=3)

    assert matches
    assert matches[0].uid == "tcra-ref"
    assert matches[0].score >= 72


def test_workload_snapshot_and_digests_summarize_distribution():
    records = [
        make_tcra(uid="tcra-1", responsavel_execucao="Equipe Norte"),
        make_tcra(uid="tcra-2", numero_tcra="", responsavel_execucao=""),
        make_tcra(uid="tcra-3", responsavel_execucao="Equipe Sul", prazo_final=date(2027, 1, 1), data_proximo_relatorio=date(2026, 4, 20)),
    ]

    workload = build_workload_snapshot(records, today=date(2026, 4, 3))
    digests = build_responsavel_digests(records, today=date(2026, 4, 3))

    assert workload.entries
    assert workload.suggestions
    assert any("Prioridades" in line for line in digests[0].message_lines)


def test_audit_trend_and_timeline_detect_risk_transition():
    before = make_tcra(uid="tcra-1", prazo_final=date(2026, 4, 20), data_proximo_relatorio=date(2026, 4, 20))
    after = make_tcra(uid="tcra-1", prazo_final=date(2026, 3, 20), data_proximo_relatorio=date(2026, 3, 20))
    audit_event = AuditEvent(
        event_id="event-1",
        timestamp="2026-04-03T12:00:00+00:00",
        workbook_path="session://banco-local",
        action="TCRA_EDIT",
        summary="Status ajustado",
        metadata={"uid": "tcra-1", "changed_fields": ["prazo_final", "data_proximo_relatorio"]},
        before={
            "uid": before.uid,
            "numero_processo": before.numero_processo,
            "numero_tcra": before.numero_tcra,
            "local": before.local,
            "status": before.status,
            "prazo_final": before.prazo_final.strftime("%d/%m/%Y"),
            "data_proximo_relatorio": before.data_proximo_relatorio.strftime("%d/%m/%Y"),
            "responsavel_execucao": before.responsavel_execucao,
        },
        after={
            "uid": after.uid,
            "numero_processo": after.numero_processo,
            "numero_tcra": after.numero_tcra,
            "local": after.local,
            "status": after.status,
            "prazo_final": after.prazo_final.strftime("%d/%m/%Y"),
            "data_proximo_relatorio": after.data_proximo_relatorio.strftime("%d/%m/%Y"),
            "responsavel_execucao": after.responsavel_execucao,
        },
    )

    trend = build_audit_trend_summary([audit_event], today=date(2026, 4, 11), weeks=2)
    timeline_text = build_record_change_timeline_text([audit_event], target_uid="tcra-1", today=date(2026, 4, 11))

    assert trend.buckets
    assert "alto risco" in trend.summary_text.lower()
    assert "prazo final" in timeline_text.lower()
