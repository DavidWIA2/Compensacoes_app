from app.application.use_cases.map_interactions import MapInteractionsUseCases
from app.models.plantio_item import PlantioItem


def test_map_interactions_builds_street_view_plan_with_choices_and_marker_fallback():
    use_cases = MapInteractionsUseCases()

    plan = use_cases.build_street_view_plan(
        main_address="Rua Principal",
        plantios=[
            PlantioItem(sequence=1, endereco="Rua Plantio A", qtd_mudas="4"),
            PlantioItem(sequence=2, endereco="Rua Plantio B", qtd_mudas="6"),
        ],
        marker_coords=(-22.01, -47.89),
    )

    assert [choice.label for choice in plan.choices] == [
        "Endereço Principal",
        "Plantio 1: Rua Plantio A (4 mudas)",
        "Plantio 2: Rua Plantio B (6 mudas)",
    ]
    assert plan.requires_selection is True
    assert plan.marker_fallback == (-22.01, -47.89)
    assert use_cases.resolve_choice(plan, "Plantio 2: Rua Plantio B (6 mudas)") == "Rua Plantio B"


def test_map_interactions_builds_geocode_and_street_view_presentations():
    use_cases = MapInteractionsUseCases()

    success = use_cases.build_geocode_presentation(
        address="Rua A",
        coords=(-22.01, -47.89),
        microbacia="Gregorio",
    )
    outside = use_cases.build_geocode_presentation(
        address="Rua B",
        coords=(-22.02, -47.90),
        microbacia="",
    )
    failure = use_cases.build_geocode_presentation(address="Rua C", coords=None, microbacia="")
    street_failure = use_cases.build_street_view_lookup_failure("Rua D")

    assert use_cases.build_geocoding_status("Rua A", purpose="street_view") == "Geocodificando para Street View: Rua A..."
    assert use_cases.build_geocoding_status("Rua B", purpose="plantio_search") == "Pesquisando endereco de plantio..."
    assert use_cases.build_street_view_url(lat=-22.01, lon=-47.89).startswith(
        "https://www.google.com/maps/@?api=1"
    )
    assert success.found is True
    assert success.status_message == "Localizado. Microbacia: Gregorio"
    assert success.microbacia == "Gregorio"
    assert outside.status_message == "Localizado (fora de microbacia)"
    assert failure.found is False
    assert failure.warning_title == "Não encontrado"
    assert street_failure.warning_message == "Não foi possível localizar o endereço: Rua D"
