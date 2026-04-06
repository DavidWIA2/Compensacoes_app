from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.models.tcra_evento import TcraEvento


@dataclass
class Tcra:
    uid: str = ""
    numero_processo: str = ""
    numero_tcra: str = ""
    local: str = ""
    endereco: str = ""
    bairro: str = ""
    orgao_acompanhamento: str = ""
    status: str = ""
    data_assinatura: date | None = None
    prazo_final: date | None = None
    periodicidade_relatorio_meses: int | None = None
    data_ultimo_relatorio: date | None = None
    data_proximo_relatorio: date | None = None
    area_m2: float | None = None
    numero_mudas_previsto: int | None = None
    servicos_exigidos: str = ""
    responsavel_execucao: str = ""
    observacoes: str = ""
    mpsp_relacionado: str = ""
    inquerito_civil: str = ""
    eventos: list[TcraEvento] = field(default_factory=list)
