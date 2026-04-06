import os
from typing import List
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.compensacao import Compensacao
from app.services.coordinates import format_coordinate_pair
from app.services.plantio_service import record_plantio_items
from app.services.report_service_support import (
    build_department_header_html_lines,
    build_individual_report_rows,
)
from app.ui.components.ui_utils import resource_path


def _resolve_ficha_logo_path() -> str:
    candidate_paths = [
        resource_path("assets", "logo_prefeitura.png"),
        os.path.join(os.path.expanduser("~"), "Downloads", "logo prefeitura.png"),
        resource_path("assets", "Logo_512.png"),
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            return path
    return candidate_paths[-1]


def _build_ficha_header(styles):
    logo_path = _resolve_ficha_logo_path()
    logo = Spacer(1, 1)
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=1.55 * inch, height=0.97 * inch)

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

    department_lines = build_department_header_html_lines()
    lines = [
        Paragraph(department_lines[0], header_title),
        *[Paragraph(line, header_text) for line in department_lines[1:]],
    ]

    table = Table([[logo, lines]], colWidths=[1.7 * inch, 4.5 * inch])
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


def _build_ficha_rows(record: Compensacao, observation: str = "") -> List[List[str]]:
    return build_individual_report_rows(record, observation)


def _build_plantios_rows(record: Compensacao) -> List[List[str]]:
    rows = []
    for index, plantio in enumerate(record_plantio_items(record), start=1):
        rows.append(
            [
                str(index),
                str(plantio.endereco or ""),
                str(plantio.qtd_mudas or ""),
                format_coordinate_pair(plantio.latitude, plantio.longitude),
            ]
        )
    return rows


def export_individual_pdf(filepath: str, record: Compensacao, observation: str = ""):
    def paragraph_text(value: object) -> str:
        return escape(str(value or "")).replace("\r\n", "\n").replace("\n", "<br/>")

    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=28,
        bottomMargin=40,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "FichaMainTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        textColor=colors.HexColor("#2C3E50"),
        alignment=1,
        spaceAfter=14,
    )
    label_style = ParagraphStyle(
        "FichaLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#2C3E50"),
    )
    value_style = ParagraphStyle(
        "FichaValue",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
    )
    signature_style = ParagraphStyle(
        "FichaSignature",
        parent=styles["Normal"],
        alignment=1,
        fontSize=12,
    )
    section_title_style = ParagraphStyle(
        "FichaSectionTitle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.HexColor("#2C3E50"),
        spaceAfter=8,
    )
    signature_subtitle_style = ParagraphStyle(
        "FichaSignatureSubtitle",
        parent=styles["Normal"],
        alignment=1,
        fontSize=10,
    )

    elements = [
        *_build_ficha_header(styles),
        Paragraph("Ficha de Compensa\u00e7\u00e3o Ambiental", title_style),
        Spacer(1, 0.12 * inch),
    ]

    data = _build_ficha_rows(record, observation)
    table_rows = []
    for row in data:
        table_row = [
            Paragraph(paragraph_text(row[0]), label_style),
            Paragraph(paragraph_text(row[1]), value_style),
        ]
        table_row.append(Paragraph(paragraph_text(row[2]), label_style) if row[2] else "")
        table_row.append(Paragraph(paragraph_text(row[3]), value_style) if row[3] else "")
        table_rows.append(table_row)

    table = Table(table_rows, colWidths=[120, 150, 100, 140])
    table_style = [
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
    ]

    for row_index, row in enumerate(data):
        if row[2] == "" and row[3] == "":
            table_style.append(("SPAN", (1, row_index), (3, row_index)))
    table.setStyle(TableStyle(table_style))

    elements.append(table)

    plantio_rows = _build_plantios_rows(record)
    if plantio_rows:
        elements.append(Spacer(1, 0.18 * inch))
        elements.append(Paragraph("Plantios Cadastrados", section_title_style))
        plantio_table_rows = [
            [
                Paragraph("Plantio", label_style),
                Paragraph("Endereço", label_style),
                Paragraph("Qtd. mudas", label_style),
                Paragraph("Coordenadas", label_style),
            ]
        ]
        for plantio_row in plantio_rows:
            plantio_table_rows.append(
                [
                    Paragraph(paragraph_text(plantio_row[0]), value_style),
                    Paragraph(paragraph_text(plantio_row[1]), value_style),
                    Paragraph(paragraph_text(plantio_row[2]), value_style),
                    Paragraph(paragraph_text(plantio_row[3]), value_style),
                ]
            )

        plantio_table = Table(plantio_table_rows, colWidths=[50, 260, 90, 130])
        plantio_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ]
            )
        )
        elements.append(plantio_table)

    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Spacer(1, 1.5 * inch))
    elements.append(Paragraph("_" * 40, signature_style))
    elements.append(Paragraph("Assinatura do T\u00e9cnico Respons\u00e1vel", signature_subtitle_style))

    doc.build(elements)
