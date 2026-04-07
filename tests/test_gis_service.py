import geopandas as gpd
from shapely.geometry import Polygon

from app.services.gis_service import GisService


def test_find_microbacia_uses_cached_metric_projection():
    service = GisService.__new__(GisService)
    service.name_field = "Nome_Do_Arquivo"
    service.gdf = gpd.GeoDataFrame(
        {
            "Nome_Do_Arquivo": ["Gregorio"],
            "geometry": [
                Polygon(
                    [
                        (-47.8900, -22.0150),
                        (-47.8890, -22.0150),
                        (-47.8890, -22.0140),
                        (-47.8900, -22.0140),
                    ]
                )
            ],
        },
        crs="EPSG:4326",
    )
    service.sindex = type("FakeSIndex", (), {"intersection": lambda self, bounds: [0]})()
    service.metric_crs = "EPSG:31982"
    service.gdf_metric = service.gdf.to_crs(service.metric_crs)
    service._geojson_obj = None
    service.gdf.to_crs = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("to_crs nao deve rodar por consulta"))

    micro = service.find_microbacia(-22.0138, -47.8895)

    assert micro == "Gregorio"


def test_to_geojson_obj_is_cached(monkeypatch):
    service = GisService.__new__(GisService)
    service.gdf = gpd.GeoDataFrame(
        {
            "Nome_Do_Arquivo": ["Gregorio"],
            "geometry": [
                Polygon(
                    [
                        (-47.8900, -22.0150),
                        (-47.8890, -22.0150),
                        (-47.8890, -22.0140),
                        (-47.8900, -22.0140),
                    ]
                )
            ],
        },
        crs="EPSG:4326",
    )
    service._geojson_obj = None

    calls = []
    original_to_json = gpd.GeoDataFrame.to_json

    def fake_to_json(self, *args, **kwargs):
        calls.append(1)
        return original_to_json(self, *args, **kwargs)

    monkeypatch.setattr(gpd.GeoDataFrame, "to_json", fake_to_json)

    first = service.to_geojson_obj()
    second = service.to_geojson_obj()

    assert first is second
    assert len(calls) == 1


def test_get_microbacia_centroid_uses_cache_and_alias_resolution(monkeypatch):
    service = GisService.__new__(GisService)
    service.name_field = "Nome_Do_Arquivo"
    service.DE_PARA_NOMES = GisService.DE_PARA_NOMES
    service.gdf = gpd.GeoDataFrame(
        {
            "Nome_Do_Arquivo": ["Gregorio"],
            "geometry": [
                Polygon(
                    [
                        (-47.8900, -22.0150),
                        (-47.8890, -22.0150),
                        (-47.8890, -22.0140),
                        (-47.8900, -22.0140),
                    ]
                )
            ],
        },
        crs="EPSG:4326",
    )
    service.metric_crs = "EPSG:31982"
    service.gdf_metric = service.gdf.to_crs(service.metric_crs)
    service._geojson_obj = None
    service._centroid_cache = {}
    service._build_name_lookup_cache()

    calls = []
    original_to_crs = gpd.GeoSeries.to_crs

    def fake_to_crs(self, *args, **kwargs):
        calls.append(1)
        return original_to_crs(self, *args, **kwargs)

    monkeypatch.setattr(gpd.GeoSeries, "to_crs", fake_to_crs)

    first = service.get_microbacia_centroid("Microbacia do Gregorio")
    second = service.get_microbacia_centroid("Gregorio")

    assert first == second
    assert len(calls) == 1


def test_gis_service_lists_official_microbacias_sorted_by_lookup_key():
    service = GisService.__new__(GisService)
    service.name_field = "Nome_Do_Arquivo"
    service.gdf = gpd.GeoDataFrame(
        {
            "Nome_Do_Arquivo": ["Água Quente", "Gregório", "Monjolinho"],
            "geometry": [
                Polygon(
                    [
                        (-47.8900, -22.0150),
                        (-47.8890, -22.0150),
                        (-47.8890, -22.0140),
                        (-47.8900, -22.0140),
                    ]
                )
            ]
            * 3,
        },
        crs="EPSG:4326",
    )
    service._geojson_obj = None
    service._centroid_cache = {}
    service._build_name_lookup_cache()

    assert service.list_microbacias() == ["Água Quente", "Gregório", "Monjolinho"]


def test_gis_service_normalizes_alias_to_official_microbacia_name():
    service = GisService.__new__(GisService)
    service.name_field = "Nome_Do_Arquivo"
    service.DE_PARA_NOMES = GisService.DE_PARA_NOMES
    service.gdf = gpd.GeoDataFrame(
        {
            "Nome_Do_Arquivo": ["Gregório"],
            "geometry": [
                Polygon(
                    [
                        (-47.8900, -22.0150),
                        (-47.8890, -22.0150),
                        (-47.8890, -22.0140),
                        (-47.8900, -22.0140),
                    ]
                )
            ],
        },
        crs="EPSG:4326",
    )
    service._geojson_obj = None
    service._centroid_cache = {}
    service._build_name_lookup_cache()

    assert service.normalize_microbacia_name("Gregorio") == "Gregório"
