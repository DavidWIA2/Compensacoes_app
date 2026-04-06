from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem
from app.models.tcra import Tcra
from app.models.tcra_evento import TcraEvento
from app.services.sqlite_mirror_service import DEFAULT_SINGLETON_SESSION_PATH, SqliteMirrorService
from app.services.tcra_sqlite_service import TcraSqliteService
from app.utils.app_paths import ensure_dir, resolve_data_path


def resolve_demo_db_path() -> Path:
    return resolve_data_path("state", "demo", "compensacoes-demo.db")


def build_demo_records() -> list[Compensacao]:
    return [
        Compensacao(
            excel_row=2,
            oficio_processo="145/2026 - DEMO",
            eletronico="Oficio",
            caixa="12",
            av_tec="101/2026",
            compensacao="8",
            endereco="Rua das Sibipirunas, 120",
            microbacia="Gregorio",
            compensado="",
            endereco_plantio="Praca das Acacias",
            latitude_plantio="-22.0184",
            longitude_plantio="-47.8921",
            latitude="-22.0219",
            longitude="-47.9016",
            uid="demo-comp-001",
            plantios=[
                PlantioItem(
                    sequence=1,
                    endereco="Praca das Acacias",
                    qtd_mudas="8",
                    latitude="-22.0184",
                    longitude="-47.8921",
                ),
            ],
        ),
        Compensacao(
            excel_row=3,
            oficio_processo="212/2026 - DEMO",
            eletronico="Eletronico",
            caixa="",
            av_tec="118/2026",
            compensacao="14",
            endereco="Avenida Brasil, 540",
            microbacia="Medeiros",
            compensado="SIM",
            endereco_plantio="Rotatoria do Jardim Modelo",
            latitude_plantio="-22.0117",
            longitude_plantio="-47.8840",
            latitude="-22.0125",
            longitude="-47.8871",
            uid="demo-comp-002",
            plantios=[
                PlantioItem(
                    sequence=1,
                    endereco="Rotatoria do Jardim Modelo",
                    qtd_mudas="14",
                    latitude="-22.0117",
                    longitude="-47.8840",
                ),
            ],
        ),
        Compensacao(
            excel_row=4,
            oficio_processo="301/2026 - DEMO",
            eletronico="Fisico",
            caixa="44",
            av_tec="132/2026",
            compensacao="5",
            endereco="Rua do Ipê, 33",
            microbacia="Monjolinho",
            compensado="",
            endereco_plantio="Corredor verde do bairro Demo Sul",
            latitude_plantio="",
            longitude_plantio="",
            latitude="-22.0340",
            longitude="-47.9042",
            uid="demo-comp-003",
            plantios=[],
        ),
        Compensacao(
            excel_row=5,
            oficio_processo="327/2026 - DEMO",
            eletronico="Nulo",
            caixa="",
            av_tec="141/2026",
            compensacao="11",
            endereco="Rua das Paineiras, 890",
            microbacia="Santa Maria do Leme",
            compensado="",
            endereco_plantio="Parque linear das Hortensias",
            latitude_plantio="-22.0064",
            longitude_plantio="-47.9110",
            latitude="-22.0058",
            longitude="-47.9101",
            uid="demo-comp-004",
            plantios=[
                PlantioItem(
                    sequence=1,
                    endereco="Parque linear das Hortensias",
                    qtd_mudas="6",
                    latitude="-22.0064",
                    longitude="-47.9110",
                ),
                PlantioItem(
                    sequence=2,
                    endereco="Praca das Jabuticabeiras",
                    qtd_mudas="5",
                    latitude="-22.0080",
                    longitude="-47.9075",
                ),
            ],
        ),
        Compensacao(
            excel_row=6,
            oficio_processo="402/2026 - DEMO",
            eletronico="Eletronico",
            caixa="",
            av_tec="166/2026",
            compensacao="19",
            endereco="Avenida das Araucarias, 1700",
            microbacia="Agua Quente",
            compensado="SIM",
            endereco_plantio="Bosque do terminal norte",
            latitude_plantio="-22.0262",
            longitude_plantio="-47.8769",
            latitude="-22.0249",
            longitude="-47.8785",
            uid="demo-comp-005",
            plantios=[
                PlantioItem(
                    sequence=1,
                    endereco="Bosque do terminal norte",
                    qtd_mudas="19",
                    latitude="-22.0262",
                    longitude="-47.8769",
                ),
            ],
        ),
        Compensacao(
            excel_row=7,
            oficio_processo="418/2026 - DEMO",
            eletronico="Oficio",
            caixa="77",
            av_tec="171/2026",
            compensacao="9",
            endereco="Rua do Cafezal, 58",
            microbacia="Tijuco Preto",
            compensado="",
            endereco_plantio="Canteiro central da Avenida Modelo",
            latitude_plantio="",
            longitude_plantio="",
            latitude="-22.0151",
            longitude="-47.9183",
            uid="demo-comp-006",
            plantios=[],
        ),
    ]


def build_demo_tcras() -> list[Tcra]:
    today = date.today()
    return [
        Tcra(
            uid="demo-tcra-001",
            numero_processo="IC 100/2026",
            numero_tcra="TCRA-01/2026",
            local="Parque das Acacias",
            endereco="Rua das Sibipirunas, 120",
            bairro="Centro",
            orgao_acompanhamento="SMMA",
            status="Em acompanhamento",
            data_assinatura=today - timedelta(days=90),
            prazo_final=today + timedelta(days=240),
            periodicidade_relatorio_meses=6,
            data_ultimo_relatorio=today - timedelta(days=30),
            data_proximo_relatorio=today + timedelta(days=150),
            area_m2=320.0,
            numero_mudas_previsto=42,
            servicos_exigidos="Plantio compensatorio, irrigacao inicial e tutoramento.",
            responsavel_execucao="Equipe Demo Norte",
            observacoes="Exemplo ficticio para navegacao no modulo TCRA.",
            mpsp_relacionado="SIM",
            inquerito_civil="IC-2026-10",
            eventos=[
                TcraEvento(
                    sequence=1,
                    data_evento=today - timedelta(days=88),
                    tipo_evento="Assinatura",
                    descricao="TCRA ficticio assinado para fins de demonstracao.",
                    prazo_resultante=today + timedelta(days=240),
                    status_resultante="Em acompanhamento",
                ),
                TcraEvento(
                    sequence=2,
                    data_evento=today - timedelta(days=30),
                    tipo_evento="Relatorio",
                    descricao="Relatorio semestral ficticio recebido.",
                    prazo_resultante=today + timedelta(days=150),
                    status_resultante="Em acompanhamento",
                ),
            ],
        ),
        Tcra(
            uid="demo-tcra-002",
            numero_processo="IC 205/2025",
            numero_tcra="TCRA-14/2025",
            local="Bosque do terminal norte",
            endereco="Avenida das Araucarias, 1700",
            bairro="Vila Norte",
            orgao_acompanhamento="SAAE",
            status="Relatorio pendente",
            data_assinatura=today - timedelta(days=380),
            prazo_final=today + timedelta(days=25),
            periodicidade_relatorio_meses=3,
            data_ultimo_relatorio=today - timedelta(days=120),
            data_proximo_relatorio=today - timedelta(days=15),
            area_m2=510.0,
            numero_mudas_previsto=60,
            servicos_exigidos="Plantio, manutencao trimestral e substituicao de perdas.",
            responsavel_execucao="Consorcio Verde Demo",
            observacoes="TCRA ficticio com pendencia para demonstrar alertas.",
            mpsp_relacionado="",
            inquerito_civil="",
            eventos=[
                TcraEvento(
                    sequence=1,
                    data_evento=today - timedelta(days=360),
                    tipo_evento="Assinatura",
                    descricao="Inicio do acompanhamento ficticio.",
                    prazo_resultante=today + timedelta(days=25),
                    status_resultante="Em acompanhamento",
                ),
                TcraEvento(
                    sequence=2,
                    data_evento=today - timedelta(days=120),
                    tipo_evento="Relatorio",
                    descricao="Ultimo relatorio recebido dentro do prazo.",
                    prazo_resultante=today - timedelta(days=15),
                    status_resultante="Relatorio pendente",
                ),
            ],
        ),
        Tcra(
            uid="demo-tcra-003",
            numero_processo="IC 311/2024",
            numero_tcra="TCRA-22/2024",
            local="Corredor verde Demo Sul",
            endereco="Rua do Ipe, 33",
            bairro="Jardim Modelo",
            orgao_acompanhamento="SMMA",
            status="Cumprido",
            data_assinatura=today - timedelta(days=540),
            prazo_final=today - timedelta(days=40),
            periodicidade_relatorio_meses=6,
            data_ultimo_relatorio=today - timedelta(days=60),
            data_proximo_relatorio=None,
            area_m2=180.0,
            numero_mudas_previsto=24,
            servicos_exigidos="Plantio e manutencao inicial.",
            responsavel_execucao="Equipe Demo Sul",
            observacoes="Exemplo encerrado para demonstrar status cumprido.",
            mpsp_relacionado="",
            inquerito_civil="IC-2024-88",
            eventos=[
                TcraEvento(
                    sequence=1,
                    data_evento=today - timedelta(days=520),
                    tipo_evento="Assinatura",
                    descricao="TCRA ficticio firmado.",
                    prazo_resultante=today - timedelta(days=40),
                    status_resultante="Em acompanhamento",
                ),
                TcraEvento(
                    sequence=2,
                    data_evento=today - timedelta(days=60),
                    tipo_evento="Encerramento",
                    descricao="Encerramento ficticio homologado.",
                    prazo_resultante=None,
                    status_resultante="Cumprido",
                ),
            ],
        ),
    ]


def reset_demo_database(db_path: str | Path | None = None) -> Path:
    target_path = Path(db_path) if db_path else resolve_demo_db_path()
    ensure_dir(target_path.parent)
    if target_path.exists():
        target_path.unlink()

    sqlite_service = SqliteMirrorService(db_path=target_path)
    sqlite_service.ensure_singleton_session()
    sqlite_service.sync_workbook_snapshot(DEFAULT_SINGLETON_SESSION_PATH, build_demo_records())

    tcra_service = TcraSqliteService(db_path=target_path)
    tcra_service.replace_all(build_demo_tcras())
    return target_path
