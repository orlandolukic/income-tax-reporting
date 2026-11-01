"""PDF and Excel copies of a finished report result, made again on every request (POST /api/reports/export).

No browser is involved: the PDF is drawn with reportlab in the look of the web page (same colours as
web/src/style.css, Segoe UI like the page on Windows, tiles, limit bar, tables), the Excel file is written
with openpyxl. Each report type lays out its own content (`ReportType.pdf` / `ReportType.excel`); the
shared pieces are here.
"""
import time
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Table, TableStyle

# Light theme of web/src/style.css (:root).
TEXT = colors.HexColor("#1f2328")
MUTED = colors.HexColor("#6b7280")
BORDER = colors.HexColor("#d9dce1")
ACCENT = colors.HexColor("#2563eb")
WARNING = colors.HexColor("#b45309")
ERROR = colors.HexColor("#dc2626")
OK = colors.HexColor("#15803d")
OK_BG = colors.HexColor("#dcfce7")
FAIL_BG = colors.HexColor("#fee2e2")
WARN_BG = colors.HexColor("#fef3c7")
NEUTRAL_BG = colors.HexColor("#eef0f3")
SELECTED = colors.HexColor("#dbe7ff")
LEVELS = {"ok": (OK_BG, OK), "near": (WARN_BG, WARNING), "over": (FAIL_BG, ERROR)}

FONTS = Path("C:/Windows/Fonts")
FONT, BOLD = "Helvetica", "Helvetica-Bold"  # replaced by Segoe UI / Arial (they have č, ć, đ) when found


def _register_fonts() -> None:
    global FONT, BOLD
    for regular, bold in (("segoeui.ttf", "segoeuib.ttf"), ("arial.ttf", "arialbd.ttf"),
                          ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")):
        for folder in (FONTS, Path("/usr/share/fonts/truetype/dejavu")):
            if (folder / regular).is_file() and (folder / bold).is_file():
                pdfmetrics.registerFont(TTFont("UI", str(folder / regular)))
                pdfmetrics.registerFont(TTFont("UI-Bold", str(folder / bold)))
                pdfmetrics.registerFontFamily("UI", normal="UI", bold="UI-Bold", italic="UI", boldItalic="UI-Bold")
                FONT, BOLD = "UI", "UI-Bold"
                return


_register_fonts()


def style(name: str, size: float = 9.5, color=TEXT, bold: bool = False, right: bool = False, leading=None, **kw):
    return ParagraphStyle(name, fontName=BOLD if bold else FONT, fontSize=size, textColor=color,
                          leading=leading or size * 1.35, alignment=TA_RIGHT if right else 0, **kw)


H1 = style("h1", 17, bold=True, leading=21)
H2 = style("h2", 12, bold=True, spaceBefore=10, spaceAfter=6)
BODY = style("body", 9.5)
SMALL = style("small", 8.5, MUTED)
TILE_LABEL = style("tile-label", 8.5, MUTED)
TILE_VALUE = style("tile-value", 15, bold=True, leading=19)


def esc(text) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def p(text, st=BODY) -> Paragraph:
    return Paragraph(text, st)


class Meter(Flowable):
    """The limit bar of the page (.limit-meter): a grey rounded track with a coloured fill."""

    def __init__(self, percent: float, color, height: float = 2.6 * mm):
        super().__init__()
        self.percent, self.color, self.height = percent, color, height

    def wrap(self, available_width, available_height):
        self.width = available_width
        return available_width, self.height

    def draw(self):
        c, r = self.canv, self.height / 2
        c.setFillColor(NEUTRAL_BG)
        c.roundRect(0, 0, self.width, self.height, r, stroke=0, fill=1)
        fill = self.width * max(0.0, min(self.percent, 100.0)) / 100
        if fill > 0:
            c.setFillColor(self.color)
            c.roundRect(0, 0, max(fill, self.height), self.height, r, stroke=0, fill=1)


def tiles(cells: list[tuple[list, object, object]], width: float) -> Table:
    """A row of tiles (.tile): each (paragraphs, background or None, text colour or None)."""
    gap = 4 * mm
    w = (width - gap * (len(cells) - 1)) / len(cells)
    row, widths, st = [], [], [("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]
    for i, (content, bg, _fg) in enumerate(cells):
        inner = Table([[c] for c in content], colWidths=[w])
        inner.setStyle(TableStyle([
            ("ROUNDEDCORNERS", [6, 6, 6, 6]),
            ("BOX", (0, 0), (-1, -1), 0.8, BORDER if bg is None else bg),
            ("BACKGROUND", (0, 0), (-1, -1), bg or colors.white),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ]))
        row.append(inner)
        widths.append(w)
        if i < len(cells) - 1:
            row.append("")
            widths.append(gap)
    table = Table([row], colWidths=widths)
    table.setStyle(TableStyle(st))
    return table


def document(story: list, title: str, subtitle: str) -> bytes:
    """A4 portrait PDF with the page's margins feel and a footer (generated time, page numbers)."""
    buffer = BytesIO()
    made = time.strftime("%d.%m.%Y. %H:%M")

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(doc.leftMargin, 9 * mm, f"TiM ERP automatizacija · {subtitle} · izrađeno {made}")
        canvas.drawRightString(A4[0] - doc.rightMargin, 9 * mm, f"Strana {doc.page}")
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, 12.5 * mm, A4[0] - doc.rightMargin, 12.5 * mm)
        canvas.restoreState()

    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=18 * mm, title=title, author="TiM ERP automatizacija", subject=subtitle)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def content_width() -> float:
    return A4[0] - 30 * mm


def pdf(report, result: dict) -> bytes:
    return report.pdf(result)


def xlsx(report, result: dict) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    report.excel(workbook, result)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
