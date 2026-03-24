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
from app.models.display_columns import (
    DISPLAY_COLUMNS,
    DISPLAY_COLUMN_LABEL_BY_ATTR,
    display_column_label,
)
from app.services.coordinates import format_coordinate_pair
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


def _selected_headers(selected_cols: List[str]) -> List[str]:
    return [display_column_label(column) for column in selected_cols]


def _format_individual_status(record: Compensacao) -> str:
    return "CONCLUÍDO" if str(record.compensado or "").strip().upper() == "SIM" else "PENDENTE"


def _build_individual_pdf_rows(record: Compensacao, observation: str = "") -> List[List[str]]:
    rows = [
        ["Ofício/Processo:", str(record.oficio_processo or ""), "Eletrônico:", str(record.eletronico or "")],
        ["Av. Técnica:", str(record.av_tec or ""), "Caixa:", str(record.caixa or "")],
        ["Status:", _format_individual_status(record), "Microbacia:", str(record.microbacia or "")],
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


def _build_individual_pdf_header(styles):
    logo_path = resource_path("assets", "Logo_512.png")
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
        Paragraph("PREFEITURA MUNICIPAL DE S&Atilde;O CARLOS", header_title),
        Paragraph("Capital Nacional da Tecnologia", header_text),
        Paragraph("Secretaria Municipal de Conserva&ccedil;&atilde;o e Qualidade Urbana", header_text),
        Paragraph("Departamento de Poda de &Aacute;rvores", header_text),
        Paragraph("Se&ccedil;&atilde;o de Recupera&ccedil;&atilde;o Ambiental", header_text),
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


def _records_to_dict_list(records: List[Compensacao], selected_cols: List[str]) -> List[dict]:
    data_list = []
    for record in records:
        row = {}
        for attr in selected_cols:
            header_name = DISPLAY_COLUMN_LABEL_BY_ATTR.get(attr, attr)
            value = getattr(record, attr)
            row[header_name] = "" if value is None else str(value)
        data_list.append(row)
    return data_list


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
    if data:
        df_dados = pd.DataFrame(data)
    else:
        df_dados = pd.DataFrame(columns=_selected_headers(selected_cols))

    df_kpis = pd.DataFrame(kpis, columns=["Métrica", "Valor"])
    df_micro = pd.DataFrame(pend_micro_sorted, columns=["Microbacia", "Mudas Pendentes"])
    df_ele = pd.DataFrame(pend_ele_sorted, columns=["Processo Eletrônico", "Mudas Pendentes"])

    try:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df_dados.to_excel(writer, sheet_name="Dados", index=False)
            worksheet = writer.book.create_sheet("Resumo Gerencial")
            writer.sheets["Resumo Gerencial"] = worksheet

            worksheet.cell(row=1, column=1, value="Filtros Aplicados:")
            worksheet.cell(row=1, column=2, value=filtros_txt)
            worksheet["B1"].font = FONT_BOLD

            worksheet.cell(row=3, column=1, value="INDICADORES GERAIS").font = FONT_BOLD
            start_row = 4
            worksheet.cell(row=start_row, column=1, value="Métrica").font = FONT_BOLD
            worksheet.cell(row=start_row, column=2, value="Valor").font = FONT_BOLD
            for index, row in df_kpis.iterrows():
                worksheet.cell(row=start_row + 1 + index, column=1, value=row["Métrica"])
                worksheet.cell(row=start_row + 1 + index, column=2, value=row["Valor"])

            worksheet.cell(row=3, column=5, value="PENDÊNCIAS POR MICROBACIA").font = FONT_BOLD
            worksheet.cell(row=4, column=5, value="Microbacia").font = FONT_BOLD
            worksheet.cell(row=4, column=6, value="Mudas").font = FONT_BOLD
            for index, row in df_micro.iterrows():
                worksheet.cell(row=5 + index, column=5, value=row["Microbacia"])
                worksheet.cell(row=5 + index, column=6, value=row["Mudas Pendentes"])

            worksheet.cell(row=3, column=9, value="PENDÊNCIAS POR PROCESSO").font = FONT_BOLD
            worksheet.cell(row=4, column=9, value="Eletrônico").font = FONT_BOLD
            worksheet.cell(row=4, column=10, value="Mudas").font = FONT_BOLD
            for index, row in df_ele.iterrows():
                worksheet.cell(row=5 + index, column=9, value=row["Processo Eletrônico"])
                worksheet.cell(row=5 + index, column=10, value=row["Mudas Pendentes"])

            _style_worksheet(writer.sheets["Dados"], highlight_compensado=True)
            _style_worksheet(writer.sheets["Resumo Gerencial"], highlight_compensado=False)
    except Exception as exc:
        raise RuntimeError(f"Erro ao salvar Excel: {exc}") from exc


def export_pdf(
    path: str,
    records: List[Compensacao],
    filtros_txt: str,
    selected_cols: List[str],
    kpis: List[Tuple[str, Any]],
    pend_micro_sorted: List[Tuple[str, float]],
):
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
    
    # Estilos customizados para a tabela
    style_header = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontSize=7,
        leading=8,
        textColor=colors.whitesmoke,
        fontName='Helvetica-Bold',
        alignment=1 # Center
    )
    
    style_cell = ParagraphStyle(
        'CellStyle',
        parent=styles['Normal'],
        fontSize=7,
        leading=8,
        alignment=0 # Left
    )
    
    style_cell_center = ParagraphStyle(
        'CellStyleCenter',
        parent=style_cell,
        alignment=1
    )

    title_style = styles["Title"]
    title_style.fontSize = 14
    normal_style = styles["Normal"]
    normal_style.fontSize = 9

    elements.append(Paragraph("Relatório de Compensações", title_style))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(f"<b>Filtros:</b> {filtros_txt}", normal_style))
    elements.append(Spacer(1, 10))

    kpi_data = [["Métrica", "Valor"]] + [[str(key), str(value)] for key, value in kpis]
    t_kpi = Table(kpi_data, colWidths=[200, 100])
    t_kpi.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.append(Paragraph("<b>Resumo do Relatório:</b>", normal_style))
    elements.append(t_kpi)
    elements.append(Spacer(1, 15))

    headers = _selected_headers(selected_cols)
    
    # 1. Calcular pesos para larguras das colunas baseado no conteúdo
    # Colunas que tendem a ser longas ganham mais peso
    weights = []
    for attr in selected_cols:
        if "endereco" in attr.lower():
            weights.append(3.5) # Endereços precisam de mais espaço
        elif "oficio" in attr.lower() or "processo" in attr.lower():
            weights.append(2.0)
        elif "micro" in attr.lower():
            weights.append(2.0)
        elif attr in ["caixa", "av_tec", "eletronico", "compensado", "compensacao"]:
            weights.append(1.0) # Campos curtos
        else:
            weights.append(1.5)
            
    page_width = landscape(A4)[0] - 40 # Margens
    total_weight = sum(weights)
    col_widths = [(w / total_weight) * page_width for w in weights]

    # 2. Montar dados da tabela com Paragraphs para wrapping
    table_data = [[Paragraph(h, style_header) for h in headers]]
    raw_data = _records_to_dict_list(records, selected_cols)
    
    for row_dict in raw_data:
        row_elements = []
        for i, attr in enumerate(selected_cols):
            val = str(row_dict.get(headers[i], "") or "")
            # Centralizar campos curtos/status
            current_style = style_cell_center if weights[i] <= 1.0 else style_cell
            row_elements.append(Paragraph(val, current_style))
        table_data.append(row_elements)

    t_main = Table(table_data, colWidths=col_widths, repeatRows=1)
    t_main.setStyle(
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

    elements.append(Paragraph("<b>Detalhamento:</b>", normal_style))
    elements.append(t_main)
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

    chart_objs = []
    for img_path in chart_images:
        if os.path.exists(img_path):
            chart_objs.append(Image(img_path, width=350, height=250))

    if chart_objs:
        rows = []
        if len(chart_objs) >= 2:
            rows.append([chart_objs[0], chart_objs[1]])
            if len(chart_objs) > 2:
                rows.append([chart_objs[2], ""])
        else:
            rows.append([chart_objs[0]])

        t_charts = Table(rows)
        t_charts.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        elements.append(t_charts)

    doc.build(elements)


def export_individual_pdf(filepath: str, record: Compensacao):
    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "MainTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=colors.HexColor("#2C3E50"),
        alignment=1,
        spaceAfter=20,
    )

    elements = [
        Paragraph("Ficha de Compensação Ambiental", title_style),
        Spacer(1, 0.2 * inch),
    ]

    data = _build_individual_pdf_rows(record)
    table = Table(data, colWidths=[120, 150, 100, 140])
    table_style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#2C3E50")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#2C3E50")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
    ]

    for row_index, row in enumerate(data):
        if row[2] == "" and row[3] == "":
            table_style.append(("SPAN", (1, row_index), (3, row_index)))
    table.setStyle(TableStyle(table_style))

    elements.append(table)
    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Spacer(1, 2 * inch))
    elements.append(Paragraph("_" * 40, ParagraphStyle(name="Sig", alignment=1, fontSize=12)))
    elements.append(
        Paragraph(
            "Assinatura do Técnico Responsável",
            ParagraphStyle(name="SigSub", alignment=1, fontSize=10),
        )
    )

    doc.build(elements)
