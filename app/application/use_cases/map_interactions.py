from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from app.models.plantio_item import PlantioItem
from app.services.plantio_service import plantio_choice_label


@dataclass(frozen=True)
class AddressChoice:
    label: str
    address: str


@dataclass(frozen=True)
class AddressSelectionPlan:
    choices: tuple[AddressChoice, ...]
    chooser_title: str
    chooser_prompt: str
    empty_title: str
    empty_message: str
    marker_fallback: Optional[tuple[float, float]] = None

    @property
    def requires_selection(self) -> bool:
        return len(self.choices) > 1


@dataclass(frozen=True)
class GeocodePresentation:
    found: bool
    status_message: str
    warning_title: str = ""
    warning_message: str = ""
    microbacia: str = ""


class MapInteractionsUseCases:
    def build_street_view_plan(
        self,
        *,
        main_address: str,
        plantios: Sequence[PlantioItem],
        marker_coords: Optional[tuple[float, float]] = None,
    ) -> AddressSelectionPlan:
        choices: list[AddressChoice] = []
        normalized_main = str(main_address or "").strip()
        if normalized_main:
            choices.append(AddressChoice(label="Endereço Principal", address=normalized_main))

        for index, item in enumerate(plantios or [], start=1):
            address = str(getattr(item, "endereco", "") or "").strip()
            if not address:
                continue
            choices.append(
                AddressChoice(
                    label=plantio_choice_label(item, index),
                    address=address,
                )
            )

        return AddressSelectionPlan(
            choices=tuple(choices),
            chooser_title="Escolha o Endereço",
            chooser_prompt="Qual endereço você deseja visualizar no Street View?",
            empty_title="Atencao",
            empty_message="Nenhum endereco ou ponto no mapa selecionado para o Street View.",
            marker_fallback=marker_coords,
        )

    def build_plantio_search_plan(self, plantios: Sequence[PlantioItem]) -> AddressSelectionPlan:
        choices = [
            AddressChoice(label=plantio_choice_label(item, index), address=str(item.endereco or "").strip())
            for index, item in enumerate(plantios or [], start=1)
            if str(getattr(item, "endereco", "") or "").strip()
        ]
        return AddressSelectionPlan(
            choices=tuple(choices),
            chooser_title="Escolher Plantio",
            chooser_prompt="Qual endereço de plantio você deseja buscar?",
            empty_title="Atencao",
            empty_message="Cadastre ao menos um endereco de plantio para pesquisar.",
        )

    @staticmethod
    def resolve_choice(plan: AddressSelectionPlan, selected_label: str) -> str:
        for choice in plan.choices:
            if choice.label == selected_label:
                return choice.address
        return ""

    @staticmethod
    def build_geocoding_status(address: str, *, purpose: str) -> str:
        normalized = str(address or "").strip()
        if purpose == "street_view":
            return f"Geocodificando para Street View: {normalized}..."
        if purpose == "plantio_search":
            return "Pesquisando endereco de plantio..."
        return "Pesquisando endereco..."

    @staticmethod
    def build_geocode_presentation(
        *,
        address: str,
        coords: Optional[tuple[float, float]],
        microbacia: str = "",
    ) -> GeocodePresentation:
        if not coords:
            return GeocodePresentation(
                found=False,
                status_message="Endereço não encontrado",
                warning_title="Não encontrado",
                warning_message="Não consegui localizar esse endereço.",
            )

        normalized_micro = str(microbacia or "").strip()
        if normalized_micro:
            return GeocodePresentation(
                found=True,
                status_message=f"Localizado. Microbacia: {normalized_micro}",
                microbacia=normalized_micro,
            )

        return GeocodePresentation(
            found=True,
            status_message="Localizado (fora de microbacia)",
        )

    @staticmethod
    def build_street_view_lookup_failure(address: str) -> GeocodePresentation:
        normalized = str(address or "").strip()
        return GeocodePresentation(
            found=False,
            status_message="Endereço não encontrado",
            warning_title="Erro",
            warning_message=f"Não foi possível localizar o endereço: {normalized}",
        )

    @staticmethod
    def build_street_view_url(*, lat: float, lon: float) -> str:
        return f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}"
