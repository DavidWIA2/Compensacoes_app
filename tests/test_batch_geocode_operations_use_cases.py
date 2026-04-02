from app.application.use_cases.batch_geocode_operations import BatchGeocodeOperationsUseCases
from app.models.compensacao import Compensacao
from app.models.plantio_item import PlantioItem


def make_record(**overrides) -> Compensacao:
    payload = {
        "excel_row": 2,
        "oficio_processo": "123/2026",
        "eletronico": "SIM",
        "caixa": "CX-1",
        "av_tec": "AT-1",
        "compensacao": "10",
        "endereco": "Rua A",
        "microbacia": "",
        "compensado": "",
        "endereco_plantio": "",
        "latitude": "",
        "longitude": "",
        "uid": "geo-uid-1",
        "plantios": [],
    }
    payload.update(overrides)
    return Compensacao(**payload)


def test_batch_geocode_build_plan_counts_pending_records():
    use_cases = BatchGeocodeOperationsUseCases()
    records = [
        make_record(uid="geo-1", endereco="Rua A"),
        make_record(uid="geo-2", endereco="Rua B", microbacia="Gregorio", latitude="-22.1", longitude="-47.8"),
    ]

    plan = use_cases.build_batch_plan(records, needs_batch_geocode=lambda record: not record.microbacia)

    assert plan.total_pending == 1
    assert plan.pending_records[0].uid == "geo-1"
    assert plan.empty_message == "Tudo georreferenciado!"
    assert plan.confirmation_message == "Deseja buscar coordenadas para 1 registro?"


def test_batch_geocode_apply_results_updates_main_and_plantio_data():
    use_cases = BatchGeocodeOperationsUseCases()
    record = make_record(
        uid="geo-apply-1",
        plantios=[PlantioItem(sequence=1, endereco="Rua Plantio", qtd_mudas="4")],
    )

    plan = use_cases.apply_results(
        [record],
        {
            2: {
                "main": (-22.12, -47.91),
                "plantios": {1: (-22.11, -47.9)},
            }
        },
        micro_finder=lambda lat, lon: "Gregorio" if lat < -22 else "",
    )

    assert plan.total_updated_records == 1
    assert plan.updated_records[0].latitude == "-22.12"
    assert plan.updated_records[0].longitude == "-47.91"
    assert plan.updated_records[0].microbacia == "Gregorio"
    assert plan.updated_records[0].plantios[0].latitude == "-22.11"
    assert plan.updated_records[0].plantios[0].longitude == "-47.9"
    assert plan.updated_records[0].endereco_plantio == "Rua Plantio"


def test_batch_geocode_build_completion_presentations():
    use_cases = BatchGeocodeOperationsUseCases()

    empty = use_cases.build_completion_presentation({}, updated_count=0)
    updated = use_cases.build_completion_presentation({2: {"main": (-22.0, -47.0)}}, updated_count=2)
    unchanged = use_cases.build_completion_presentation({2: {"main": (-22.0, -47.0)}}, updated_count=0)

    assert empty.runtime_message == "Nenhum endereco pode ser processado."
    assert empty.should_reload is False
    assert updated.runtime_message == "2 registro(s) tiveram coordenadas salvas."
    assert updated.dialog_message == "2 registros tiveram coordenadas salvas."
    assert updated.should_reload is True
    assert unchanged.runtime_message == "Nenhuma coordenada nova foi salva."
    assert unchanged.should_reload is False
