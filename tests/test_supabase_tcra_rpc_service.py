from datetime import date
from types import SimpleNamespace

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.supabase_tcra_rpc_service import (
    SupabaseTcraRpcError,
    SupabaseTcraRpcService,
    serialize_tcra,
)


class _FakeRpcQuery:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return SimpleNamespace(data=self.payload)


class _FakeRpcClient:
    def __init__(self, payloads):
        self.payloads = dict(payloads)
        self.calls = []

    def rpc(self, function_name, params=None):
        self.calls.append((function_name, dict(params or {})))
        return _FakeRpcQuery(self.payloads[function_name])


def _make_tcra() -> Tcra:
    return Tcra(
        uid="tcra-001",
        numero_processo="26207/2019",
        numero_tcra="TCRA-001",
        local="Parque A",
        endereco="Rua A",
        bairro="Centro",
        orgao_acompanhamento="CETESB",
        status="Em acompanhamento",
        data_assinatura=date(2024, 1, 10),
        prazo_final=date(2026, 4, 1),
        periodicidade_relatorio_meses=12,
        data_ultimo_relatorio=date(2025, 1, 1),
        data_proximo_relatorio=date(2026, 1, 1),
        area_m2=1200.5,
        numero_mudas_previsto=200,
        servicos_exigidos="Plantio",
        responsavel_execucao="Equipe",
        observacoes="Observacao",
        mpsp_relacionado="Sim",
        inquerito_civil="IC 123",
        eventos=[
            TcraEvento(
                sequence=1,
                data_evento=date(2025, 1, 1),
                tipo_evento="Relatorio",
                descricao="Relatorio recebido",
                prazo_resultante=date(2026, 1, 1),
                status_resultante="Em acompanhamento",
            )
        ],
    )


def test_serialize_tcra_includes_dates_and_events():
    payload = serialize_tcra(_make_tcra())

    assert payload["uid"] == "tcra-001"
    assert payload["data_assinatura"] == "2024-01-10"
    assert payload["eventos"][0]["prazo_resultante"] == "2026-01-01"


def test_save_record_calls_tcra_rpc_with_serialized_payload():
    service = SupabaseTcraRpcService()
    client = _FakeRpcClient(
        {
            service.SAVE_FUNCTION: {
                "uid": "tcra-001",
                "tcra_count": 18,
                "tcra_event_count": 3,
                "audit_event_id": "evt-tcra-1",
            }
        }
    )

    result = service.save_record(
        client,
        record=_make_tcra(),
        action="TCRA_SAVE",
        summary="TCRA salvo",
        metadata={"origin": "pytest"},
    )

    function_name, params = client.calls[0]
    assert function_name == service.SAVE_FUNCTION
    assert params["p_record"]["uid"] == "tcra-001"
    assert params["p_record"]["eventos"][0]["tipo_evento"] == "Relatorio"
    assert params["p_metadata"] == {"origin": "pytest"}
    assert result.uid == "tcra-001"
    assert result.tcra_count == 18


def test_bulk_and_replace_records_call_batch_rpcs():
    service = SupabaseTcraRpcService()
    record = _make_tcra()
    client = _FakeRpcClient(
        {
            service.BULK_SAVE_FUNCTION: {"tcra_count": 1, "tcra_event_count": 1, "imported_count": 1},
            service.IMPORT_FUNCTION: {"tcra_count": 1, "tcra_event_count": 1, "imported_count": 1},
        }
    )

    bulk_result = service.save_records(client, records=[record], action="TCRA_BULK", summary="Lote")
    import_result = service.replace_records(client, records=[record], action="TCRA_IMPORT", summary="Import")

    assert client.calls[0][0] == service.BULK_SAVE_FUNCTION
    assert client.calls[1][0] == service.IMPORT_FUNCTION
    assert bulk_result.imported_count == 1
    assert import_result.imported_count == 1


def test_delete_record_calls_rpc_with_uid_and_before_payload():
    service = SupabaseTcraRpcService()
    client = _FakeRpcClient(
        {
            service.DELETE_FUNCTION: {
                "uid": "tcra-001",
                "tcra_count": 17,
                "tcra_event_count": 2,
                "audit_event_id": "evt-tcra-2",
            }
        }
    )

    result = service.delete_record(
        client,
        uid="tcra-001",
        action="TCRA_DELETE",
        summary="Exclusao",
        before={"uid": "tcra-001"},
    )

    function_name, params = client.calls[0]
    assert function_name == service.DELETE_FUNCTION
    assert params["p_uid"] == "tcra-001"
    assert params["p_before"] == {"uid": "tcra-001"}
    assert result.uid == "tcra-001"
    assert result.tcra_count == 17


def test_rpc_service_rejects_invalid_payload():
    service = SupabaseTcraRpcService()

    class _BrokenClient:
        def rpc(self, _function_name, params=None):
            return _FakeRpcQuery(payload=["unexpected", params])

    try:
        service.save_record(_BrokenClient(), record=_make_tcra(), action="TCRA_SAVE", summary="Salvar")
    except SupabaseTcraRpcError as exc:
        assert "payload invalido" in str(exc)
    else:
        raise AssertionError("Era esperado erro para payload RPC invalido.")
