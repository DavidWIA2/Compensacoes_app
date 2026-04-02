from app.application.use_cases.plantios_dialog_presenter import (
    PlantioRowView,
    PlantiosDialogPresenter,
)
from app.models.plantio_item import PlantioItem


def test_total_text_sums_rows_and_reports_invalid_values():
    presenter = PlantiosDialogPresenter()

    valid_text = presenter.total_text(
        [
            PlantioRowView(endereco="Rua A", qtd_mudas="3"),
            PlantioRowView(endereco="Rua B", qtd_mudas="7"),
        ],
        "10",
    )
    invalid_text = presenter.total_text(
        [
            PlantioRowView(endereco="Rua A", qtd_mudas="abc"),
        ],
        "10",
    )

    assert valid_text == "Soma dos plantios: 10 mudas | Compensacao: 10"
    assert invalid_text == "Soma dos plantios: valor invalido | Compensacao: 10"


def test_validate_rows_reuses_previous_coordinates_and_blocks_invalid_values():
    presenter = PlantiosDialogPresenter()
    previous = [
        PlantioItem(sequence=1, endereco="Rua A", qtd_mudas="3", latitude="-22.01", longitude="-47.89"),
    ]

    valid = presenter.validate_rows(
        [PlantioRowView(endereco="Rua A", qtd_mudas="4")],
        previous_plantios=previous,
    )
    invalid = presenter.validate_rows(
        [PlantioRowView(endereco="Rua B", qtd_mudas="0")],
        previous_plantios=previous,
    )

    assert valid.is_valid is True
    assert valid.plantios[0].latitude == "-22.01"
    assert valid.plantios[0].longitude == "-47.89"
    assert invalid.is_valid is False
    assert invalid.message == "A quantidade de mudas do Plantio 1 deve ser maior que zero."
