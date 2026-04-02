from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from app.models.compensacao import Compensacao
from app.services.coordinates import build_heatmap_points


@dataclass(frozen=True)
class MapJsCommand:
    context: str
    script: str


class MapRenderingUseCases:
    def build_heatmap_points(
        self,
        records: Iterable[Compensacao],
        mode: str,
        *,
        enabled: bool = True,
    ) -> list[list[float]]:
        if not enabled:
            return []

        points: list[list[float]] = []
        for record in records:
            points.extend(build_heatmap_points(record, mode))
        return points

    @staticmethod
    def build_marker_command(lat: float, lon: float, *, context: str = "marker") -> MapJsCommand:
        return MapJsCommand(
            context=context,
            script=f"if(window.setMarker) window.setMarker({float(lat)}, {float(lon)});",
        )

    @staticmethod
    def build_status_command(message: str, *, context: str = "status") -> MapJsCommand:
        return MapJsCommand(
            context=context,
            script=f"if(window.setStatus) window.setStatus({json.dumps(str(message or ''))});",
        )

    @staticmethod
    def build_microbacias_command(geojson_obj: dict[str, Any], *, context: str = "load-microbacias") -> MapJsCommand:
        return MapJsCommand(
            context=context,
            script=f"if(window.setMicrobacias) window.setMicrobacias({json.dumps(geojson_obj)});",
        )

    @staticmethod
    def build_theme_command(theme: str, *, context: str = "theme") -> MapJsCommand:
        return MapJsCommand(
            context=context,
            script=f"if(window.setTheme) window.setTheme({json.dumps(str(theme or ''))});",
        )

    @staticmethod
    def build_base_layer_command(layer_name: str, *, context: str = "restore-layer") -> MapJsCommand:
        return MapJsCommand(
            context=context,
            script=f"if(window.setBaseLayer) window.setBaseLayer({json.dumps(str(layer_name or ''))});",
        )

    @staticmethod
    def build_highlight_command(name_field: str, name: str, *, context: str = "highlight") -> MapJsCommand:
        return MapJsCommand(
            context=context,
            script=(
                "if(window.highlightGeoJsonByName) "
                f"window.highlightGeoJsonByName({json.dumps(str(name_field or ''))}, {json.dumps(str(name or ''))});"
            ),
        )

    @staticmethod
    def build_heatmap_command(points: Sequence[Sequence[float]], *, context: str = "update-heatmap") -> MapJsCommand:
        return MapJsCommand(
            context=context,
            script=f"if(window.setHeatmap) window.setHeatmap({json.dumps(list(points))});",
        )

    @staticmethod
    def build_custom_layer_command(geojson_obj: dict[str, Any], *, context: str = "load-custom-layer") -> MapJsCommand:
        return MapJsCommand(
            context=context,
            script=(
                "if(window.map) {"
                "if(window.customLayer) window.map.removeLayer(window.customLayer);"
                f"window.customLayer = L.geoJSON({json.dumps(geojson_obj)}, "
                "{style: function(feature) {"
                "return {color: \"#e74c3c\", weight: 2, fillOpacity: 0.1, dashArray: \"5, 5\"};"
                "}}).addTo(window.map);"
                "window.map.fitBounds(window.customLayer.getBounds());"
                "}"
            ),
        )

    def build_initial_sync_commands(
        self,
        *,
        theme: str = "",
        geojson_data: dict[str, Any] | None = None,
        current_layer: str = "",
        marker_coords: tuple[float, float] | None = None,
        heatmap_points: Sequence[Sequence[float]] | None = None,
    ) -> tuple[MapJsCommand, ...]:
        commands: list[MapJsCommand] = []
        if theme:
            commands.append(self.build_theme_command(theme))
        if geojson_data:
            commands.append(self.build_microbacias_command(geojson_data, context="micro"))
        if current_layer:
            commands.append(self.build_base_layer_command(current_layer, context="layer"))
        if marker_coords:
            commands.append(
                self.build_marker_command(marker_coords[0], marker_coords[1], context="marker")
            )
        if heatmap_points is not None:
            commands.append(self.build_heatmap_command(heatmap_points, context="heat"))
        return tuple(commands)
