from typing import Callable, Optional, Tuple

import requests

ARCGIS_GEOCODE_URL = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"


def normalize_address(address: str) -> str:
    clean = str(address or "").strip()
    if not clean:
        return ""

    lowered = clean.lower()
    if "são carlos" not in lowered and "sao carlos" not in lowered:
        clean += ", São Carlos, SP"

    return clean


def geocode_address_arcgis(
    address: str,
    *,
    timeout: int = 10,
    requester: Callable = requests.get,
) -> Optional[Tuple[float, float]]:
    clean_addr = normalize_address(address)
    if not clean_addr:
        return None

    params = {
        "SingleLine": clean_addr,
        "f": "json",
        "maxLocations": 1,
        "outFields": "Match_addr,Addr_type",
        "countryCode": "BRA",
    }
    headers = {"User-Agent": "CompensacoesApp/1.0"}

    try:
        response = requester(ARCGIS_GEOCODE_URL, params=params, headers=headers, timeout=timeout)
    except Exception:
        return None

    if getattr(response, "status_code", 200) != 200:
        return None

    try:
        data = response.json()
    except Exception:
        return None

    candidates = data.get("candidates") or []
    if not candidates:
        return None

    loc = candidates[0].get("location") or {}
    try:
        return float(loc["y"]), float(loc["x"])
    except Exception:
        return None
