import io
import requests
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, Image
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

GREEN      = colors.HexColor("#344d47")
BLACK      = colors.HexColor("#1c1c1c")
OFF_WHITE  = colors.HexColor("#f8f8f6")
LIGHT_LINE = colors.HexColor("#e0e0dc")

def _styles():
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=18,
                         textColor=BLACK, spaceAfter=2)
    sub = ParagraphStyle("sub", fontName="Helvetica", fontSize=7,
                          textColor=GREEN, spaceAfter=0, letterSpacing=2,
                          wordWrap="CJK")
    label = ParagraphStyle("label", fontName="Helvetica", fontSize=7,
                            textColor=GREEN, spaceAfter=1, leading=10)
    value = ParagraphStyle("value", fontName="Helvetica-Bold", fontSize=9,
                            textColor=BLACK, spaceAfter=0, leading=12)
    cell  = ParagraphStyle("cell", fontName="Helvetica", fontSize=8,
                            textColor=BLACK, leading=11)
    cell_b = ParagraphStyle("cell_b", fontName="Helvetica-Bold", fontSize=8,
                             textColor=BLACK, leading=11)
    footer = ParagraphStyle("footer", fontName="Helvetica", fontSize=8,
                             textColor=colors.HexColor("#888888"))
    return h1, sub, label, value, cell, cell_b, footer

def generate_po_pdf(order_rows: list, usd_to_aud: float, po_number: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=12*mm, bottomMargin=15*mm
    )
    W = A4[0] - 30*mm
    h1, sub, label, value, cell, cell_b, footer_style = _styles()
    story = []

    # ── Logo ────────────────────────────────────────────────────────────────
    try:
        resp = requests.get(
            "https://rainco.com.au/cdn/shop/files/Dark_Slate_Green_Logo.png",
            timeout=5
        )
        logo_buf = io.BytesIO(resp.content)
        logo = Image(logo_buf, width=45*mm, height=18*mm, kind="proportional")
    except Exception:
        logo = Paragraph("RainCo", h1)

    po_title = Paragraph("PURCHASE ORDER", ParagraphStyle(
        "po", fontName="Helvetica-Bold", fontSize=20,
        textColor=GREEN, alignment=TA_RIGHT
    ))

    header_table = Table([[logo, po_title]], colWidths=[W * 0.5, W * 0.5])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",  (1, 0), (1, 0),  "RIGHT"),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=1, color=GREEN, spaceAfter=6*mm))

    # ── Info Row ─────────────────────────────────────────────────────────────
    date_str = datetime.now().strftime("%d %B %Y")
    info_data = [[
        Paragraph("PO NUMBER",  label),
        Paragraph("DATE",       label),
        Paragraph("SUPPLIER",   label),
        Paragraph("CURRENCY",   label),
    ], [
        Paragraph(po_number,    value),
        Paragraph(date_str,     value),
        Paragraph("Watersino",  value),
        Paragraph("USD",        value),
    ]]
    info_table = Table(info_data, colWidths=[W*0.25]*4)
    info_table.setStyle(TableStyle([
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ("TOPPADDING",  (0,0),(-1,-1), 2),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 6*mm))

    # ── Line Items Table ──────────────────────────────────────────────────────
    col_w = [W*0.14, W*0.44, W*0.10, W*0.16, W*0.16]
    header_row = [
        Paragraph("SKU",              cell_b),
        Paragraph("PRODUCT",          cell_b),
        Paragraph("QTY",              cell_b),
        Paragraph("UNIT COST (USD)",  cell_b),
        Paragraph("TOTAL (USD)",      cell_b),
    ]

    table_data = [header_row]
    for row in order_rows:
        sku      = str(row.get("sku", ""))
        product  = str(row.get("product", ""))
        qty      = int(row.get("rec_order", 0))
        cost     = row.get("cost_usd") or 0
        total    = row.get("order_value_usd") or (qty * cost)
        cost_str  = f"${cost:.2f}" if cost else "—"
        total_str = f"${total:,.2f}" if total else "—"
        table_data.append([
            Paragraph(sku,        cell),
            Paragraph(product,    cell),
            Paragraph(str(qty),   cell),
            Paragraph(cost_str,   cell),
            Paragraph(total_str,  cell),
        ])

    items_table = Table(table_data, colWidths=col_w, repeatRows=1)
    items_table.setStyle(TableStyle([
        # Header
        ("BACKGROUND",   (0, 0), (-1, 0),  GREEN),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0),  7.5),
        ("TOPPADDING",   (0, 0), (-1, 0),  5),
        ("BOTTOMPADDING",(0, 0), (-1, 0),  5),
        # Body rows
        ("ROWBACKGROUNDS",(0, 1),(-1,-1), [colors.white, OFF_WHITE]),
        ("FONTSIZE",     (0, 1), (-1, -1), 8),
        ("TOPPADDING",   (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 1), (-1, -1), 4),
        # Grid
        ("LINEBELOW",    (0, 0), (-1,  0), 0.5, GREEN),
        ("LINEBELOW",    (0, 1), (-1, -1), 0.3, LIGHT_LINE),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 6*mm))

    # ── Totals ────────────────────────────────────────────────────────────────
    total_usd = sum((r.get("order_value_usd") or (r.get("rec_order", 0) * (r.get("cost_usd") or 0))) for r in order_rows)
    total_aud = total_usd * usd_to_aud

    totals_data = [
        ["", "", "", Paragraph("SUBTOTAL (USD)", cell_b), Paragraph(f"${total_usd:,.2f}", cell_b)],
        ["", "", "", Paragraph(f"EXCHANGE RATE  1 USD = {usd_to_aud:.4f} AUD", ParagraphStyle(
            "ex", fontName="Helvetica", fontSize=7, textColor=colors.HexColor("#888888")
        )), ""],
        ["", "", "", Paragraph("TOTAL (AUD)", ParagraphStyle(
            "tot", fontName="Helvetica-Bold", fontSize=10, textColor=GREEN
        )), Paragraph(f"${total_aud:,.2f}", ParagraphStyle(
            "tot2", fontName="Helvetica-Bold", fontSize=10, textColor=GREEN
        ))],
    ]
    totals_table = Table(totals_data, colWidths=col_w)
    totals_table.setStyle(TableStyle([
        ("LINEABOVE",    (3, 0), (-1, 0), 0.5, LIGHT_LINE),
        ("LINEABOVE",    (3, 2), (-1, 2), 1.0, GREEN),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(totals_table)

    story.append(Spacer(1, 10*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=LIGHT_LINE))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        f"This purchase order was generated by RainCo Procurement Dashboard on {date_str}. "
        "All prices in USD unless stated otherwise.",
        footer_style
    ))

    doc.build(story)
    return buf.getvalue()
