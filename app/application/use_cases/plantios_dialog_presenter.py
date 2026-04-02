from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from app.models.plantio_item import PlantioItem
from app.services.plantio_service import build_plantios_from_rows, clone_plantios, parse_numeric_value


@dataclass(frozen=True)
class PlantioRowView:
    endereco: str
    qtd_mudas: str


@dataclass(frozen=True)
class PlantiosValidationResult:
    is_valid: bool
    message: str
    plantios: tuple[PlantioItem, ...]


class PlantiosDialogPresenter:
    @staticmethod
    def build_initial_rows(plantios: Iterable[PlantioItem]) -> tuple[PlantioRowView, ...]:
        return tuple(
            PlantioRowView(
                endereco=str(getattr(item, "endereco", "") or "").strip(),
                qtd_mudas=str(getattr(item, "qtd_mudas", "") or "").strip(),
            )
            for item in clone_plantios(plantios)
        )

    @staticmethod
    def empty_row() -> PlantioRowView:
        return PlantioRowView(endereco="", qtd_mudas="")

    @staticmethod
    def total_text(rows: Sequence[PlantioRowView], compensacao_total: str = "") -> str:
        total = 0.0
        invalid = False
        for row in rows:
            if not row.endereco and not row.qtd_mudas:
                continue
            try:
                total += parse_numeric_value(row.qtd_mudas)
            except ValueError:
                invalid = True

        if invalid:
            total_text = "Soma dos plantios: valor invalido"
        else:
            total_text = f"Soma dos plantios: {total:g} mudas"

        if str(compensacao_total or "").strip():
            total_text = f"{total_text} | Compensacao: {str(compensacao_total).strip()}"
        return total_text

    @staticmethod
    def normalize_editor_values(endereco: str, qtd_mudas: str) -> PlantioRowView:
        return PlantioRowView(
            endereco=str(endereco or "").strip(),
            qtd_mudas=str(qtd_mudas or "").strip(),
        )

    def validate_rows(
        self,
        rows: Sequence[PlantioRowView],
        *,
        previous_plantios: Sequence[PlantioItem],
    ) -> PlantiosValidationResult:
        normalized_rows = [(row.endereco, row.qtd_mudas) for row in rows]
        plantios = tuple(build_plantios_from_rows(normalized_rows, previous_plantios))

        for index, item in enumerate(plantios, start=1):
            if not item.endereco:
                return PlantiosValidationResult(
                    is_valid=False,
                    message=f"Preencha o endereco do Plantio {index}.",
                    plantios=plantios,
                )
            if not item.qtd_mudas:
                return PlantiosValidationResult(
                    is_valid=False,
                    message=f"Preencha a quantidade de mudas do Plantio {index}.",
                    plantios=plantios,
                )
            try:
                qtd = parse_numeric_value(item.qtd_mudas)
            except ValueError:
                return PlantiosValidationResult(
                    is_valid=False,
                    message=f"A quantidade de mudas do Plantio {index} deve ser numerica.",
                    plantios=plantios,
                )
            if qtd <= 0:
                return PlantiosValidationResult(
                    is_valid=False,
                    message=f"A quantidade de mudas do Plantio {index} deve ser maior que zero.",
                    plantios=plantios,
                )

        return PlantiosValidationResult(
            is_valid=True,
            message="",
            plantios=plantios,
        )
