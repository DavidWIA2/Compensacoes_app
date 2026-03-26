from typing import Any, List, Optional, Tuple

from app.models.compensacao import Compensacao
from app.services.plantio_service import record_plantio_items
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
        for plantio in record_plantio_items(record):
            coords = parse_coordinate_pair(plantio.latitude, plantio.longitude)
            if coords:
                return coords
        return parse_coordinate_pair(
            getattr(record, "latitude_plantio", ""),
            getattr(record, "longitude_plantio", ""),
        )
    return parse_coordinate_pair(
        getattr(record, "latitude", ""),
        getattr(record, "longitude", ""),
    )


def get_record_plantio_coordinates(record: Compensacao) -> List[List[float]]:
    points: List[List[float]] = []
    for plantio in record_plantio_items(record):
        coords = parse_coordinate_pair(plantio.latitude, plantio.longitude)
        if coords:
            points.append([coords[0], coords[1]])

    if points:
        return points

    legacy_coords = parse_coordinate_pair(
        getattr(record, "latitude_plantio", ""),
        getattr(record, "longitude_plantio", ""),
    )
    if legacy_coords:
        return [[legacy_coords[0], legacy_coords[1]]]
    return []


def build_heatmap_points(record: Compensacao, heatmap_type: str) -> List[List[float]]:
    is_compensated = safe_upper(record.compensado) == "SIM"

    if heatmap_type == "Pendentes":
        if is_compensated:
            return []
        coords = get_record_coordinates(record, "main")
    elif heatmap_type == "Realizadas":
        if not is_compensated:
            return []
        return get_record_plantio_coordinates(record)
    else:
        coords = get_record_coordinates(record, "main")

    if not coords:
        return []
    return [[coords[0], coords[1]]]


def build_heatmap_point(record: Compensacao, heatmap_type: str) -> Optional[List[float]]:
    points = build_heatmap_points(record, heatmap_type)
    if not points:
        return None
    return points[0]
