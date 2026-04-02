from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from app.application.use_cases.map_interactions import MapInteractionsUseCases
from app.application.use_cases.map_rendering import MapJsCommand, MapRenderingUseCases
from app.models.compensacao import Compensacao


GeocodeAddress = Callable[[str], tuple[float, float] | None]


@dataclass(frozen=True)
class MapFullscreenHeatmapSyncResult:
    points: tuple[tuple[float, float], ...]
    command: MapJsCommand


@dataclass(frozen=True)
class MapFullscreenClickResult:
    marker_coords: tuple[float, float]
    command: MapJsCommand
    status_message: str


@dataclass(frozen=True)
class MapFullscreenSearchResult:
    address: str
    found: bool
    marker_coords: tuple[float, float] | None
    command: MapJsCommand | None
    status_message: str


class MapFullscreenOperationsUseCases:
    def __init__(
        self,
        *,
        rendering_use_cases: MapRenderingUseCases | None = None,
        interactions_use_cases: MapInteractionsUseCases | None = None,
    ):
        self.rendering_use_cases = rendering_use_cases or MapRenderingUseCases()
        self.interactions_use_cases = interactions_use_cases or MapInteractionsUseCases()

    def build_heatmap_sync_result(
        self,
        *,
        records: Iterable[Compensacao],
        mode: str,
        enabled: bool,
    ) -> MapFullscreenHeatmapSyncResult:
        points = tuple(
            (float(point[0]), float(point[1]))
            for point in self.rendering_use_cases.build_heatmap_points(records, mode, enabled=enabled)
            if len(point) >= 2
        )
        command = self.rendering_use_cases.build_heatmap_command(points, context="fs-heatmap")
        return MapFullscreenHeatmapSyncResult(points=points, command=command)

    def build_initial_sync_commands(
        self,
        *,
        theme: str,
        geojson_data: dict | None,
        current_layer: str,
        marker_coords: tuple[float, float] | None,
        heatmap_enabled: bool,
        heatmap_points: Sequence[Sequence[float]],
    ) -> tuple[MapJsCommand, ...]:
        return self.rendering_use_cases.build_initial_sync_commands(
            theme=theme,
            geojson_data=geojson_data,
            current_layer=current_layer,
            marker_coords=marker_coords,
            heatmap_points=heatmap_points if heatmap_enabled else None,
        )

    def build_click_result(self, lat: float, lng: float) -> MapFullscreenClickResult:
        command = self.rendering_use_cases.build_marker_command(lat, lng, context="marker")
        return MapFullscreenClickResult(
            marker_coords=(lat, lng),
            command=command,
            status_message=f"Ponto: {lat:.5f}, {lng:.5f}",
        )

    def search_address(
        self,
        *,
        address: str,
        geocode_address: GeocodeAddress,
    ) -> MapFullscreenSearchResult:
        normalized_address = str(address or "").strip()
        if not normalized_address:
            return MapFullscreenSearchResult(
                address="",
                found=False,
                marker_coords=None,
                command=None,
                status_message="",
            )

        coords = geocode_address(normalized_address)
        if coords:
            lat, lng = coords
            command = self.rendering_use_cases.build_marker_command(lat, lng, context="search")
            presentation = self.interactions_use_cases.build_geocode_presentation(
                address=normalized_address,
                coords=coords,
                microbacia="",
            )
            return MapFullscreenSearchResult(
                address=normalized_address,
                found=True,
                marker_coords=(lat, lng),
                command=command,
                status_message=presentation.status_message,
            )

        presentation = self.interactions_use_cases.build_geocode_presentation(
            address=normalized_address,
            coords=None,
            microbacia="",
        )
        return MapFullscreenSearchResult(
            address=normalized_address,
            found=False,
            marker_coords=None,
            command=None,
            status_message=presentation.warning_message or presentation.status_message,
        )
