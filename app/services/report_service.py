import csv
import os
from typing import List, Tuple, Any

import pandas as pd
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image

from app.models.compensacao import Compensacao

ALL_COLUMNS = [
    ("Ofício/ Processo", "oficio_processo"),
    ("Eletrônico", "eletronico"),
    ("Caixa", "caixa"),
    ("Av. Tec.", "av_tec"),
    ("Compensação", "compensacao"),
    ("Endereço", "endereco"),
    ("Microbacia", "microbacia"),
    ("Compensado", "compensado")
]

HEADER_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
COMPENSADO_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
BORDER_STYLE = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'),
                      bottom=Side(style='thin'))
FONT_BOLD = Font(bold=True)
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")


def _records_to_dict_list(records: List[Compensacao], selected_cols: List[str]) -> List[dict]:
    data_list = []
    col_map = {attr: name for name, attr in ALL_COLUMNS}
    for r in records:
        row = {}
        for attr in selected_cols:
            header_name = col_map.get(attr, attr)
            val = getattr(r, attr)
            if val is None: val = ""
            row[header_name] = str(val)
        data_list.append(row)
    return data_list


def _style_worksheet(ws, highlight_compensado=False):
    col_compensado_idx = -1
    if highlight_compensado:
        for col_idx, cell in enumerate(ws[1], start=1):
            if str(cell.value).strip().lower() == "compensado":
                col_compensado_idx = col_idx
                break
    for row in ws.iter_rows():
        is_green_row = False
        if col_compensado_idx != -1 and row[0].row > 1:
            val = row[col_compensado_idx - 1].value
            if val and str(val).strip().upper() == "SIM":
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
        col_map = {attr: name for name, attr in ALL_COLUMNS}
        headers = [col_map.get(c, c) for c in selected_cols]
        df = pd.DataFrame(columns=headers)
        df.to_csv(path, index=False, encoding="utf-8-sig", sep=";")
        return
    df = pd.DataFrame(data)
    df.to_csv(path, index=False, encoding="utf-8-sig", sep=";")


def export_excel_two_sheets(path: str, records: List[Compensacao], filtros_txt: str,
                            selected_cols: List[str], kpis: List[Tuple[str, Any]],
                            pend_micro_sorted: List[Tuple[str, float]],
                            pend_ele_sorted: List[Tuple[str, float]]):
    data = _records_to_dict_list(records, selected_cols)
    if data:
        df_dados = pd.DataFrame(data)
    else:
        col_map = {attr: name for name, attr in ALL_COLUMNS}
        headers = [col_map.get(c, c) for c in selected_cols]
        df_dados = pd.DataFrame(columns=headers)

    df_kpis = pd.DataFrame(kpis, columns=["Métrica", "Valor"])
    df_micro = pd.DataFrame(pend_micro_sorted, columns=["Microbacia", "Mudas Pendentes"])
    df_ele = pd.DataFrame(pend_ele_sorted, columns=["Processo Eletrônico", "Mudas Pendentes"])

    try:
        with pd.ExcelWriter(path, engine='openpyxl') as writer:
            df_dados.to_excel(writer, sheet_name='Dados', index=False)
            workbook = writer.book
            worksheet = workbook.create_sheet("Resumo Gerencial")
            writer.sheets["Resumo Gerencial"] = worksheet

            worksheet.cell(row=1, column=1, value="Filtros Aplicados:")
            worksheet.cell(row=1, column=2, value=filtros_txt)
            worksheet["B1"].font = FONT_BOLD

            worksheet.cell(row=3, column=1, value="INDICADORES GERAIS").font = FONT_BOLD
            start_row = 4
            worksheet.cell(row=start_row, column=1, value="Métrica").font = FONT_BOLD
            worksheet.cell(row=start_row, column=2, value="Valor").font = FONT_BOLD
            for i, row in df_kpis.iterrows():
                worksheet.cell(row=start_row + 1 + i, column=1, value=row["Métrica"])
                worksheet.cell(row=start_row + 1 + i, column=2, value=row["Valor"])

            worksheet.cell(row=3, column=5, value="PENDÊNCIAS POR MICROBACIA").font = FONT_BOLD
            worksheet.cell(row=4, column=5, value="Microbacia").font = FONT_BOLD
            worksheet.cell(row=4, column=6, value="Mudas").font = FONT_BOLD
            for i, row in df_micro.iterrows():
                worksheet.cell(row=5 + i, column=5, value=row["Microbacia"])
                worksheet.cell(row=5 + i, column=6, value=row["Mudas Pendentes"])

            worksheet.cell(row=3, column=9, value="PENDÊNCIAS POR PROCESSO").font = FONT_BOLD
            worksheet.cell(row=4, column=9, value="Eletrônico").font = FONT_BOLD
            worksheet.cell(row=4, column=10, value="Mudas").font = FONT_BOLD
            for i, row in df_ele.iterrows():
                worksheet.cell(row=5 + i, column=9, value=row["Processo Eletrônico"])
                worksheet.cell(row=5 + i, column=10, value=row["Mudas Pendentes"])

            _style_worksheet(writer.sheets['Dados'], highlight_compensado=True)
            _style_worksheet(writer.sheets['Resumo Gerencial'], highlight_compensado=False)
    except Exception as e:
        raise RuntimeError(f"Erro ao salvar Excel: {str(e)}")


def export_pdf(path: str, records: List[Compensacao], filtros_txt: str,
               selected_cols: List[str], kpis: List[Tuple[str, Any]],
               pend_micro_sorted: List[Tuple[str, float]]):
    doc = SimpleDocTemplate(path, pagesize=landscape(A4), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
    elements = []
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.fontSize = 14
    normal_style = styles["Normal"]
    normal_style.fontSize = 9

    elements.append(Paragraph("Relatório de Compensações", title_style))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(f"<b>Filtros:</b> {filtros_txt}", normal_style))
    elements.append(Spacer(1, 10))

    kpi_data = [["Métrica", "Valor"]] + [[str(k), str(v)] for k, v in kpis]
    t_kpi = Table(kpi_data, colWidths=[200, 100])
    t_kpi.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
    ]))
    elements.append(Paragraph("<b>Resumo do Relatório:</b>", normal_style))
    elements.append(t_kpi)
    elements.append(Spacer(1, 15))

    col_map = {attr: name for name, attr in ALL_COLUMNS}
    headers = [col_map.get(c, c) for c in selected_cols]

    def wrap_text(text, limit=25):
        s = str(text)
        return s[:limit] + "..." if len(s) > limit else s

    table_data = [headers]
    raw_data = _records_to_dict_list(records, selected_cols)
    for row_dict in raw_data:
        row_vals = []
        for h in headers:
            val = row_dict.get(h, "")
            row_vals.append(wrap_text(val))
        table_data.append(row_vals)

    page_width = landscape(A4)[0] - 60
    col_width = page_width / len(headers)
    t_main = Table(table_data, colWidths=[col_width] * len(headers), repeatRows=1)
    t_main.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
    ]))

    elements.append(Paragraph("<b>Detalhamento:</b>", normal_style))
    elements.append(t_main)
    doc.build(elements)


def export_dashboard_pdf(path: str, titulo: str, kpi_lines: List[str],
                         filtros_txt: str, chart_images: List[str]):
    doc = SimpleDocTemplate(path, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    elements = []
    styles = getSampleStyleSheet()
    elements.append(Paragraph(titulo, styles["Title"]))
    elements.append(Paragraph(f"Filtros: {filtros_txt}", styles["Normal"]))
    elements.append(Spacer(1, 20))
    for line in kpi_lines:
        elements.append(Paragraph(f"• {line}", styles["Heading3"]))
    elements.append(Spacer(1, 20))
    chart_objs = []
    for img_path in chart_images:
        if os.path.exists(img_path):
            img = Image(img_path, width=350, height=250)
            chart_objs.append(img)
    if chart_objs:
        rows = []
        if len(chart_objs) >= 2:
            rows.append([chart_objs[0], chart_objs[1]])
            if len(chart_objs) > 2: rows.append([chart_objs[2], ""])
        elif len(chart_objs) == 1:
            rows.append([chart_objs[0]])
        t_charts = Table(rows)
        t_charts.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
        elements.append(t_charts)
    doc.build(elements)