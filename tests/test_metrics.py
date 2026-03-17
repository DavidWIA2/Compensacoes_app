from app.models.compensacao import Compensacao
from app.services.records_service import to_float, row_is_compensado, compute_metrics


class MetricsHarness:
    _to_float = staticmethod(to_float)
    _row_is_compensado = staticmethod(row_is_compensado)
    _compute_metrics = staticmethod(compute_metrics)


def make_record(**overrides) -> Compensacao:
    base = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "Gregorio",
        "compensado": "",
        "latitude": "",
        "longitude": "",
    }
    base.update(overrides)
    return Compensacao(**base)


def test_compute_metrics_sums_pending_and_compensated():
    harness = MetricsHarness()
    records = [
        make_record(compensacao="10", compensado=""),
        make_record(excel_row=3, compensacao="5.5", compensado="SIM", microbacia="Monjolinho"),
        make_record(excel_row=4, compensacao="2,5", compensado="", microbacia="Gregorio", eletronico="NAO"),
    ]

    metrics = harness._compute_metrics(records)

    assert metrics["total_geral"] == 18.0
    assert metrics["total_pendente"] == 12.5
    assert metrics["total_compensado"] == 5.5
    assert metrics["count_total"] == 3
    assert metrics["count_pend"] == 2
    assert metrics["count_comp"] == 1
    assert metrics["pend_micro_sorted"][0] == ("Gregorio", 12.5)


def test_compute_metrics_groups_empty_values_with_fallback_labels():
    harness = MetricsHarness()
    records = [
        make_record(microbacia="", eletronico="", compensacao="4"),
    ]

    metrics = harness._compute_metrics(records)

    assert metrics["pend_micro_sorted"] == [("(Sem microbacia)", 4.0)]
    assert metrics["pend_ele_sorted"] == [("(Sem eletr\u00f4nico)", 4.0)]
