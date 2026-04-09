from types import SimpleNamespace

from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem
from app.services.supabase_compensacoes_rpc_service import (
    SupabaseCompensacoesConflictError,
    SupabaseCompensacoesRpcError,
    SupabaseCompensacoesRpcService,
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


def _make_record() -> Compensacao:
    return Compensacao(
        excel_row=12,
        oficio_processo="123/2026",
        eletronico="Eletronico",
        caixa="Arquivado",
        av_tec="456/2026",
        compensacao="8",
        endereco="Rua A",
        microbacia="Gregorio",
        compensado="SIM",
        endereco_plantio="Praca A",
        latitude_plantio="-22.01",
        longitude_plantio="-47.90",
        latitude="-22.00",
        longitude="-47.89",
        uid="uid-123",
        updated_at="2026-04-09T12:00:00+00:00",
        plantios=[
            PlantioItem(
                sequence=1,
                endereco="Praca A",
                qtd_mudas="8",
                latitude="-22.01",
                longitude="-47.90",
            )
        ],
    )


def test_save_record_calls_rpc_with_serialized_payload():
    service = SupabaseCompensacoesRpcService()
    client = _FakeRpcClient(
        {
            service.SAVE_FUNCTION: {
                "workbook_path": "session://banco-local",
                "uid": "uid-123",
                "record_id": 10,
                "excel_row": 12,
                "updated_at": "2026-04-09T12:05:00+00:00",
                "record_count": 329,
                "plantio_count": 1,
                "audit_event_id": "evt-1",
            }
        }
    )

    result = service.save_record(
        client,
        workbook_path="session://banco-local",
        record=_make_record(),
        action="SAVE",
        summary="Atualizacao remota",
        expected_updated_at="2026-04-09T12:00:00+00:00",
        metadata={"origin": "pytest"},
    )

    function_name, params = client.calls[0]
    assert function_name == service.SAVE_FUNCTION
    assert params["p_workbook_path"] == "session://banco-local"
    assert params["p_record"]["uid"] == "uid-123"
    assert params["p_record"]["updated_at"] == "2026-04-09T12:00:00+00:00"
    assert params["p_record"]["plantios"][0]["endereco"] == "Praca A"
    assert params["p_expected_updated_at"] == "2026-04-09T12:00:00+00:00"
    assert params["p_after"]["uid"] == "uid-123"
    assert result.uid == "uid-123"
    assert result.updated_at == "2026-04-09T12:05:00+00:00"
    assert result.record_count == 329
    assert result.plantio_count == 1


def test_delete_record_calls_rpc_with_uid_and_audit_payload():
    service = SupabaseCompensacoesRpcService()
    client = _FakeRpcClient(
        {
            service.DELETE_FUNCTION: {
                "workbook_path": "session://banco-local",
                "uid": "uid-123",
                "updated_at": "2026-04-09T12:05:00+00:00",
                "record_count": 328,
                "plantio_count": 0,
                "audit_event_id": "evt-2",
            }
        }
    )

    result = service.delete_record(
        client,
        workbook_path="session://banco-local",
        uid="uid-123",
        action="DELETE",
        summary="Exclusao remota",
        expected_updated_at="2026-04-09T12:00:00+00:00",
        before={"uid": "uid-123"},
    )

    function_name, params = client.calls[0]
    assert function_name == service.DELETE_FUNCTION
    assert params["p_uid"] == "uid-123"
    assert params["p_expected_updated_at"] == "2026-04-09T12:00:00+00:00"
    assert params["p_before"] == {"uid": "uid-123"}
    assert result.operation == "delete"
    assert result.audit_event_id == "evt-2"
    assert result.updated_at == "2026-04-09T12:05:00+00:00"


def test_replace_records_calls_rpc_with_batch_payload_and_summary_sample():
    service = SupabaseCompensacoesRpcService()
    record = _make_record()
    client = _FakeRpcClient(
        {
            service.IMPORT_FUNCTION: {
                "workbook_path": "session://banco-local",
                "record_count": 1,
                "plantio_count": 1,
                "imported_count": 1,
                "audit_event_id": "evt-3",
            }
        }
    )

    result = service.replace_records(
        client,
        workbook_path="session://banco-local",
        records=[record],
        action="IMPORT",
        summary="Importacao remota",
        metadata={"source_kind": "excel_import"},
    )

    function_name, params = client.calls[0]
    assert function_name == service.IMPORT_FUNCTION
    assert len(params["p_records"]) == 1
    assert params["p_after"]["imported_count"] == 1
    assert params["p_after"]["sample_records"][0]["uid"] == "uid-123"
    assert result.imported_count == 1
    assert result.record_count == 1


def test_rpc_service_rejects_invalid_payload():
    service = SupabaseCompensacoesRpcService()

    class _BrokenClient:
        def rpc(self, _function_name, params=None):
            return _FakeRpcQuery(payload=["unexpected", params])

    try:
        service.save_record(
            _BrokenClient(),
            workbook_path="session://banco-local",
            record=_make_record(),
            action="SAVE",
            summary="Atualizacao remota",
        )
    except SupabaseCompensacoesRpcError as exc:
        assert "payload invalido" in str(exc)
    else:
        raise AssertionError("Era esperado erro para payload RPC invalido.")


def test_rpc_service_maps_conflict_errors_to_specific_exception():
    service = SupabaseCompensacoesRpcService()

    class _ConflictClient:
        def rpc(self, _function_name, params=None):
            class _BrokenQuery:
                def execute(self_inner):
                    raise RuntimeError(
                        "compensacao_record_conflict: o registro remoto foi alterado por outra sessao."
                    )

            return _BrokenQuery()

    try:
        service.save_record(
            _ConflictClient(),
            workbook_path="session://banco-local",
            record=_make_record(),
            action="SAVE",
            summary="Atualizacao remota",
            expected_updated_at="2026-04-09T12:00:00+00:00",
        )
    except SupabaseCompensacoesConflictError as exc:
        assert "outra sessao" in str(exc).lower()
    else:
        raise AssertionError("Era esperado conflito especifico para versao remota divergente.")
