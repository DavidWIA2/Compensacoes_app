from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class TcraEvento:
    sequence: int = 1
    data_evento: date | None = None
    tipo_evento: str = ""
    descricao: str = ""
    prazo_resultante: date | None = None
    status_resultante: str = ""
