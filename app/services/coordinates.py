from typing import Any, List, Optional, Tuple

from app.models.compensacao import Compensacao
from app.services.records_service import safe_upper


def format_coordinate_pair(lat: Any, lon: Any) -> str:
    lat_value = str(lat or "").strip()
    lon_value = str(lon or "").strip()
    if lat_value and lon_value:
        return f"{lat_value}, {lon_value}"
    return ""


def parse_coordinate_pair(lat: Any, lon: Any) -> Optional[Tuple[float, float]]:
    lat_value = str(lat or "").strip()
    lon_value = str(lon or "").strip()
    if not lat_value or not lon_value:
        return None

    try:
        return float(lat_value), float(lon_value)
    except (TypeError, ValueError):
        return None


def get_record_coordinates(record: Compensacao, source: str = "main") -> Optional[Tuple[float, float]]:
    if source == "plantio":
        return parse_coordinate_pair(
            getattr(record, "latitude_plantio", ""),
            getattr(record, "longitude_plantio", ""),
        )
    return parse_coordinate_pair(
        getattr(record, "latitude", ""),
        getattr(record, "longitude", ""),
    )


def build_heatmap_point(record: Compensacao, heatmap_type: str) -> Optional[List[float]]:
    is_compensated = safe_upper(record.compensado) == "SIM"

    if heatmap_type == "Pendentes":
        if is_compensated:
            return None
        coords = get_record_coordinates(record, "main")
    elif heatmap_type == "Realizadas":
        if not is_compensated:
            return None
        coords = get_record_coordinates(record, "plantio")
    else:
        coords = get_record_coordinates(record, "main")

    if not coords:
        return None
    return [coords[0], coords[1]]
