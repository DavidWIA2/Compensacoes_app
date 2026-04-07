from __future__ import annotations

import os
from typing import Any, List, Tuple

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.compensacao import Compensacao
from app.models.display_columns import DISPLAY_COLUMNS
from app.services.ficha_report_service import export_individual_pdf as export_ficha_report_pdf
from app.services.report_service_support import (
    DATA_SHEET_NAME,
    REPORT_DETAIL_LABEL,
    REPORT_SUMMARY_LABEL,
    REPORT_TITLE,
    SUMMARY_LABEL_FILTERS,
    SUMMARY_LABEL_GENERAL,
    SUMMARY_LABEL_METRIC,
    SUMMARY_LABEL_PENDING_MICRO,
    SUMMARY_LABEL_PENDING_TYPE,
    SUMMARY_LABEL_VALUE,
    SUMMARY_SHEET_NAME,
    build_dashboard_chart_rows,
    build_department_header_html_lines,
    build_grid_pdf_layout,
    build_individual_report_rows,
    build_records_to_dict_list,
    build_selected_headers,
    format_individual_status,
)
from app.ui.components.ui_utils import resource_path


ALL_COLUMNS = DISPLAY_COLUMNS

HEADER_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
COMPENSADO_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
BORDER_STYLE = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
FONT_BOLD = Font(bold=True)
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")


def _resolve_report_logo_path() -> str:
    candidate_paths = [
        resource_path("assets", "icons", "pga_icon_clean_512.png"),
        resource_path("assets", "Logo_512.png"),
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            return path
    return candidate_paths[-1]


def _selected_headers(selected_cols: List[str]) -> List[str]:
    return build_selected_headers(selected_cols)


def _format_individual_status(record: Compensacao) -> str:
    return format_individual_status(record)


def _build_individual_pdf_rows(record: Compensacao, observation: str = "") -> List[List[str]]:
    return build_individual_report_rows(record, observation)


def _build_individual_pdf_header(styles):
    logo_path = _resolve_report_logo_path()
    logo = Spacer(1, 1)
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=1.15 * inch, height=0.95 * inch)

    header_title = ParagraphStyle(
        "FichaHeaderTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=14,
        alignment=1,
        textColor=colors.black,
    )
    header_text = ParagraphStyle(
        "FichaHeaderText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        alignment=1,
        textColor=colors.black,
    )

    lines = [
        Paragraph(build_department_header_html_lines()[0], header_title),
        *[Paragraph(line, header_text) for line in build_department_header_html_lines()[1:]],
    ]

    table = Table([[logo, lines]], colWidths=[1.35 * inch, 4.85 * inch])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    return [
        table,
        Spacer(1, 0.12 * inch),
        HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#7A7A7A")),
        Spacer(1, 0.18 * inch),
    ]


def _records_to_dict_list(records: List[Compensacao], selected_cols: List[str]) -> List[dict[str, str]]:
    return build_records_to_dict_list(records, selected_cols)


def _style_worksheet(ws, highlight_compensado: bool = False):
    col_compensado_idx = -1
    if highlight_compensado:
        for col_idx, cell in enumerate(ws[1], start=1):
            if str(cell.value).strip().lower() == "compensado":
                col_compensado_idx = col_idx
                break

    for row in ws.iter_rows():
        is_green_row = False
        if col_compensado_idx != -1 and row[0].row > 1:
            value = row[col_compensado_idx - 1].value
            if value and str(value).strip().upper() == "SIM":
                is_green_row = True

        for cell in row:
            cell.border = BORDER_STYLE
            if cell.row == 1:
                cell.font = FONT_BOLD
                cell.fill = HEADER_FILL
                cell.alignment = ALIGN_CENTER
            elif is_green_row:
                cell.fill = COMPENSADO_FILL

            if cell.row > 1:
                if cell.value and len(str(cell.value)) < 15:
                    cell.alignment = ALIGN_CENTER
                else:
                    cell.alignment = Alignment(vertical="center", wrap_text=False)

    for column_cells in ws.columns:
        length = max(len(str(cell.value) or "") for cell in column_cells)
        final_width = min(max(length + 2, 10), 60)
        ws.column_dimensions[get_column_letter(column_cells[0].column)].width = final_width

    ws.auto_filter.ref = ws.dimensions


def _write_summary_table(worksheet, *, start_row: int, start_col: int, title: str, headers: tuple[str, str], rows):
    worksheet.cell(row=start_row, column=start_col, value=title).font = FONT_BOLD
    worksheet.cell(row=start_row + 1, column=start_col, value=headers[0]).font = FONT_BOLD
    worksheet.cell(row=start_row + 1, column=start_col + 1, value=headers[1]).font = FONT_BOLD
    for index, row in enumerate(rows):
        worksheet.cell(row=start_row + 2 + index, column=start_col, value=row[0])
        worksheet.cell(row=start_row + 2 + index, column=start_col + 1, value=row[1])


def export_csv(path: str, records: List[Compensacao], selected_cols: List[str]):
    data = _records_to_dict_list(records, selected_cols)
    if not data:
        pd.DataFrame(columns=_selected_headers(selected_cols)).to_csv(
            path,
            index=False,
            encoding="utf-8-sig",
            sep=";",
        )
        return

    pd.DataFrame(data).to_csv(path, index=False, encoding="utf-8-sig", sep=";")


def export_excel_two_sheets(
    path: str,
    records: List[Compensacao],
    filtros_txt: str,
    selected_cols: List[str],
    kpis: List[Tuple[str, Any]],
    pend_micro_sorted: List[Tuple[str, float]],
    pend_ele_sorted: List[Tuple[str, float]],
):
    data = _records_to_dict_list(records, selected_cols)
    df_dados = pd.DataFrame(data) if data else pd.DataFrame(columns=_selected_headers(selected_cols))

    try:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df_dados.to_excel(writer, sheet_name=DATA_SHEET_NAME, index=False)
            worksheet = writer.book.create_sheet(SUMMARY_SHEET_NAME)
            writer.sheets[SUMMARY_SHEET_NAME] = worksheet

            worksheet.cell(row=1, column=1, value=SUMMARY_LABEL_FILTERS)
            worksheet.cell(row=1, column=2, value=filtros_txt)
            worksheet["B1"].font = FONT_BOLD

            _write_summary_table(
                worksheet,
                start_row=3,
                start_col=1,
                title=SUMMARY_LABEL_GENERAL,
                headers=(SUMMARY_LABEL_METRIC, SUMMARY_LABEL_VALUE),
                rows=kpis,
            )
            _write_summary_table(
                worksheet,
                start_row=3,
                start_col=5,
                title=SUMMARY_LABEL_PENDING_MICRO,
                headers=("Microbacia", "Mudas"),
                rows=pend_micro_sorted,
            )
            _write_summary_table(
                worksheet,
                start_row=3,
                start_col=9,
                title=SUMMARY_LABEL_PENDING_TYPE,
                headers=("Tipo", "Mudas"),
                rows=pend_ele_sorted,
            )

            _style_worksheet(writer.sheets[DATA_SHEET_NAME], highlight_compensado=True)
            _style_worksheet(writer.sheets[SUMMARY_SHEET_NAME], highlight_compensado=False)
    except Exception as exc:
        raise RuntimeError(f"Erro ao salvar Excel: {exc}") from exc


export_spreadsheet_two_sheets = export_excel_two_sheets


def export_pdf(
    path: str,
    records: List[Compensacao],
    filtros_txt: str,
    selected_cols: List[str],
    kpis: List[Tuple[str, Any]],
    pend_micro_sorted: List[Tuple[str, float]],
):
    del pend_micro_sorted

    doc = SimpleDocTemplate(
        path,
        pagesize=landscape(A4),
        rightMargin=20,
        leftMargin=20,
        topMargin=20,
        bottomMargin=18,
    )
    elements = []
    styles = getSampleStyleSheet()

    style_header = ParagraphStyle(
        "HeaderStyle",
        parent=styles["Normal"],
        fontSize=7,
        leading=8,
        textColor=colors.whitesmoke,
        fontName="Helvetica-Bold",
        alignment=1,
    )
    style_cell = ParagraphStyle(
        "CellStyle",
        parent=styles["Normal"],
        fontSize=7,
        leading=8,
        alignment=0,
    )
    style_cell_center = ParagraphStyle(
        "CellStyleCenter",
        parent=style_cell,
        alignment=1,
    )

    title_style = styles["Title"]
    title_style.fontSize = 14
    normal_style = styles["Normal"]
    normal_style.fontSize = 9

    elements.append(Paragraph(REPORT_TITLE, title_style))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(f"<b>Filtros:</b> {filtros_txt}", normal_style))
    elements.append(Spacer(1, 10))

    kpi_data = [[SUMMARY_LABEL_METRIC, SUMMARY_LABEL_VALUE]] + [[str(key), str(value)] for key, value in kpis]
    kpi_table = Table(kpi_data, colWidths=[200, 100])
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.append(Paragraph(f"<b>{REPORT_SUMMARY_LABEL}</b>", normal_style))
    elements.append(kpi_table)
    elements.append(Spacer(1, 15))

    page_width = landscape(A4)[0] - 40
    layout = build_grid_pdf_layout(selected_cols, page_width)

    table_data = [[Paragraph(header, style_header) for header in layout.headers]]
    raw_data = _records_to_dict_list(records, selected_cols)
    for row_dict in raw_data:
        row_elements = []
        for index, attr in enumerate(selected_cols):
            value = str(row_dict.get(layout.headers[index], "") or "")
            current_style = style_cell_center if layout.weights[index] <= 1.0 else style_cell
            row_elements.append(Paragraph(value, current_style))
        table_data.append(row_elements)

    main_table = Table(table_data, colWidths=list(layout.column_widths), repeatRows=1)
    main_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )

    elements.append(Paragraph(f"<b>{REPORT_DETAIL_LABEL}</b>", normal_style))
    elements.append(main_table)
    doc.build(elements)


def export_dashboard_pdf(path: str, titulo: str, kpi_lines: List[str], filtros_txt: str, chart_images: List[str]):
    doc = SimpleDocTemplate(
        path,
        pagesize=landscape(A4),
        rightMargin=20,
        leftMargin=20,
        topMargin=20,
        bottomMargin=20,
    )
    elements = []
    styles = getSampleStyleSheet()
    elements.append(Paragraph(titulo, styles["Title"]))
    elements.append(Paragraph(f"Filtros: {filtros_txt}", styles["Normal"]))
    elements.append(Spacer(1, 20))
    for line in kpi_lines:
        elements.append(Paragraph(f"- {line}", styles["Heading3"]))
    elements.append(Spacer(1, 20))

    chart_objects = []
    for img_path in chart_images:
        if os.path.exists(img_path):
            chart_objects.append(Image(img_path, width=350, height=250))

    chart_rows = build_dashboard_chart_rows(chart_objects)
    if chart_rows:
        charts_table = Table(list(chart_rows))
        charts_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        elements.append(charts_table)

    doc.build(elements)


def export_individual_pdf(filepath: str, record: Compensacao, observation: str = ""):
    return export_ficha_report_pdf(filepath, record, observation)
