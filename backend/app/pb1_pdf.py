"""PDF of a company's PB-1 form: the three tabs as shown in the app (values with edits and
formulas, comments, the tax-loss notice), one tab per page, A4 landscape. Built from the same
tables the API returns (build_pb1_table), so the PDF and the page always agree.

Fonts: a TrueType font with the Serbian Latin letters (č, ć, đ, š, ž) is needed; the first one
found in PDF_FONT_CANDIDATES is used (Arial on Windows, DejaVu or Liberation on Linux), or the
files given by PDF_FONT / PDF_FONT_BOLD.
"""

import io
import math
import os
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from app.logging_config import get_logger

logger = get_logger(__name__)

AMOUNT_DECIMALS = 2
THOUSANDS, DECIMAL = ".", ","  # Serbian separators, as in the app
LETTER = re.compile(r"[^\W\d_]")

PDF_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
]
FONT, FONT_BOLD = "Pb1Sans", "Pb1Sans-Bold"

# Colors of the printed form (a document, not the app's theme: always on white paper).
GRID = colors.HexColor("#c8c8c8")
HEADER_BG = colors.HexColor("#f0f0f0")
SHADED_BG = colors.HexColor("#f4f4f4")
RED = colors.HexColor("#c0392b")
MUTED = colors.HexColor("#6b6b6b")

_fonts_ready = False


def _register_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return
    candidates = list(PDF_FONT_CANDIDATES)
    if os.getenv("PDF_FONT"):
        candidates.insert(0, (os.environ["PDF_FONT"], os.getenv("PDF_FONT_BOLD", os.environ["PDF_FONT"])))
    for regular, bold in candidates:
        if Path(regular).is_file() and Path(bold).is_file():
            pdfmetrics.registerFont(TTFont(FONT, regular))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, bold))
            _fonts_ready = True
            logger.info("PDF font: %s", regular)
            return
    raise RuntimeError("No TrueType font for the PDF found (set PDF_FONT and PDF_FONT_BOLD)")


# --- numbers, as the app shows them (src/lib/excel-format.ts, simplified to the PB-1 formats) ---

def _digits(value: float, decimals: int) -> str:
    text = f"{abs(value):,.{decimals}f}"  # 1,234.56
    return text.replace(",", "\0").replace(".", DECIMAL).replace("\0", THOUSANDS)


def _general(value: float) -> str:
    if float(value).is_integer() and abs(value) < 1e11:
        return str(int(value))
    return f"{value:.10g}".replace(".", DECIMAL)


def format_value(value: object, number_format: str | None, amount: bool) -> tuple[str, bool]:
    """(text, red) of a cell value: amounts with two decimals (0 when empty), percent formats as
    percent, other numbers as in Excel's General; negative amounts red when the format says so."""
    fmt = number_format or "General"
    if amount:
        value = value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0
    if value is None:
        return "", False
    if isinstance(value, bool):
        return ("TRUE" if value else "FALSE"), False
    if not isinstance(value, (int, float)):
        return str(value), False
    if not math.isfinite(value):
        return "", False
    negative = value < 0
    red = negative and "[red]" in fmt.lower()
    if "%" in fmt:
        text = _digits(value * 100, 2 if amount else _decimals(fmt)) + "%"
    elif amount:
        text = _digits(value, AMOUNT_DECIMALS)
    elif fmt == "General":
        return _general(value), False
    else:
        text = _digits(value, _decimals(fmt))
    if negative:
        parentheses = ";" in fmt and "(" in fmt.split(";")[1]
        text = f"({text})" if parentheses else f"-{text}"
    return text, red


def _decimals(fmt: str) -> int:
    section = fmt.split(";")[0]
    match = re.search(r"\.([0#]+)", section)
    return len(match.group(1)) if match else 0


# --- tables ------------------------------------------------------------------------------

def _style(size: float, bold: bool = False, align: int = TA_LEFT, color=colors.black) -> ParagraphStyle:
    return ParagraphStyle(
        "cell", fontName=FONT_BOLD if bold else FONT, fontSize=size, leading=size * 1.2,
        alignment=align, textColor=color,
    )


def _cell_flowable(cell, column, size: float, align_end: bool, span: int = 1):
    text, red = format_value(cell.value, cell.format, cell.amount)
    number = cell.amount or isinstance(cell.value, (int, float))
    align = TA_RIGHT if align_end or number or (text and not LETTER.search(text)) else TA_LEFT
    # Line numbers are muted; a heading spanning from a line-number column is not.
    color = RED if red else (MUTED if column.narrow and span == 1 else colors.black)
    return Paragraph(escape(text), _style(size, cell.bold, align, color))


def _span(cells: dict, columns: list, index: int, text: str) -> int:
    """A long text in a line-number column covers the empty cells after it (as in the app)."""
    column = columns[index]
    if not column.narrow or len(text) <= column.width:
        return 1
    span = 1
    while index + span < len(columns):
        nxt = cells.get(columns[index + span].key)
        if nxt is not None and (nxt.amount or format_value(nxt.value, nxt.format, False)[0].strip()):
            break
        span += 1
    return span


def _table(rows, columns, widths: list[float], size: float, header: list[str] | None = None,
           extra: list | None = None) -> Table:
    """A form table. `extra`: per row, an additional last cell (the comment)."""
    data, commands = [], [
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    if header:
        data.append([Paragraph(escape(h), _style(size, True)) for h in header])
        commands += [("BACKGROUND", (0, 0), (-1, 0), HEADER_BG), ("REPEATROWS", (0, 0), (-1, 0))]
    for i, row in enumerate(rows):
        line, index = [], 0
        r = len(data)
        while index < len(columns):
            column = columns[index]
            cell = row.cells.get(column.key)
            if cell is None:
                line.append("")
                index += 1
                continue
            text = format_value(cell.value, cell.format, cell.amount)[0]
            span = _span(row.cells, columns, index, text)
            line.append(_cell_flowable(cell, column, size, span == 1 and bool(column.amount or column.narrow), span))
            if cell.fill:
                commands.append(("BACKGROUND", (index, r), (index + span - 1, r), colors.HexColor(cell.fill)))
            if span > 1:
                commands.append(("SPAN", (index, r), (index + span - 1, r)))
                line += [""] * (span - 1)
            index += span
        if extra is not None:
            line.append(extra[i])
        if row.shaded:
            commands.append(("BACKGROUND", (0, r), (-1, r), SHADED_BG))
        data.append(line)
    table = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    table.setStyle(TableStyle(commands))
    return table


def _widths(columns, total: float, extra_chars: int = 0) -> list[float]:
    # A line-number column fits two digits (with the cell padding).
    chars = [4 if c.narrow else c.width + 2 for c in columns] + ([extra_chars] if extra_chars else [])
    scale = total / sum(chars)
    return [c * scale for c in chars]


def build_pb1_pdf(tables: list, company: str, pib: str | None, year: int) -> bytes:
    """The PDF of a company's PB-1 form; `tables`: the Pb1Table of each tab, in tab order."""
    _register_fonts()
    buffer = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(
        buffer, pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"PB-1 {year} {company}", author="Income Tax Reporting",
    )
    width = page[0] - 24 * mm
    size = 7.5
    story = []
    for n, table in enumerate(tables):
        if n:
            story.append(PageBreak())
        subtitle = f"PB-1 · {table.sheet} · {year}" + (f" · PIB {pib}" if pib else "")
        story += [Paragraph(escape(company), _style(14, True)), Paragraph(escape(subtitle), _style(9, color=MUTED))]
        if table.loss is not None:
            base = format_value(table.loss.base, "#,##0.00", True)[0]
            story.append(Paragraph(
                f"<b>Gubitak!</b> Poreska osnovica {escape(base)}: porez i mesečna akontacija su 0.",
                _style(9, color=RED),
            ))
        story.append(Spacer(1, 4 * mm))

        comment_key = table.comment_column
        columns = table.columns
        comments = None
        if comment_key:
            def comment(row):
                cell = row.cells.get(comment_key)
                text = format_value(cell.value, cell.format, False)[0] if cell else ""
                return Paragraph(escape(text), _style(size))
        widths = _widths(columns, width, 24 if comment_key else 0)

        if table.head:
            head_columns = table.head_columns or columns
            used = [i for i, c in enumerate(head_columns)
                    if any((r.cells.get(c.key) and (r.cells[c.key].amount or r.cells[c.key].fill
                            or format_value(r.cells[c.key].value, r.cells[c.key].format, False)[0].strip()))
                           for r in table.head)]
            start, end = (min(used), max(used) + 1) if used else (0, len(head_columns))
            head = _table(table.head, head_columns[start:end], widths[start:end], size)
            head.hAlign = "LEFT"
            story += [_indent(head, sum(widths[:start])), Spacer(1, 3 * mm)]

        header = [c.header or "" for c in columns] if any(c.header for c in columns) else None
        if header and comment_key:
            header.append("Komentar")
        if comment_key:
            comments = [comment(r) for r in table.rows]
        main = _table(table.rows, columns, widths, size, header, comments)
        main.hAlign = "LEFT"
        story.append(main)
        if table.summary:
            summary = _table(table.summary, columns, widths, size, None,
                             [comment(r) for r in table.summary] if comment_key else None)
            summary.hAlign = "LEFT"
            story += [Spacer(1, 3 * mm), summary]
    doc.build(story)
    return buffer.getvalue()


def _indent(flowable, left: float):
    """The flowable moved right by `left` points (head table above its own columns)."""
    if left <= 0:
        return flowable
    wrapper = Table([["", flowable]], colWidths=[left, None])
    wrapper.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                 ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    wrapper.hAlign = "LEFT"
    return wrapper
