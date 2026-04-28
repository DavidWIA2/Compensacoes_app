import pytest
import app.services.geocode_service as geocode_module
from app.services.geocode_service import (
    NOMINATIM_SEARCH_URL,
    address_search_variants,
    confirm_geocode_candidate,
    extract_coordinates_from_text,
    geocode_address,
    geocode_address_arcgis,
    geocode_address_arcgis_candidates,
    geocode_address_candidates,
    geocode_address_nominatim,
    geocode_address_nominatim_candidates,
    normalize_address,
    resolve_coordinates_from_map_link,
)
from app.services.geocode_cache import geocode_cache


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def clear_cache():
    geocode_cache.clear()
    geocode_module._last_nominatim_request_at = None
    yield
    geocode_cache.clear()
    geocode_module._last_nominatim_request_at = None


def test_normalize_address_appends_city_when_missing():
    assert normalize_address("Rua Teste") == "Rua Teste, São Carlos, SP"


def test_normalize_address_keeps_city_when_present():
    assert normalize_address("Rua Teste, Sao Carlos") == "Rua Teste, Sao Carlos"


def test_address_search_variants_biases_sao_carlos_with_brazil_forms():
    assert address_search_variants("Condomínio Parque Itaipú") == [
        "Condomínio Parque Itaipú",
        "Condomínio Parque Itaipú, São Carlos, SP",
        "Condomínio Parque Itaipú, São Carlos, São Paulo, Brasil",
        "Condomínio Parque Itaipú, São Carlos, SP, Brasil",
        "Condomínio Parque Itaipú, São Carlos, Brasil",
    ]


def test_extract_coordinates_from_google_maps_url_prefers_place_pin():
    url = (
        "https://www.google.com/maps/place/Condominio/@-22.0638392,-47.8142037,1828a/"
        "data=!3m1!1e3!4m6!3m5!8m2!3d-22.0503202!4d-47.8149254"
    )

    assert extract_coordinates_from_text(url) == (-22.0503202, -47.8149254)


def test_resolve_coordinates_from_short_google_maps_link_uses_redirect_url():
    class RedirectResponse:
        status_code = 200
        url = "https://www.google.com/maps/place/Teste/data=!3d-22.0503202!4d-47.8149254"

    def fake_get(url, **kwargs):
        assert url == "https://maps.app.goo.gl/ttz2p6No6j2DPsaT6"
        assert kwargs["allow_redirects"] is True
        return RedirectResponse()

    assert resolve_coordinates_from_map_link(
        "https://maps.app.goo.gl/ttz2p6No6j2DPsaT6",
        requester=fake_get,
    ) == (-22.0503202, -47.8149254)


def test_geocode_address_arcgis_returns_coordinates():
    def fake_get(url, **kwargs):
        assert "params" in kwargs
        return FakeResponse(
            payload={
                "candidates": [
                    {"location": {"y": -22.01, "x": -47.89}}
                ]
            }
        )

    result = geocode_address_arcgis("Rua A", requester=fake_get)

    assert result == (-22.01, -47.89)


def test_geocode_address_arcgis_accepts_google_maps_short_link():
    class RedirectResponse:
        status_code = 200
        url = "https://www.google.com/maps/place/Teste/data=!3d-22.0503202!4d-47.8149254"

    def fake_get(url, **kwargs):
        return RedirectResponse()

    assert geocode_address_arcgis(
        "https://maps.app.goo.gl/ttz2p6No6j2DPsaT6",
        requester=fake_get,
    ) == (-22.0503202, -47.8149254)


def test_geocode_address_arcgis_tries_multiple_address_variants():
    attempted = []

    def fake_get(url, **kwargs):
        attempted.append(kwargs["params"]["SingleLine"])
        if kwargs["params"]["SingleLine"].endswith("São Paulo, Brasil"):
            return FakeResponse(
                payload={
                    "candidates": [
                        {"location": {"y": -22.05, "x": -47.81}},
                    ]
                }
            )
        return FakeResponse(payload={"candidates": []})

    assert geocode_address_arcgis("Condomínio Parque Itaipú", requester=fake_get) == (-22.05, -47.81)
    assert attempted[:3] == [
        "Condomínio Parque Itaipú",
        "Condomínio Parque Itaipú, São Carlos, SP",
        "Condomínio Parque Itaipú, São Carlos, São Paulo, Brasil",
    ]
    assert "Condomínio Parque Itaipú, São Carlos, SP, Brasil" in attempted


def test_geocode_candidates_rank_sao_carlos_numbered_address_first():
    def fake_get(url, **kwargs):
        return FakeResponse(
            payload={
                "candidates": [
                    {
                        "address": "Rua Teste, 123, São Paulo, SP",
                        "score": 99,
                        "location": {"y": -23.55, "x": -46.63},
                        "attributes": {"Addr_type": "PointAddress", "Place_addr": "São Paulo"},
                    },
                    {
                        "address": "Rua Teste, 123, São Carlos, SP",
                        "score": 92,
                        "location": {"y": -22.01, "x": -47.89},
                        "attributes": {"Addr_type": "PointAddress", "Place_addr": "São Carlos"},
                    },
                ]
            }
        )

    candidates = geocode_address_arcgis_candidates("Rua Teste, 123", requester=fake_get)

    assert candidates[0].match_addr == "Rua Teste, 123, São Carlos, SP"
    assert candidates[0].confidence > candidates[1].confidence


def test_confirmed_geocode_candidate_is_reused_from_cache():
    candidate = geocode_address_arcgis_candidates(
        "https://www.google.com/maps/@-22.01,-47.89,18z"
    )[0]

    confirm_geocode_candidate("Rua Confirmada, 55", candidate)

    cached = geocode_address_arcgis_candidates("Rua Confirmada, 55")
    assert cached[0].source == "cache"
    assert cached[0].coords == (-22.01, -47.89)


def test_geocode_address_nominatim_returns_and_caches_result():
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        assert url == NOMINATIM_SEARCH_URL
        assert kwargs["headers"]["User-Agent"].startswith("PlataformaGestaoAmbiental/1.0")
        return FakeResponse(
            payload=[
                {
                    "display_name": "Rua Teste, 123, São Carlos, São Paulo, Brasil",
                    "lat": "-22.01",
                    "lon": "-47.89",
                    "importance": 0.7,
                    "type": "house",
                }
            ]
        )

    assert geocode_address_nominatim(
        "Rua Teste, 123",
        requester=fake_get,
        clock=lambda: 10.0,
        sleeper=lambda _seconds: None,
    ) == (-22.01, -47.89)
    assert geocode_address_nominatim(
        "Rua Teste, 123",
        requester=fake_get,
        clock=lambda: 20.0,
        sleeper=lambda _seconds: None,
    ) == (-22.01, -47.89)
    assert len(calls) == 1


def test_geocode_address_nominatim_rate_limit_uses_injected_sleeper():
    sleeps = []
    times = iter([10.0, 10.2, 11.2])

    def fake_get(url, **kwargs):
        return FakeResponse(
            payload=[
                {
                    "display_name": "Rua A, São Carlos, Brasil",
                    "lat": "-22.01",
                    "lon": "-47.89",
                    "importance": 0.5,
                }
            ]
        )

    geocode_address_nominatim_candidates(
        "Rua A",
        requester=fake_get,
        clock=lambda: next(times),
        sleeper=sleeps.append,
    )
    geocode_cache.clear()
    geocode_address_nominatim_candidates(
        "Rua B",
        requester=fake_get,
        clock=lambda: next(times),
        sleeper=sleeps.append,
    )

    assert sleeps == pytest.approx([0.8])


def test_geocode_address_falls_back_to_arcgis_when_nominatim_fails():
    attempted_urls = []

    def fake_get(url, **kwargs):
        attempted_urls.append(url)
        if url == NOMINATIM_SEARCH_URL:
            return FakeResponse(payload=[])
        return FakeResponse(
            payload={
                "candidates": [
                    {
                        "address": "Rua Fallback, São Carlos, SP",
                        "score": 90,
                        "location": {"y": -22.02, "x": -47.9},
                        "attributes": {"Addr_type": "PointAddress", "Place_addr": "São Carlos"},
                    }
                ]
            }
        )

    assert geocode_address(
        "Rua Fallback, 100",
        requester=fake_get,
        clock=lambda: 1.0,
        sleeper=lambda _seconds: None,
    ) == (-22.02, -47.9)
    assert NOMINATIM_SEARCH_URL in attempted_urls
    assert geocode_module.ARCGIS_GEOCODE_URL in attempted_urls


def test_geocode_address_preserves_existing_coordinates_without_request():
    def fake_get(url, **kwargs):
        raise AssertionError("nao deveria chamar geocoder")

    assert geocode_address(
        "Rua Ja Coordenada",
        latitude="-22.03",
        longitude="-47.91",
        requester=fake_get,
    ) == (-22.03, -47.91)
    assert geocode_address_candidates(
        "Rua Ja Coordenada",
        latitude="-22.03",
        longitude="-47.91",
        requester=fake_get,
    )[0].source == "existing"


def test_geocode_address_arcgis_returns_none_on_empty_candidates():
    def fake_get(url, **kwargs):
        return FakeResponse(payload={"candidates": []})

    assert geocode_address_arcgis("Rua A", requester=fake_get) is None


def test_geocode_address_arcgis_returns_none_on_request_error():
    def fake_get(url, **kwargs):
        raise RuntimeError("boom")

    assert geocode_address_arcgis("Rua A", requester=fake_get) is None
