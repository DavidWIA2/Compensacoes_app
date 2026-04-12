from types import SimpleNamespace

from app.models.compensacao import Compensacao
from app.services.sqlite_mirror_service import DEFAULT_SINGLETON_SESSION_PATH, SqliteMirrorService
from app.services.supabase_workspace_sync_service import (
    PRODUCTION_CACHE_SESSION_PATH,
    SupabaseWorkspaceSyncService,
)
from app.services.tcra_sqlite_service import TcraSqliteService


class _FakeTableQuery:
    def __init__(self, rows):
        self.rows = list(rows)
        self._start = None
        self._end = None
        self._limit = None

    def select(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, value):
        self._limit = int(value)
        return self

    def range(self, start, end):
        self._start = int(start)
        self._end = int(end)
        return self

    def execute(self):
        if self._limit is not None:
            data = self.rows[: self._limit]
        elif self._start is not None and self._end is not None:
            data = self.rows[self._start : self._end + 1]
        else:
            data = self.rows
        return SimpleNamespace(data=data)


class _FakeSupabaseClient:
    def __init__(self, table_rows):
        self.table_rows = dict(table_rows)

    def table(self, table_name):
        return _FakeTableQuery(self.table_rows.get(table_name, ()))


def test_sync_authenticated_client_resets_local_cache_and_loads_remote_snapshot(tmp_path):
    target_db = tmp_path / "prod-cache.db"
    service = SupabaseWorkspaceSyncService(production_db_path=target_db)
    client = _FakeSupabaseClient(
        {
            "workbooks": [
                {
                    "id": 1,
                    "workbook_path": "session://banco-local",
                    "workbook_name": "Base oficial",
                }
            ],
            "records": [
                {
                    "id": 11,
                    "uid": "remote-001",
                    "excel_row": 2,
                    "oficio_processo": "120/2026",
                    "eletronico": "Oficio",
                    "caixa": "42",
                    "av_tec": "300/2026",
                    "compensacao": "8",
                    "endereco": "ExtensÃ£o da Rua A",
                    "microbacia": "GregÃ³rio",
                    "compensado": "",
                    "endereco_plantio": "PraÃ§a A",
                    "latitude_plantio": "-22.01",
                    "longitude_plantio": "-47.90",
                    "latitude": "-22.00",
                    "longitude": "-47.89",
                    "updated_at": "2026-04-09T12:00:00+00:00",
                },
                {
                    "id": 12,
                    "uid": "remote-002",
                    "excel_row": 3,
                    "oficio_processo": "121/2026",
                    "eletronico": "Eletronico",
                    "caixa": "",
                    "av_tec": "301/2026",
                    "compensacao": "15",
                    "endereco": "Rua B",
                    "microbacia": "Medeiros",
                    "compensado": "SIM",
                    "endereco_plantio": "Bosque B",
                    "latitude_plantio": "",
                    "longitude_plantio": "",
                    "latitude": "",
                    "longitude": "",
                    "updated_at": "2026-04-09T12:05:00+00:00",
                },
            ],
            "plantios": [
                {
                    "id": 21,
                    "record_id": 11,
                    "sequence": 1,
                    "endereco": "PraÃ§a A",
                    "qtd_mudas": "8",
                    "latitude": "-22.01",
                    "longitude": "-47.90",
                }
            ],
            "audit_events": [
                {
                    "id": 31,
                    "event_id": "evt-001",
                    "timestamp": "2026-04-06T12:00:00+00:00",
                    "action": "IMPORT",
                    "summary": "Carga oficial",
                    "backup_path": "",
                    "metadata_json": {"origin": "supabase"},
                    "before_json": None,
                    "after_json": {"records": 2},
                }
            ],
            "tcras": [
                {
                    "uid": "tcra-001",
                    "numero_processo": "IC 100/2026",
                    "numero_tcra": "TCRA-01/2026",
                    "local": "Parque EcolÃ³gico",
                    "endereco": "Rua A",
                    "bairro": "Centro",
                    "orgao_acompanhamento": "SMMA",
                    "status": "Em acompanhamento",
                    "data_assinatura": "2026-01-10",
                    "prazo_final": "2026-12-10",
                    "periodicidade_relatorio_meses": 6,
                    "data_ultimo_relatorio": "2026-03-01",
                    "data_proximo_relatorio": "2026-09-01",
                    "area_m2": 320.0,
                    "numero_mudas_previsto": 42,
                    "servicos_exigidos": "Plantio",
                    "responsavel_execucao": "Equipe",
                    "observacoes": "RelatÃ³rio pendente de protocolo",
                    "mpsp_relacionado": "SIM",
                    "inquerito_civil": "IC-2026-10",
                }
            ],
            "tcra_eventos": [
                {
                    "id": 41,
                    "tcra_uid": "tcra-001",
                    "sequence": 1,
                    "data_evento": "2026-03-01",
                    "tipo_evento": "RelatÃ³rio",
                    "descricao": "RelatÃ³rio recebido",
                    "prazo_resultante": "2026-09-01",
                    "status_resultante": "Em acompanhamento",
                    "protocolo": "SEI-123",
                    "documento_ref": "docs/relatorio.pdf",
                }
            ],
        }
    )

    result = service.sync_authenticated_client(client)

    sqlite_service = SqliteMirrorService(db_path=target_db)
    tcra_service = TcraSqliteService(db_path=target_db)
    records = sqlite_service.list_records_for_workbook(DEFAULT_SINGLETON_SESSION_PATH)
    audit_events = sqlite_service.list_audit_event_payloads_for_session(DEFAULT_SINGLETON_SESSION_PATH)
    tcras = tcra_service.list_tcras()

    assert result.local_db_path == str(target_db)
    assert result.session_path == PRODUCTION_CACHE_SESSION_PATH
    assert result.record_count == 2
    assert result.plantio_count == 2
    assert result.audit_event_count == 1
    assert result.tcra_count == 1
    assert len(records) == 2
    assert isinstance(records[0], Compensacao)
    assert records[0].endereco == "Extensão da Rua A"
    assert records[0].microbacia == "Gregório"
    assert records[0].updated_at == "2026-04-09T12:00:00+00:00"
    assert records[0].plantios[0].endereco == "Praça A"
    assert len(records[0].plantios) == 1
    assert len(records[1].plantios) == 1
    assert len(audit_events) == 1
    assert audit_events[0]["action"] == "IMPORT"
    assert len(tcras) == 1
    assert tcras[0].local == "Parque Ecológico"
    assert tcras[0].observacoes == "Relatório pendente de protocolo"
    assert tcras[0].eventos[0].tipo_evento == "Relatório"
    assert tcras[0].eventos[0].protocolo == "SEI-123"
    assert tcras[0].eventos[0].documento_ref == "docs/relatorio.pdf"
    assert len(tcras[0].eventos) == 1
