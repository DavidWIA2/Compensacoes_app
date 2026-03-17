import pytest
from app.services.geocode_service import geocode_address_arcgis, normalize_address
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
    yield
    geocode_cache.clear()


def test_normalize_address_appends_city_when_missing():
    assert normalize_address("Rua Teste") == "Rua Teste, São Carlos, SP"


def test_normalize_address_keeps_city_when_present():
    assert normalize_address("Rua Teste, Sao Carlos") == "Rua Teste, Sao Carlos"


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


def test_geocode_address_arcgis_returns_none_on_empty_candidates():
    def fake_get(url, **kwargs):
        return FakeResponse(payload={"candidates": []})

    assert geocode_address_arcgis("Rua A", requester=fake_get) is None


def test_geocode_address_arcgis_returns_none_on_request_error():
    def fake_get(url, **kwargs):
        raise RuntimeError("boom")

    assert geocode_address_arcgis("Rua A", requester=fake_get) is None
