from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from app.models.compensacao import Compensacao
from app.services.geocode_update_service import apply_geocode_to_record, find_record_by_excel_row
from app.services.plantio_service import record_plantio_items, sync_legacy_plantio_fields

CoordinatePair = tuple[float, float]
GeocodeResultMap = dict[int, dict[str, object]]
MicrobaciaFinder = Callable[[float, float], str]
NeedsBatchGeocodePredicate = Callable[[Compensacao], bool]


@dataclass(frozen=True)
class BatchGeocodePlan:
    pending_records: tuple[Compensacao, ...]
    empty_message: str
    confirmation_title: str
    confirmation_message: str

    @property
    def total_pending(self) -> int:
        return len(self.pending_records)


@dataclass(frozen=True)
class BatchGeocodePersistencePlan:
    updated_records: tuple[Compensacao, ...]

    @property
    def total_updated_records(self) -> int:
        return len(self.updated_records)


@dataclass(frozen=True)
class BatchGeocodeCompletionPresentation:
    runtime_message: str
    dialog_title: str
    dialog_message: str
    should_reload: bool = False


class BatchGeocodeOperationsUseCases:
    def build_batch_plan(
        self,
        records: Iterable[Compensacao],
        *,
        needs_batch_geocode: NeedsBatchGeocodePredicate,
    ) -> BatchGeocodePlan:
        pending_records = tuple(record for record in records if needs_batch_geocode(record))
        total_pending = len(pending_records)
        noun = "registro" if total_pending == 1 else "registros"
        return BatchGeocodePlan(
            pending_records=pending_records,
            empty_message="Tudo georreferenciado!",
            confirmation_title="GPS em Lote",
            confirmation_message=f"Deseja buscar coordenadas para {total_pending} {noun}?",
        )

    def apply_results(
        self,
        records: Iterable[Compensacao],
        results: GeocodeResultMap,
        *,
        micro_finder: Optional[MicrobaciaFinder] = None,
    ) -> BatchGeocodePersistencePlan:
        updated_records: list[Compensacao] = []
        available_records = tuple(records)

        for excel_row, geocode_data in (results or {}).items():
            record = find_record_by_excel_row(available_records, excel_row)
            if record is None:
                continue

            changed = False
            main_coords = geocode_data.get("main")
            if isinstance(main_coords, tuple) and len(main_coords) >= 2:
                lat = float(main_coords[0])
                lon = float(main_coords[1])
                apply_geocode_to_record(record, lat, lon, micro_finder)
                changed = True

            plantio_coords = self._normalize_plantio_coords(geocode_data.get("plantios"))
            legacy_plantio = geocode_data.get("plantio")
            if isinstance(legacy_plantio, tuple) and len(legacy_plantio) >= 2:
                first_plantio = next(iter(record_plantio_items(record)), None)
                if first_plantio is not None:
                    sequence = int(first_plantio.sequence)
                    plantio_coords.setdefault(
                        sequence,
                        (float(legacy_plantio[0]), float(legacy_plantio[1])),
                    )
            if plantio_coords:
                changed = self._apply_plantio_coords(record, plantio_coords, micro_finder) or changed

            if changed:
                updated_records.append(record)

        return BatchGeocodePersistencePlan(updated_records=tuple(updated_records))

    @staticmethod
    def build_cancelled_message(message: str) -> str:
        resolved = str(message or "").strip()
        return resolved or "Geocodificação em lote cancelada."

    @staticmethod
    def build_failure_runtime_message(exc: Exception) -> str:
        return f"Falha ao salvar geocodificação: {exc}"

    @staticmethod
    def build_completion_presentation(
        results: GeocodeResultMap,
        *,
        updated_count: int,
    ) -> BatchGeocodeCompletionPresentation:
        if not results:
            return BatchGeocodeCompletionPresentation(
                runtime_message="Nenhum endereco pode ser processado.",
                dialog_title="Concluido",
                dialog_message="Nenhum endereco pode ser processado.",
                should_reload=False,
            )

        if updated_count > 0:
            return BatchGeocodeCompletionPresentation(
                runtime_message=f"{updated_count} registro(s) tiveram coordenadas salvas.",
                dialog_title="Concluido",
                dialog_message=f"{updated_count} registros tiveram coordenadas salvas.",
                should_reload=True,
            )

        return BatchGeocodeCompletionPresentation(
            runtime_message="Nenhuma coordenada nova foi salva.",
            dialog_title="Concluido",
            dialog_message="Nenhuma coordenada nova foi salva.",
            should_reload=False,
        )

    def _apply_plantio_coords(
        self,
        record: Compensacao,
        plantio_coords: dict[int, CoordinatePair],
        micro_finder: Optional[MicrobaciaFinder],
    ) -> bool:
        changed = False
        updated_plantios = []
        for plantio in record_plantio_items(record):
            coords = plantio_coords.get(int(plantio.sequence))
            if coords is not None:
                plantio.latitude = str(float(coords[0]))
                plantio.longitude = str(float(coords[1]))
                changed = True
            updated_plantios.append(plantio)

        if not changed:
            return False

        record.plantios = updated_plantios
        sync_legacy_plantio_fields(record)

        if not (record.microbacia or "").strip() and micro_finder is not None:
            first_coords = next(iter(plantio_coords.values()), None)
            if first_coords is not None:
                try:
                    micro = micro_finder(float(first_coords[0]), float(first_coords[1]))
                except Exception:
                    micro = ""
                if micro and str(micro).strip():
                    record.microbacia = str(micro).strip()
        return True

    @staticmethod
    def _normalize_plantio_coords(raw_plantios: object) -> dict[int, CoordinatePair]:
        normalized: dict[int, CoordinatePair] = {}
        if isinstance(raw_plantios, dict):
            for sequence, coords in raw_plantios.items():
                try:
                    seq_value = int(sequence)
                except (TypeError, ValueError):
                    continue
                if isinstance(coords, tuple) and len(coords) >= 2:
                    normalized[seq_value] = (float(coords[0]), float(coords[1]))
        return normalized
