from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Optional, Tuple
from urllib.parse import unquote, urlparse

import requests

from app.config import (
    GEOCODER_FALLBACK_PROVIDER,
    GEOCODER_PROVIDER,
    GEOCODER_RATE_LIMIT_SECONDS,
    GEOCODER_USER_AGENT,
)
from app.services.geocode_cache import geocode_cache

ARCGIS_GEOCODE_URL = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
SAO_CARLOS_LAT = -22.015
SAO_CARLOS_LON = -47.89
SAO_CARLOS_LOCATION_BIAS = f"{SAO_CARLOS_LON},{SAO_CARLOS_LAT}"
SAO_CARLOS_SEARCH_DISTANCE_METERS = 60000
GOOGLE_MAPS_HOSTS = (
    "google.",
    "maps.google.",
    "maps.app.goo.gl",
    "goo.gl",
)
_last_nominatim_request_at: float | None = None


@dataclass(frozen=True)
class GeocodeCandidate:
    lat: float
    lon: float
    confidence: float
    match_addr: str
    place_addr: str = ""
    addr_type: str = ""
    query: str = ""
    source: str = "arcgis"
    raw_score: float = 0.0
    distance_km: float = 0.0

    @property
    def coords(self) -> tuple[float, float]:
        return self.lat, self.lon

    @property
    def title(self) -> str:
        return self.match_addr or self.place_addr or f"{self.lat:.6f}, {self.lon:.6f}"

    def choice_label(self) -> str:
        details: list[str] = [self.title]
        if self.addr_type:
            details.append(self.addr_type)
        if self.distance_km:
            details.append(f"{self.distance_km:.1f} km do centro")
        details.append(f"confianca {self.confidence:.0f}%")
        return " | ".join(details)


def _strip_accents(value: object) -> str:
    text = str(value or "")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _normalize_key(value: object) -> str:
    return " ".join(_strip_accents(value).casefold().split())


def _valid_coords(lat: float, lon: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lon <= 180


def _coerce_existing_coords(latitude: object = None, longitude: object = None) -> Optional[Tuple[float, float]]:
    try:
        if latitude in (None, "") or longitude in (None, ""):
            return None
        lat = float(str(latitude).strip())
        lon = float(str(longitude).strip())
    except Exception:
        return None
    return (lat, lon) if _valid_coords(lat, lon) else None


def _distance_km(lat: float, lon: float, ref_lat: float = SAO_CARLOS_LAT, ref_lon: float = SAO_CARLOS_LON) -> float:
    radius_km = 6371.0088
    phi1 = math.radians(ref_lat)
    phi2 = math.radians(lat)
    delta_phi = math.radians(lat - ref_lat)
    delta_lambda = math.radians(lon - ref_lon)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _requested_street_number(address: object) -> str:
    text = str(address or "")
    match = re.search(r"\b(?:n[ºo.]?\s*)?(\d{1,6})(?:\D|$)", text, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _expand_address_abbreviations(address: str) -> str:
    text = str(address or "").strip()
    replacements = (
        (r"\bR\.\s+", "Rua "),
        (r"\bAv\.\s+", "Avenida "),
        (r"\bAv\s+", "Avenida "),
        (r"\bRod\.\s+", "Rodovia "),
        (r"\bPca\.\s+", "Praca "),
        (r"\bPç\.\s+", "Praca "),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return " ".join(text.split())


def extract_coordinates_from_text(value: object) -> Optional[Tuple[float, float]]:
    text = unquote(str(value or "").strip())
    if not text:
        return None

    patterns = (
        r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)",
        r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)",
        r"(?:[?&](?:q|query|ll)=)(?:loc:)?(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)",
        r"\b(-?\d{1,2}\.\d+),\s*(-?\d{1,3}\.\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            lat = float(match.group(1))
            lon = float(match.group(2))
        except Exception:
            continue
        if _valid_coords(lat, lon):
            return lat, lon
    return None


def looks_like_map_url(value: object) -> bool:
    text = str(value or "").strip().lower()
    if not text.startswith(("http://", "https://")):
        return False
    host = urlparse(text).netloc.lower()
    return any(token in host for token in GOOGLE_MAPS_HOSTS)


def resolve_coordinates_from_map_link(
    value: object,
    *,
    timeout: int = 10,
    requester: Callable = requests.get,
) -> Optional[Tuple[float, float]]:
    direct = extract_coordinates_from_text(value)
    if direct:
        return direct
    if not looks_like_map_url(value):
        return None

    headers = {"User-Agent": "CompensacoesApp/1.0"}
    try:
        response = requester(str(value).strip(), headers=headers, timeout=timeout, allow_redirects=True)
    except Exception:
        return None

    response_url = str(getattr(response, "url", "") or "")
    resolved = extract_coordinates_from_text(response_url)
    if resolved:
        return resolved

    try:
        body = getattr(response, "text", "") or getattr(response, "content", "") or ""
        return extract_coordinates_from_text(body)
    except Exception:
        return None


def normalize_address(address: str) -> str:
    clean = _expand_address_abbreviations(address)
    if not clean:
        return ""

    lowered = _normalize_key(clean)
    if "sao carlos" not in lowered:
        clean += ", São Carlos, SP"

    return clean


def address_search_variants(address: str) -> list[str]:
    clean = _expand_address_abbreviations(address)
    if not clean:
        return []

    candidates = [clean, normalize_address(clean)]
    lowered = _normalize_key(clean)
    if "sao carlos" not in lowered:
        candidates.extend(
            [
                f"{clean}, São Carlos, São Paulo, Brasil",
                f"{clean}, São Carlos, SP, Brasil",
                f"{clean}, São Carlos, Brasil",
            ]
        )

    variants: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = " ".join(str(candidate or "").split())
        key = _normalize_key(normalized)
        if normalized and key not in seen:
            variants.append(normalized)
            seen.add(key)
    return variants


def _rate_limit_nominatim(
    *,
    rate_limit_seconds: float = GEOCODER_RATE_LIMIT_SECONDS,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> None:
    global _last_nominatim_request_at
    import time

    now_fn = clock or time.monotonic
    sleep_fn = sleeper or time.sleep
    now = float(now_fn())
    if _last_nominatim_request_at is not None:
        elapsed = now - _last_nominatim_request_at
        wait_seconds = float(rate_limit_seconds) - elapsed
        if wait_seconds > 0:
            sleep_fn(wait_seconds)
            now = float(now_fn())
    _last_nominatim_request_at = now


def _candidate_from_nominatim_item(item: dict, *, query: str) -> GeocodeCandidate | None:
    try:
        lat = float(item.get("lat"))
        lon = float(item.get("lon"))
    except Exception:
        return None
    if not _valid_coords(lat, lon):
        return None

    display_name = str(item.get("display_name") or "").strip()
    item_type = str(item.get("type") or item.get("class") or "").strip()
    importance = float(item.get("importance") or 0)
    distance_km = _distance_km(lat, lon)
    combined = _normalize_key(display_name)
    requested_number = _requested_street_number(query)

    confidence = 62 + min(max(importance, 0), 1) * 20
    if "sao carlos" in combined:
        confidence += 14
    else:
        confidence -= 18
    if distance_km <= 18:
        confidence += 8
    elif distance_km <= 35:
        confidence += 2
    else:
        confidence -= min((distance_km - 35) * 0.7, 25)
    if requested_number:
        if re.search(rf"\b{re.escape(requested_number)}\b", display_name):
            confidence += 6
        else:
            confidence -= 5

    return GeocodeCandidate(
        lat=lat,
        lon=lon,
        confidence=max(0.0, min(confidence, 100.0)),
        match_addr=display_name,
        place_addr=display_name,
        addr_type=item_type,
        query=query,
        source="nominatim",
        raw_score=importance,
        distance_km=distance_km,
    )


def geocode_address_nominatim_candidates(
    address: str,
    *,
    latitude: object = None,
    longitude: object = None,
    timeout: int = 10,
    requester: Callable = requests.get,
    max_candidates: int = 5,
    rate_limit_seconds: float = GEOCODER_RATE_LIMIT_SECONDS,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> list[GeocodeCandidate]:
    existing = _coerce_existing_coords(latitude, longitude)
    if existing:
        lat, lon = existing
        return [
            GeocodeCandidate(
                lat=lat,
                lon=lon,
                confidence=100.0,
                match_addr="Coordenada existente",
                query=str(address or "").strip(),
                source="existing",
                distance_km=_distance_km(lat, lon),
            )
        ]

    original_address = str(address or "").strip()
    direct_coords = resolve_coordinates_from_map_link(original_address, timeout=timeout, requester=requester)
    if direct_coords:
        lat, lon = direct_coords
        return [
            GeocodeCandidate(
                lat=lat,
                lon=lon,
                confidence=100.0,
                match_addr="Coordenada informada",
                query=original_address,
                source="map_link",
                distance_km=_distance_km(lat, lon),
            )
        ]

    variants = address_search_variants(original_address)
    if not variants:
        return []
    normalized_address = normalize_address(original_address)
    cached = geocode_cache.get(normalized_address) or geocode_cache.get(variants[0])
    if cached:
        lat, lon = cached
        return [
            GeocodeCandidate(
                lat=lat,
                lon=lon,
                confidence=100.0,
                match_addr=f"Endereco confirmado: {normalized_address}",
                query=normalized_address,
                source="cache",
                distance_km=_distance_km(lat, lon),
            )
        ]

    headers = {"User-Agent": GEOCODER_USER_AGENT}
    found: list[GeocodeCandidate] = []
    for variant in variants[:3]:
        _rate_limit_nominatim(
            rate_limit_seconds=rate_limit_seconds,
            clock=clock,
            sleeper=sleeper,
        )
        params = {
            "q": variant,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": max(max_candidates, 5),
            "countrycodes": "br",
            "accept-language": "pt-BR,pt",
            "viewbox": "-48.12,-21.86,-47.70,-22.18",
            "bounded": 0,
        }
        try:
            response = requester(NOMINATIM_SEARCH_URL, params=params, headers=headers, timeout=timeout)
        except Exception:
            continue
        if getattr(response, "status_code", 200) != 200:
            continue
        try:
            payload = response.json()
        except Exception:
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            if not isinstance(item, dict):
                continue
            candidate = _candidate_from_nominatim_item(item, query=variant)
            if candidate:
                found.append(candidate)
        if found:
            break

    return _dedupe_candidates(found)[:max_candidates]


def geocode_address_nominatim(
    address: str,
    *,
    latitude: object = None,
    longitude: object = None,
    timeout: int = 10,
    requester: Callable = requests.get,
    rate_limit_seconds: float = GEOCODER_RATE_LIMIT_SECONDS,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> Optional[Tuple[float, float]]:
    candidates = geocode_address_nominatim_candidates(
        address,
        latitude=latitude,
        longitude=longitude,
        timeout=timeout,
        requester=requester,
        max_candidates=3,
        rate_limit_seconds=rate_limit_seconds,
        clock=clock,
        sleeper=sleeper,
    )
    if not candidates:
        return None
    best = candidates[0]
    if best.source not in {"existing"}:
        geocode_cache.set(normalize_address(address), best.lat, best.lon, label=best.title)
    return best.coords


def _candidate_confidence(item: dict, *, query: str, variant_index: int, lat: float, lon: float) -> tuple[float, float]:
    raw_score = float(item.get("score") or item.get("Score") or 0)
    match_addr = str(item.get("address") or item.get("Match_addr") or "").strip()
    attributes = item.get("attributes") or {}
    place_addr = str(attributes.get("Place_addr") or item.get("Place_addr") or "").strip()
    addr_type = str(attributes.get("Addr_type") or item.get("Addr_type") or "").strip()
    combined_text = _normalize_key(f"{match_addr} {place_addr}")
    requested_number = _requested_street_number(query)
    distance_km = _distance_km(lat, lon)

    confidence = raw_score
    if not raw_score:
        confidence = 60.0

    confidence += max(0, 4 - variant_index) * 1.5
    if "sao carlos" in combined_text:
        confidence += 10
    else:
        confidence -= 16

    if distance_km <= 18:
        confidence += 8
    elif distance_km <= 35:
        confidence += 2
    else:
        confidence -= min((distance_km - 35) * 0.7, 25)

    type_key = _normalize_key(addr_type)
    if type_key in {"pointaddress", "streetaddress", "subaddress"}:
        confidence += 8
    elif type_key in {"streetint", "streetname"}:
        confidence += 2
    elif type_key in {"postal", "locality", "admin"}:
        confidence -= 8

    if requested_number:
        if re.search(rf"\b{re.escape(requested_number)}\b", match_addr):
            confidence += 7
        else:
            confidence -= 6

    return max(0.0, min(confidence, 100.0)), distance_km


def _candidate_from_item(item: dict, *, query: str, variant_index: int) -> GeocodeCandidate | None:
    loc = item.get("location") or {}
    try:
        lat = float(loc["y"])
        lon = float(loc["x"])
    except Exception:
        return None
    if not _valid_coords(lat, lon):
        return None

    attributes = item.get("attributes") or {}
    match_addr = str(item.get("address") or attributes.get("Match_addr") or "").strip()
    place_addr = str(attributes.get("Place_addr") or "").strip()
    addr_type = str(attributes.get("Addr_type") or "").strip()
    confidence, distance_km = _candidate_confidence(
        item,
        query=query,
        variant_index=variant_index,
        lat=lat,
        lon=lon,
    )
    return GeocodeCandidate(
        lat=lat,
        lon=lon,
        confidence=confidence,
        match_addr=match_addr,
        place_addr=place_addr,
        addr_type=addr_type,
        query=query,
        raw_score=float(item.get("score") or item.get("Score") or 0),
        distance_km=distance_km,
    )


def _dedupe_candidates(candidates: list[GeocodeCandidate]) -> list[GeocodeCandidate]:
    best_by_key: dict[str, GeocodeCandidate] = {}
    for candidate in candidates:
        key = f"{round(candidate.lat, 6)}|{round(candidate.lon, 6)}|{_normalize_key(candidate.title)}"
        current = best_by_key.get(key)
        if current is None or candidate.confidence > current.confidence:
            best_by_key[key] = candidate
    return sorted(best_by_key.values(), key=lambda item: item.confidence, reverse=True)


def geocode_address_arcgis_candidates(
    address: str,
    *,
    timeout: int = 10,
    requester: Callable = requests.get,
    max_candidates: int = 5,
) -> list[GeocodeCandidate]:
    original_address = str(address or "").strip()
    direct_coords = resolve_coordinates_from_map_link(original_address, timeout=timeout, requester=requester)
    if direct_coords:
        lat, lon = direct_coords
        geocode_cache.set(original_address, lat, lon, label="Coordenada informada")
        return [
            GeocodeCandidate(
                lat=lat,
                lon=lon,
                confidence=100.0,
                match_addr="Coordenada informada",
                query=original_address,
                source="map_link",
                distance_km=_distance_km(lat, lon),
            )
        ]

    variants = address_search_variants(original_address)
    if not variants:
        return []

    clean_addr = variants[0]
    cached = geocode_cache.get(clean_addr) or geocode_cache.get(original_address)
    if cached:
        lat, lon = cached
        return [
            GeocodeCandidate(
                lat=lat,
                lon=lon,
                confidence=100.0,
                match_addr=f"Endereco confirmado: {clean_addr}",
                query=clean_addr,
                source="cache",
                distance_km=_distance_km(lat, lon),
            )
        ]

    headers = {"User-Agent": "CompensacoesApp/1.0"}
    found: list[GeocodeCandidate] = []

    for variant_index, candidate_query in enumerate(variants):
        cached = geocode_cache.get(candidate_query)
        if cached:
            lat, lon = cached
            found.append(
                GeocodeCandidate(
                    lat=lat,
                    lon=lon,
                    confidence=100.0,
                    match_addr=f"Endereco confirmado: {candidate_query}",
                    query=candidate_query,
                    source="cache",
                    distance_km=_distance_km(lat, lon),
                )
            )
            continue

        params = {
            "SingleLine": candidate_query,
            "f": "json",
            "maxLocations": max(max_candidates, 5),
            "outFields": "Match_addr,Addr_type,Place_addr",
            "countryCode": "BRA",
            "location": SAO_CARLOS_LOCATION_BIAS,
            "distance": SAO_CARLOS_SEARCH_DISTANCE_METERS,
            "langCode": "PT",
        }
        try:
            response = requester(ARCGIS_GEOCODE_URL, params=params, headers=headers, timeout=timeout)
        except Exception:
            continue

        if getattr(response, "status_code", 200) != 200:
            continue

        try:
            data = response.json()
        except Exception:
            continue

        for item in data.get("candidates") or []:
            candidate = _candidate_from_item(item, query=candidate_query, variant_index=variant_index)
            if candidate:
                found.append(candidate)

    return _dedupe_candidates(found)[:max_candidates]


def confirm_geocode_candidate(address: str, candidate: GeocodeCandidate) -> None:
    original = str(address or "").strip()
    label = candidate.title
    for key in {original, normalize_address(original), candidate.query}:
        if key:
            geocode_cache.set(key, candidate.lat, candidate.lon, confirmed=True, label=label)


def geocode_address_candidates(
    address: str,
    *,
    latitude: object = None,
    longitude: object = None,
    provider: str = GEOCODER_PROVIDER,
    fallback_provider: str = GEOCODER_FALLBACK_PROVIDER,
    timeout: int = 10,
    requester: Callable = requests.get,
    max_candidates: int = 5,
    rate_limit_seconds: float = GEOCODER_RATE_LIMIT_SECONDS,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> list[GeocodeCandidate]:
    existing = _coerce_existing_coords(latitude, longitude)
    if existing:
        lat, lon = existing
        return [
            GeocodeCandidate(
                lat=lat,
                lon=lon,
                confidence=100.0,
                match_addr="Coordenada existente",
                query=str(address or "").strip(),
                source="existing",
                distance_km=_distance_km(lat, lon),
            )
        ]

    normalized_provider = str(provider or "nominatim").strip().lower()
    normalized_fallback = str(fallback_provider or "").strip().lower()

    def run_provider(name: str) -> list[GeocodeCandidate]:
        if name == "nominatim":
            return geocode_address_nominatim_candidates(
                address,
                timeout=timeout,
                requester=requester,
                max_candidates=max_candidates,
                rate_limit_seconds=rate_limit_seconds,
                clock=clock,
                sleeper=sleeper,
            )
        if name == "arcgis":
            return geocode_address_arcgis_candidates(
                address,
                timeout=timeout,
                requester=requester,
                max_candidates=max_candidates,
            )
        return []

    candidates = run_provider(normalized_provider)
    if candidates or not normalized_fallback or normalized_fallback == normalized_provider:
        return candidates
    return run_provider(normalized_fallback)


def geocode_address(
    address: str,
    *,
    latitude: object = None,
    longitude: object = None,
    provider: str = GEOCODER_PROVIDER,
    fallback_provider: str = GEOCODER_FALLBACK_PROVIDER,
    timeout: int = 10,
    requester: Callable = requests.get,
    rate_limit_seconds: float = GEOCODER_RATE_LIMIT_SECONDS,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> Optional[Tuple[float, float]]:
    candidates = geocode_address_candidates(
        address,
        latitude=latitude,
        longitude=longitude,
        provider=provider,
        fallback_provider=fallback_provider,
        timeout=timeout,
        requester=requester,
        max_candidates=3,
        rate_limit_seconds=rate_limit_seconds,
        clock=clock,
        sleeper=sleeper,
    )
    if not candidates:
        return None
    best = candidates[0]
    if best.source not in {"existing"}:
        geocode_cache.set(normalize_address(address), best.lat, best.lon, label=best.title)
    return best.coords


def geocode_address_arcgis(
    address: str,
    *,
    timeout: int = 10,
    requester: Callable = requests.get,
) -> Optional[Tuple[float, float]]:
    candidates = geocode_address_arcgis_candidates(address, timeout=timeout, requester=requester, max_candidates=3)
    if not candidates:
        return None

    best = candidates[0]
    geocode_cache.set(str(address or "").strip(), best.lat, best.lon, label=best.title)
    return best.coords
