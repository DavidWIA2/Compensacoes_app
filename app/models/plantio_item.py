from dataclasses import dataclass
from typing import Optional


@dataclass
class PlantioItem:
    sequence: int = 1
    endereco: str = ""
    qtd_mudas: str = ""
    latitude: Optional[str] = ""
    longitude: Optional[str] = ""
