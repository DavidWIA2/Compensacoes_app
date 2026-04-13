from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Sequence

from app.models.compensacao import Compensacao
from app.models.display_columns import DISPLAY_COLUMN_LABEL_BY_ATTR, display_column_label
from app.services.coordinates import format_coordinate_pair
from app.services.records_service import display_tipo_value
from app.ui.components.ui_utils import resource_path


DATA_SHEET_NAME = "Dados"
SUMMARY_SHEET_NAME = "Resumo Gerencial"
REPORT_TITLE = "Relatório de Compensações"
REPORT_SUMMARY_LABEL = "Resumo do Relatório"
REPORT_DETAIL_LABEL = "Detalhamento"
SUMMARY_LABEL_FILTERS = "Filtros aplicados"
SUMMARY_LABEL_GENERAL = "INDICADORES GERAIS"
SUMMARY_LABEL_METRIC = "Métrica"
SUMMARY_LABEL_VALUE = "Valor"
SUMMARY_LABEL_PENDING_MICRO = "PENDÊNCIAS POR MICROBACIA"
SUMMARY_LABEL_PENDING_TYPE = "PENDÊNCIAS POR TIPO"
INSTITUTIONAL_APP_NAME = "Plataforma de Gestão Ambiental"
INSTITUTIONAL_REPORT_SUBTITLE = "Prefeitura Municipal de São Carlos"
INSTITUTIONAL_SOURCE_LABEL = "Base operacional atual"


@dataclass(frozen=True)
class ReportMetadataRow:
    label: str
    value: str


@dataclass(frozen=True)
class GridPdfLayout:
    headers: tuple[str, ...]
    weights: tuple[float, ...]
    column_widths: tuple[float, ...]


def build_selected_headers(selected_cols: Sequence[str]) -> List[str]:
    return [display_column_label(column) for column in selected_cols]


def format_individual_status(record: Compensacao) -> str:
    return "CONCLUÍDO" if str(record.compensado or "").strip().upper() == "SIM" else "PENDENTE"


def build_individual_report_rows(record: Compensacao, observation: str = "") -> List[List[str]]:
    rows = [
        ["Ofício/Processo:", str(record.oficio_processo or ""), "Tipo:", display_tipo_value(record.eletronico)],
        ["Av. Técnica:", str(record.av_tec or ""), "Caixa:", str(record.caixa or "")],
        ["Status:", format_individual_status(record), "Microbacia:", str(record.microbacia or "")],
        ["Volume (Mudas):", str(record.compensacao or ""), "", ""],
        ["End. Ocorrência:", str(record.endereco or ""), "", ""],
        ["End. Plantio:", str(record.endereco_plantio or ""), "", ""],
    ]

    main_coords = format_coordinate_pair(record.latitude, record.longitude)
    plantio_coords = format_coordinate_pair(record.latitude_plantio, record.longitude_plantio)
    if main_coords:
        rows.append(["Coord. Ocorrência:", main_coords, "", ""])
    if plantio_coords:
        rows.append(["Coord. Plantio:", plantio_coords, "", ""])
    if not main_coords and not plantio_coords:
        rows.append(["Coordenadas:", "", "", ""])
    if str(observation or "").strip():
        rows.append(["Observações:", str(observation).strip(), "", ""])

    return rows


def build_department_header_html_lines() -> tuple[str, ...]:
    return (
        "PREFEITURA MUNICIPAL DE S&Atilde;O CARLOS",
        "Capital Nacional da Tecnologia",
        "Secretaria Municipal de Conserva&ccedil;&atilde;o e Qualidade Urbana",
        "Departamento de Poda de &Aacute;rvores",
        "Se&ccedil;&atilde;o de Recupera&ccedil;&atilde;o Ambiental",
    )


def build_records_to_dict_list(records: Sequence[Compensacao], selected_cols: Sequence[str]) -> List[dict[str, str]]:
    data_list: List[dict[str, str]] = []
    for record in records:
        row: dict[str, str] = {}
        for attr in selected_cols:
            header_name = DISPLAY_COLUMN_LABEL_BY_ATTR.get(attr, attr)
            value = getattr(record, attr)
            if attr == "eletronico":
                value = display_tipo_value(value)
            row[header_name] = "" if value is None else str(value)
        data_list.append(row)
    return data_list


def format_report_timestamp(timestamp: datetime | None = None) -> str:
    value = timestamp or datetime.now()
    return value.strftime("%d/%m/%Y %H:%M")


def build_report_metadata_rows(
    filter_summary: str,
    *,
    source_label: str = INSTITUTIONAL_SOURCE_LABEL,
    generated_at: datetime | None = None,
) -> tuple[ReportMetadataRow, ...]:
    normalized_filter = str(filter_summary or "").strip() or "Sem filtros aplicados"
    normalized_source = str(source_label or "").strip() or INSTITUTIONAL_SOURCE_LABEL
    return (
        ReportMetadataRow("Sistema", INSTITUTIONAL_APP_NAME),
        ReportMetadataRow("Origem", normalized_source),
        ReportMetadataRow("Emitido em", format_report_timestamp(generated_at)),
        ReportMetadataRow("Escopo", normalized_filter),
    )


def resolve_report_logo_path() -> str:
    candidate_paths = (
        resource_path("assets", "logo_prefeitura.png"),
        resource_path("assets", "icons", "pga_icon_clean_512.png"),
        resource_path("assets", "Logo_512.png"),
    )
    for path in candidate_paths:
        if not path:
            continue
        try:
            with open(path, "rb"):
                return path
        except OSError:
            continue
    return candidate_paths[0]


def _column_weight_for_attr(attr: str) -> float:
    normalized = str(attr or "").strip().lower()
    if "endereco" in normalized:
        return 3.5
    if "oficio" in normalized or "processo" in normalized:
        return 2.0
    if "micro" in normalized:
        return 2.0
    if normalized in {"caixa", "av_tec", "eletronico", "compensado", "compensacao"}:
        return 1.0
    return 1.5


def build_grid_pdf_layout(selected_cols: Sequence[str], page_width: float) -> GridPdfLayout:
    headers = tuple(build_selected_headers(selected_cols))
    weights = tuple(_column_weight_for_attr(attr) for attr in selected_cols)
    total_weight = sum(weights) or 1.0
    column_widths = tuple((weight / total_weight) * page_width for weight in weights)
    return GridPdfLayout(headers=headers, weights=weights, column_widths=column_widths)


def build_dashboard_chart_rows(chart_objects: Sequence[Any]) -> tuple[tuple[Any, ...], ...]:
    valid_items = tuple(item for item in chart_objects if item)
    if not valid_items:
        return ()
    if len(valid_items) == 1:
        return ((valid_items[0],),)
    if len(valid_items) == 2:
        return ((valid_items[0], valid_items[1]),)
    return (
        (valid_items[0], valid_items[1]),
        (valid_items[2], ""),
    )
