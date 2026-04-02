from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from app.application.use_cases.map_rendering import MapJsCommand, MapRenderingUseCases


@dataclass(frozen=True)
class CustomLayerLoadPresentation:
    path: str
    filename: str
    loading_message: str
    success_title: str
    success_message: str
    command: MapJsCommand


class MapLayerOperationsUseCases:
    def __init__(self, rendering_use_cases: MapRenderingUseCases | None = None):
        self.rendering_use_cases = rendering_use_cases or MapRenderingUseCases()

    def build_custom_layer_loading_message(self, path: str) -> str:
        return f"Carregando camada: {os.path.basename(str(path or ''))}..."

    def load_custom_layer(
        self,
        path: str,
        *,
        geojson_loader: Callable[[str], dict[str, Any]],
    ) -> CustomLayerLoadPresentation:
        normalized_path = str(path or "").strip()
        geojson_obj = geojson_loader(normalized_path)
        return CustomLayerLoadPresentation(
            path=normalized_path,
            filename=os.path.basename(normalized_path),
            loading_message=self.build_custom_layer_loading_message(normalized_path),
            success_title="Sucesso",
            success_message="Camada carregada com sucesso.",
            command=self.rendering_use_cases.build_custom_layer_command(geojson_obj),
        )
