from typing import Callable, Dict, Iterable, Optional, Tuple

from app.models.compensacao import Compensacao


def find_record_by_excel_row(records: Iterable[Compensacao], excel_row: int) -> Optional[Compensacao]:
    return next((record for record in records if record.excel_row == excel_row), None)


def build_cached_microbacia_finder(
    find_microbacia: Optional[Callable[[float, float], str]],
    *,
    precision: int = 6,
) -> Optional[Callable[[float, float], str]]:
    if not find_microbacia:
        return None

    cache: Dict[Tuple[float, float], str] = {}

    def cached(lat: float, lon: float) -> str:
        key = (round(float(lat), precision), round(float(lon), precision))
        if key not in cache:
            cache[key] = find_microbacia(lat, lon)
        return cache[key]

    return cached


def apply_geocode_to_record(
    record: Compensacao,
    lat: float,
    lon: float,
    find_microbacia: Optional[Callable[[float, float], str]] = None,
) -> str:
    record.latitude = str(lat)
    record.longitude = str(lon)

    if not find_microbacia:
        return ""

    try:
        micro = find_microbacia(lat, lon)
    except Exception:
        return ""

    if micro and str(micro).strip():
        micro_nome = str(micro).strip()
        record.microbacia = micro_nome
        return micro_nome

    return ""
