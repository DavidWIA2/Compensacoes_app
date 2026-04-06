from datetime import date
import sqlite3

from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.sqlite_mirror_service import SqliteMirrorService
from app.services.tcra_sqlite_service import TcraSqliteService


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


def test_tcra_sqlite_service_initializes_own_tables_without_breaking_compensacoes(tmp_path):
    db_path = tmp_path / "local.db"

    SqliteMirrorService(db_path=db_path)
    TcraSqliteService(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }

    assert {"records", "plantios", "audit_events", "tcras", "tcra_eventos"}.issubset(tables)


def test_upsert_tcra_roundtrips_with_nested_eventos(tmp_path):
    service = TcraSqliteService(db_path=tmp_path / "local.db")
    tcra = make_tcra()

    uid = service.upsert_tcra(tcra)
    loaded = service.find_tcra_by_uid(uid)

    assert loaded is not None
    assert loaded.uid == tcra.uid
    assert loaded.numero_processo == "26207/2019"
    assert loaded.area_m2 == 2920.0
    assert loaded.numero_mudas_previsto == 486
    assert loaded.data_proximo_relatorio == date(2025, 3, 10)
    assert len(loaded.eventos) == 1
    assert loaded.eventos[0].tipo_evento == "Relatorio"
    assert loaded.eventos[0].prazo_resultante == date(2025, 3, 10)


def test_tcra_sqlite_service_get_tcra_returns_record_by_uid(tmp_path):
    service = TcraSqliteService(db_path=tmp_path / "local.db")
    tcra = make_tcra(uid="tcra-42", numero_tcra="TCRA-2042-001")

    service.upsert_tcra(tcra)

    loaded = service.get_tcra("tcra-42")

    assert loaded is not None
    assert loaded.uid == "tcra-42"
    assert loaded.numero_tcra == "TCRA-2042-001"
    assert service.get_tcra("missing") is None


def test_tcra_sqlite_service_get_tcras_by_uids_preserves_requested_order(tmp_path):
    service = TcraSqliteService(db_path=tmp_path / "local.db")
    first = make_tcra(uid="tcra-1", numero_tcra="TCRA-2026-001", local="Area Norte")
    second = make_tcra(uid="tcra-2", numero_tcra="TCRA-2026-002", local="Area Sul")
    third = make_tcra(uid="tcra-3", numero_tcra="TCRA-2026-003", local="Area Oeste")

    service.replace_all([first, second, third])

    loaded = service.get_tcras_by_uids(["tcra-3", "tcra-1", "missing", "tcra-2"])

    assert [record.uid for record in loaded] == ["tcra-3", "tcra-1", "tcra-2"]
    assert [record.local for record in loaded] == ["Area Oeste", "Area Norte", "Area Sul"]


def test_replace_all_rewrites_dataset_and_cascades_eventos(tmp_path):
    service = TcraSqliteService(db_path=tmp_path / "local.db")
    first = make_tcra(uid="tcra-1", data_proximo_relatorio=None)
    second = make_tcra(
        uid="tcra-2",
        numero_processo="193/2011",
        numero_tcra="TCRA-2011-002",
        local="CEMOSAR",
        endereco="Margens da Estrada Domingues Inocentini",
        bairro="",
        status="Cumprido",
        data_assinatura=None,
        prazo_final=date(2026, 4, 25),
        periodicidade_relatorio_meses=None,
        data_ultimo_relatorio=date(2020, 7, 23),
        data_proximo_relatorio=None,
        area_m2=44710.0,
        numero_mudas_previsto=7451,
        servicos_exigidos="Tratos culturais e replantio",
        observacoes="",
        eventos=[
            TcraEvento(
                sequence=1,
                data_evento=date(2025, 1, 23),
                tipo_evento="Despacho",
                descricao="Inquerito civil arquivado",
                prazo_resultante=None,
                status_resultante="Cumprido",
            )
        ],
    )

    service.replace_all([first, second])
    loaded = service.list_tcras()

    assert [item.uid for item in loaded] == ["tcra-2", "tcra-1"]
    assert loaded[0].status == "Cumprido"
    assert loaded[0].eventos[0].descricao == "Inquerito civil arquivado"

    service.replace_all([first])

    with sqlite3.connect(service.db_path) as conn:
        tcra_rows = conn.execute("SELECT uid FROM tcras ORDER BY uid ASC").fetchall()
        evento_rows = conn.execute("SELECT tcra_uid FROM tcra_eventos ORDER BY tcra_uid ASC").fetchall()

    assert tcra_rows == [("tcra-1",)]
    assert evento_rows == [("tcra-1",)]


def test_tcra_sqlite_service_exposes_query_helpers_for_future_ui(tmp_path):
    service = TcraSqliteService(db_path=tmp_path / "local.db")
    today = date(2026, 4, 3)
    first = make_tcra(uid="tcra-1", data_proximo_relatorio=None)
    second = make_tcra(
        uid="tcra-2",
        numero_processo="444/2022",
        numero_tcra="",
        local="Varjao",
        bairro="Varjao",
        orgao_acompanhamento="MPSP",
        status="Em acompanhamento",
        prazo_final=date(2027, 1, 1),
        data_proximo_relatorio=date(2026, 1, 10),
        mpsp_relacionado="Sim",
        inquerito_civil="Procedimento em andamento",
    )
    third = make_tcra(
        uid="tcra-3",
        numero_processo="193/2011",
        numero_tcra="TCRA-2011-002",
        local="CEMOSAR",
        bairro="Centro",
        status="Cumprido",
        prazo_final=date(2024, 1, 1),
        data_proximo_relatorio=date(2024, 1, 1),
    )

    service.replace_all([first, second, third])

    filtered = service.query_tcras(
        text="varjao",
        status="Relatorio pendente",
        selected_orgaos=["MPSP"],
        selected_bairros=["Varjao"],
        selected_year="2022",
        only_mpsp=True,
        only_relatorio_pendente=True,
        today=today,
    )
    facets = service.query_filter_facets(today=today)
    metrics = service.query_metrics(status="Prazo vencido", today=today)
    overview = service.build_record_overview(today=today)

    assert [item.uid for item in filtered] == ["tcra-2"]
    assert "Relatorio pendente" in facets.statuses
    assert facets.anos_processo == ("2022", "2019", "2011")
    assert metrics["count_total"] == 1
    assert metrics["count_prazo_vencido"] == 1
    assert overview.total_count == 3
    assert overview.relatorio_pendente_count == 1
    assert overview.upcoming_reports[0].uid == "tcra-2"


def test_find_duplicate_tcra_checks_numero_tcra_and_processo_local(tmp_path):
    service = TcraSqliteService(db_path=tmp_path / "local.db")
    first = make_tcra(uid="tcra-1", numero_tcra="TCRA-2024-010", numero_processo="901/2024", local="Area Norte")
    second = make_tcra(uid="tcra-2", numero_tcra="", numero_processo="901/2024", local="Area Norte")

    service.replace_all([first, second])

    duplicate_by_numero = service.find_duplicate_tcra(numero_tcra="TCRA-2024-010")
    duplicate_by_context = service.find_duplicate_tcra(
        numero_processo="901/2024",
        local="Area Norte",
        exclude_uid="tcra-2",
    )
    ignored_same_uid = service.find_duplicate_tcra(numero_tcra="TCRA-2024-010", exclude_uid="tcra-1")

    assert duplicate_by_numero is not None
    assert duplicate_by_numero.uid == "tcra-1"
    assert duplicate_by_context is not None
    assert duplicate_by_context.uid == "tcra-1"
    assert ignored_same_uid is None


def test_tcra_sqlite_service_normalizes_status_orgao_and_event_status(tmp_path):
    service = TcraSqliteService(db_path=tmp_path / "local.db")
    tcra = make_tcra(
        uid="tcra-9",
        orgao_acompanhamento="ministerio publico",
        status="relatorio atrasado",
        eventos=[
            TcraEvento(
                sequence=1,
                data_evento=date(2026, 4, 1),
                tipo_evento="Despacho",
                descricao="Despacho mais recente",
                prazo_resultante=date(2026, 4, 15),
                status_resultante="cumprido",
            )
        ],
    )

    saved_uid = service.upsert_tcra(tcra)
    loaded = service.find_tcra_by_uid(saved_uid)

    assert loaded is not None
    assert loaded.orgao_acompanhamento == "MPSP"
    assert loaded.status == "Relatorio pendente"
    assert loaded.eventos[0].status_resultante == "Cumprido"
