from dataclasses import dataclass
from typing import Optional

@dataclass
class Compensacao:
    excel_row: int
    oficio_processo: str
    eletronico: str
    caixa: str
    av_tec: str
    compensacao: Optional[str]
    endereco: str
    microbacia: str
    compensado: str
    endereco_plantio: str = ""
    latitude_plantio: Optional[str] = ""
    longitude_plantio: Optional[str] = ""
    # Campos para o mapa de calor preciso (solicitante)
    latitude: Optional[str] = ""
    longitude: Optional[str] = ""
    uid: str = ""