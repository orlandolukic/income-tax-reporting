"""PDF report of a company's PB-1 form: its three tabs (Poreski bilans, Uporedo, Preliminarni
rezultat) with the current values (edits and formulas), nothing else (no comments, user's rule
2026-11-15). Built from the same tables the API returns (build_pb1_table), so the report and
the page always agree; styled as a report (A4 landscape, one section per tab, running header,
"Page x of y" footer), Preliminarni rezultat laid out in cards like the page.

Fonts: a TrueType font with the Serbian Latin letters (č, ć, đ, š, ž) is needed; the first one
found in PDF_FONT_CANDIDATES is used (Segoe UI or Arial on Windows, DejaVu or Liberation on
Linux), or the files given by PDF_FONT / PDF_FONT_BOLD.
"""

import io
import math
import os
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.logging_config import get_logger

logger = get_logger(__name__)

AMOUNT_DECIMALS = 2
THOUSANDS, DECIMAL = ".", ","  # Serbian separators, as in the app
LETTER = re.compile(r"[^\W\d_]")
APP_NAME = "Izveštavanje o porezu na dobit"

PDF_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
]
FONT, FONT_BOLD = "Pb1Sans", "Pb1Sans-Bold"

# Colors of the printed report (a document on white paper, not the app's theme).
INK = colors.HexColor("#18181b")
TEXT = colors.HexColor("#27272a")
MUTED = colors.HexColor("#71717a")
BORDER = colors.HexColor("#e4e4e7")
RULE = colors.HexColor("#a1a1aa")
TINT = colors.HexColor("#f4f4f5")
ACCENT = colors.HexColor("#0f766e")
ACCENT_SOFT = colors.HexColor("#f0fdfa")
ACCENT_TRACK = colors.HexColor("#d4d4d8")
DOWN = colors.HexColor("#ea580c")
RED = colors.HexColor("#dc2626")
RED_SOFT = colors.HexColor("#fef2f2")
RED_BORDER = colors.HexColor("#fecaca")
GREEN = colors.HexColor("#16a34a")
SUBTOTAL_BG = colors.HexColor("#dfe8fb")  # soft blue of the app mark: a section subtotal
LOCKED_BG = colors.HexColor("#e6e6e9")  # a fixed, computed value: darker than the section rows' TINT


def _locked(cell) -> bool:
    """A field with a fixed, computed value (formula, not editable), shown grey (user, 2026-11-25);
    not a section subtotal (own background) nor a head cell with a sheet fill."""
    return bool(getattr(cell, "formula", False)) and not getattr(cell, "subtotal", False) and not getattr(cell, "fill", None)
WHITE = colors.white

PAGE = landscape(A4)
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 14 * mm, 20 * mm, 16 * mm
BODY = 8.0  # table text size

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
    percent, other numbers as in Excel's General; every negative number red with its minus sign
    (user, 2026-11-17: a clear mark of a loss, as on the page)."""
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
    red = negative
    if "%" in fmt:
        text = _digits(value * 100, 2 if amount else _decimals(fmt)) + "%"
    elif amount:
        text = _digits(value, AMOUNT_DECIMALS)
    elif fmt == "General":
        text = _general(value)
        return (text if text.startswith("-") or not negative else f"-{text}"), red
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


# --- cells -------------------------------------------------------------------------------------

def _text(cell) -> str:
    return format_value(cell.value, cell.format, cell.amount)[0].strip() if cell is not None else ""


def _has_content(cell) -> bool:
    """A cell that shows something (a value, or an amount field shown as 0,00)."""
    return cell is not None and (cell.amount or _text(cell) != "")


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _style(size: float, bold: bool = False, align: int = TA_LEFT, color=TEXT, leading: float = 1.22,
           tracking: bool = False) -> ParagraphStyle:
    return ParagraphStyle(
        "s", fontName=FONT_BOLD if bold else FONT, fontSize=size, leading=size * leading,
        alignment=align, textColor=color, splitLongWords=True,
    )


def _para(text: str, size: float, bold: bool = False, align: int = TA_LEFT, color=TEXT) -> Paragraph:
    return Paragraph(escape(text), _style(size, bold, align, color))


def _cell_para(cell, column, size: float, *, span: int = 1, bold: bool | None = None, color=None) -> Paragraph:
    text, red = format_value(cell.value, cell.format, cell.amount)
    if getattr(column, "dash_empty", False) and cell.editable and not text.strip():
        # An empty editable Konto, as on the page (a locked cell, e.g. in a section row, stays empty).
        return Paragraph("-", _style(size, False, TA_RIGHT, MUTED))
    number = cell.amount or _number(cell.value)
    align_end = span == 1 and bool(column.amount or column.narrow)
    align = TA_RIGHT if align_end or number or (text.strip() and not LETTER.search(text)) else TA_LEFT
    if color is None:
        negative = number and _number(cell.value) and cell.value < 0
        if getattr(cell, "green", False):
            color = GREEN  # an overrun of a line with "-" in the line 59 formula
        else:
            color = RED if red or negative or getattr(cell, "red", False) else (MUTED if column.narrow and span == 1 else TEXT)
    return Paragraph(escape(text), _style(size, cell.bold if bold is None else bold, align, color))


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


class IndexCell(Flowable):
    """Index (current / previous year): a trend arrow, a small bar (100 % = half the track)
    and the value, right-aligned in its cell (as on the Uporedo page)."""

    BAR = 30.0

    def __init__(self, value: object, text: str, size: float):
        super().__init__()
        self.value, self.text, self.size = value, text, size
        self.width = 0.0

    def wrap(self, avail_width, avail_height):
        self.width = avail_width
        return avail_width, self.size * 1.22

    def draw(self):
        c, size = self.canv, self.size
        text_w = pdfmetrics.stringWidth(self.text, FONT, size)
        baseline = size * 0.22
        c.setFont(FONT, size)
        c.setFillColor(RED if _number(self.value) and self.value < 0 else TEXT)
        c.drawRightString(self.width, baseline, self.text)
        # An Index of 0 or one that can't be computed: a level arrow and an empty bar (as on the page).
        value = float(self.value) if _number(self.value) and math.isfinite(self.value) else 0.0
        mid = size * 0.55
        # The bar at the cell's left edge and the arrow right of it, so every row's marker lines
        # up (as on the page); skipped when the value leaves no room.
        left = 1.0
        h = size * 0.42
        x = left + self.BAR + 5 + h  # arrow centre
        if x + h + 4 > self.width - text_w:
            return
        # bar: track with a thin dark outline (an empty bar stays visible), fill, 100 % mark
        fill = max(0.0, min(value, 2.0)) / 2
        c.setFillColor(ACCENT_TRACK)
        c.roundRect(left, mid - 1.5, self.BAR, 3, 1.5, stroke=0, fill=1)
        if fill > 0:
            c.setFillColor(ACCENT)
            c.roundRect(left, mid - 1.5, max(3.0, self.BAR * fill), 3, 1.5, stroke=0, fill=1)
        c.setStrokeColor(TEXT)
        c.setLineWidth(0.5)
        c.roundRect(left, mid - 1.5, self.BAR, 3, 1.5, stroke=1, fill=0)
        c.setStrokeColor(MUTED)
        c.line(left + self.BAR / 2, mid - 2.5, left + self.BAR / 2, mid + 2.5)
        # arrow
        path = c.beginPath()
        if value != 0 and value > 1.0005:
            c.setFillColor(ACCENT)
            path.moveTo(x - h, mid - h / 2), path.lineTo(x + h, mid - h / 2), path.lineTo(x, mid + h / 2)
        elif value != 0 and value < 0.9995:
            c.setFillColor(DOWN)
            path.moveTo(x - h, mid + h / 2), path.lineTo(x + h, mid + h / 2), path.lineTo(x, mid - h / 2)
        else:
            c.setFillColor(MUTED)
            path.rect(x - h, mid - 0.5, 2 * h, 1)
        path.close()
        c.drawPath(path, stroke=0, fill=1)


# --- form tables (Poreski bilans, Uporedo) ------------------------------------------------------

def _form_table(rows, columns, widths: list[float], size: float, *, index_key: str | None = None,
                current_key: str | None = None) -> Table:
    """A form table: dark header row (repeated on every page), hairline rows, section rows tinted
    with an accent rule, negative amounts red. Rows without content are thin gaps.
    `index_key`: column drawn as IndexCell; `current_key`: the current year's column (tinted)."""
    header = [c.header or "" for c in columns]
    data = [[
        Paragraph(escape(h), _style(size, True, TA_RIGHT if (c.amount or c.narrow) else TA_LEFT, WHITE))
        for h, c in zip(header, columns)
    ]]
    heights: list[float | None] = [None]
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TOPPADDING", (0, 0), (-1, 0), 5), ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
    ]
    keys = [c.key for c in columns]
    subtotal_cells: list[tuple[int, int]] = []
    locked: list[tuple[int, int]] = []
    current = keys.index(current_key) if current_key in keys else None
    if current is not None:
        commands.append(("BACKGROUND", (current, 0), (current, 0), ACCENT))
    for row in rows:
        r = len(data)
        if not any(_has_content(row.cells.get(k)) for k in keys):
            data.append([""] * len(columns))
            heights.append(5)
            commands += [("TOPPADDING", (0, r), (-1, r), 0), ("BOTTOMPADDING", (0, r), (-1, r), 0)]
            continue
        line, index = [], 0
        while index < len(columns):
            column = columns[index]
            cell = row.cells.get(column.key)
            if cell is None:
                line.append("")
                index += 1
                continue
            if column.key == index_key:
                line.append(IndexCell(cell.value, format_value(cell.value, cell.format, cell.amount)[0], size))
                index += 1
                continue
            span = _span(row.cells, columns, index, _text(cell))
            if getattr(cell, "subtotal", False):
                # A section subtotal: > 0 red, < 0 green (cell flags), bold, on its own soft background.
                line.append(_cell_para(cell, column, size, span=span, bold=True))
                subtotal_cells.append((index, r))
            else:
                line.append(_cell_para(cell, column, size, span=span, bold=cell.bold or row.shaded))
                if _locked(cell):
                    locked.append((index, r))
            if span > 1:
                commands.append(("SPAN", (index, r), (index + span - 1, r)))
                line += [""] * (span - 1)
            index += span
        data.append(line)
        heights.append(None)
        commands.append(("LINEBELOW", (0, r), (-1, r), 0.35, BORDER))
        if row.shaded:
            commands += [
                ("BACKGROUND", (0, r), (-1, r), TINT),
                ("LINEBEFORE", (0, r), (0, r), 2.4, ACCENT),
                ("TOPPADDING", (0, r), (-1, r), 4), ("BOTTOMPADDING", (0, r), (-1, r), 4),
            ]
        elif current is not None:
            commands.append(("BACKGROUND", (current, r), (current, r), ACCENT_SOFT))
    commands += [("BACKGROUND", cell, cell, SUBTOTAL_BG) for cell in subtotal_cells]
    commands += [("BACKGROUND", cell, cell, LOCKED_BG) for cell in locked]
    table = Table(data, colWidths=widths, rowHeights=heights, repeatRows=1)
    table.setStyle(TableStyle(commands))
    table.hAlign = "LEFT"
    return table


def _widths(columns, total: float) -> list[float]:
    # A line-number column fits two digits (with the cell padding).
    chars = [4 if c.narrow else c.width + 2 for c in columns]
    scale = total / sum(chars)
    return [c * scale for c in chars]


def _head_figures(table) -> list[tuple[str, str, bool]]:
    """The head's labelled values, as on the page (API head_figures: Klasa 5, Klasa 6, Saldo
    (Klasa 6 - 5), Meseci poslovanja; user 2026-11-25). The title and the company name are in
    the report's header already."""
    cells = {(row.row, key): cell for row in table.head for key, cell in row.cells.items()}
    figures = []
    for figure in getattr(table, "head_figures", []):
        value = cells.get((figure.row, figure.column))
        if value is None:
            continue
        text = format_value(value.value, value.format, value.amount)[0]
        tone = getattr(value, "tone", None)
        # Klasa 5 red (expenses), Klasa 6 green (revenue), the Saldo by its sign; else red when negative.
        negative = _number(value.value) and value.value < 0
        positive = _number(value.value) and value.value > 0
        color = RED if tone == "expense" else GREEN if tone == "income" or (tone == "balance" and positive) else negative
        figures.append((figure.label, text, color))
    return figures


def _summary_figures(table) -> list[tuple[str, str, bool]]:
    """The form's closing rows with an amount (Poreska osnovica, Porez 15%, Mesecna akontacija)
    as labelled values: shown at the top with the head values (as on the page, user 2026-11-15),
    without the line number."""
    figures = []
    for row in table.summary:
        label = next((_text(row.cells.get(c.key)) for c in table.columns
                      if not c.narrow and not c.amount and _text(row.cells.get(c.key))), "")
        value = next((row.cells[c.key] for c in table.columns if c.amount and c.key in row.cells
                      and (row.cells[c.key].amount or _number(row.cells[c.key].value))), None)
        if label and value is not None:
            text = format_value(value.value, value.format, value.amount)[0]
            figures.append((label, text, _number(value.value) and value.value < 0))
    return figures


def _figure_strip(figures: list[tuple], width: float) -> Table:
    """Small labelled value tiles in a row."""
    gap = 3 * mm if len(figures) > 6 else 4 * mm
    tile_w = min(58 * mm, (width - gap * (len(figures) - 1)) / max(1, len(figures)))
    # One size for every value, the largest (up to 12 pt) at which the longest fits on one line.
    longest = max((pdfmetrics.stringWidth(f[1], FONT_BOLD, 1) for f in figures), default=1)
    value_size = max(7.0, min(12.0, (tile_w - 14 - 2) / longest))
    tiles = []
    for figure in figures:
        label, value, negative = figure[:3]
        # The third item: True (negative: red), False, or a colour of its own.
        color = negative if isinstance(negative, colors.Color) else RED if negative else INK
        content = [[_para(label, 7.2, color=MUTED)], [_para(value, value_size, True, color=color)]]
        if len(figure) > 3 and figure[3]:
            # A result's status (Dobitak / Gubitak / Nula) and its note, under the value.
            content.append([_para(figure[3], 7.2, True, color=figure[4])])
        tile = Table(content, colWidths=[tile_w])
        tile.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER), ("ROUNDEDCORNERS", [4, 4, 4, 4]),
            ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, 0), 5), ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
            ("TOPPADDING", (0, 1), (-1, 1), 0), ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ]))
        tiles.append(tile)
    cells, widths = [], []
    for n, tile in enumerate(tiles):
        if n:
            cells.append("")
            widths.append(gap)
        cells.append(tile)
        widths.append(tile_w)
    strip = Table([cells], colWidths=widths)
    strip.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    strip.hAlign = "LEFT"
    return strip


# --- Preliminarni rezultat: cards, as on the page ------------------------------------------------

def _card(title: str, groups: list[list], keys: list[str], columns: dict, width: float, size: float,
          header: list[str] | None = None, is_total: Callable | None = None) -> Table:
    """A card: title bar, optional column header, rows; groups separated by a line."""
    widths = [7 * mm, width - 7 * mm - 27 * mm, 27 * mm]
    data = [[_para(title, size + 1, True, color=INK), "", ""]]
    commands = [
        ("SPAN", (0, 0), (-1, 0)), ("BACKGROUND", (0, 0), (-1, 0), TINT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, BORDER),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER), ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.0),
        ("LEFTPADDING", (0, 0), (-1, 0), 7), ("TOPPADDING", (0, 0), (-1, 0), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4.5),
    ]
    locked: list[tuple[int, int]] = []
    if header:
        data.append([_para(h, size - 0.8, True, TA_RIGHT if i != 1 else TA_LEFT, MUTED) for i, h in enumerate(header)])
        commands.append(("LINEBELOW", (0, 1), (-1, 1), 0.6, BORDER))
    for g, rows in enumerate(groups):
        for i, row in enumerate(rows):
            r = len(data)
            total = is_total(row) if is_total else row.shaded
            line = []
            for n, key in enumerate(keys):
                cell = row.cells.get(key)
                if cell is None:
                    line.append("")
                    continue
                column = columns[key]
                line.append(_cell_para(cell, column, size, bold=cell.bold or total))
                if _locked(cell):
                    locked.append((n, r))
            data.append(line)
            if total:
                commands += [("BACKGROUND", (0, r), (-1, r), TINT), ("LINEBEFORE", (0, r), (0, r), 2.4, ACCENT)]
            if g > 0 and i == 0:
                commands.append(("LINEABOVE", (0, r), (-1, r), 1.1, RULE))
            elif r > (2 if header else 1):
                commands.append(("LINEABOVE", (0, r), (-1, r), 0.35, BORDER))
    commands += [("BACKGROUND", cell, cell, LOCKED_BG) for cell in locked]
    card = Table(data, colWidths=widths)
    card.setStyle(TableStyle(commands))
    return card


def _preliminary(table, width: float, avail_height: float) -> list:
    """Preliminarni rezultat as on the page: left the main calculation with the sections below the
    two tables stacked under it, right one card per section heading of the right table."""
    keys = [c.key for c in table.columns]
    if len(keys) != 7:
        return [_form_table(table.rows, table.columns, _widths(table.columns, width), BODY)]
    a, b, c, _, e, f, g = keys
    columns = {col.key: col for col in table.columns}
    left, right = [a, b, c], [e, f, g]
    rows = table.rows
    has = lambda row, ks: any(_has_content(row.cells.get(k)) for k in ks)  # noqa: E731
    last_right = max((r.row for r in rows if has(r, right)), default=0)

    left_rows = [r for r in rows if r.row <= last_right and has(r, left)]
    title_row = next((r for r in left_rows if not _has_content(r.cells.get(a)) and _has_content(r.cells.get(b))
                      and not _has_content(r.cells.get(c))), None)
    header_row = next((r for r in left_rows if _text(r.cells.get(a)) == "#"), None)
    left_body = [r for r in left_rows if r is not title_row and r is not header_row]

    sections: list[tuple[str, list[list]]] = []
    for row in rows:
        if not has(row, right):
            continue
        heading = _text(row.cells.get(e))
        if len(heading) > 4 and not _has_content(row.cells.get(f)) and not _has_content(row.cells.get(g)):
            sections.append((heading, [[]]))
            continue
        if not sections:
            sections.append(("", [[]]))
        groups = sections[-1][1]
        if heading == "1" and groups[-1]:
            groups.append([row])
        else:
            groups[-1].append(row)

    lower: list[tuple[str, list[list]]] = []
    for row in rows:
        if row.row <= last_right or not has(row, left):
            continue
        cell_c = row.cells.get(c)
        if _has_content(row.cells.get(b)) and not _has_content(row.cells.get(a)) and not (cell_c and cell_c.amount) \
                and not _has_content(cell_c):
            lower.append((_text(row.cells.get(b)), [[]]))
        elif _has_content(row.cells.get(a)) or _has_content(row.cells.get(b)):
            if not lower:
                lower.append(("", [[]]))
            lower[-1][1][0].append(row)

    is_total = lambda row: bool(re.match(r"ukupno\b", _text(row.cells.get(f)), re.I))  # noqa: E731
    header = [_text(header_row.cells.get(k)) for k in left] if header_row else None
    gap = 6 * mm
    col_w = (width - gap) / 2

    def cards(width_: float):
        left_cards = [_card(_text(title_row.cells.get(b)) if title_row else table.sheet, [left_body], left,
                            columns, width_, 7.6, header)]
        left_cards += [_card(t, [gr for gr in groups if gr], left, columns, width_, 7.6) for t, groups in lower]
        right_cards = [_card(t, [gr for gr in groups if gr], right, columns, width_, 7.6, is_total=is_total)
                       for t, groups in sections]
        return left_cards, right_cards

    left_cards, right_cards = cards(col_w)

    def column(flowables: list) -> list:
        out = []
        for n, card in enumerate(flowables):
            if n:
                out.append(Spacer(1, 4 * mm))
            out.append(card)
        return out

    layout = Table([[column(left_cards), "", column(right_cards)]], colWidths=[col_w, gap, col_w])
    layout.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    layout.hAlign = "LEFT"
    if layout.wrap(width, avail_height)[1] <= avail_height:
        return [layout]
    # Too tall for one page side by side: the cards one under the other, full width.
    logger.info("PB-1 PDF: Preliminarni rezultat stacked (too tall for two columns)")
    stacked_left, stacked_right = cards(width)
    return column(stacked_left + stacked_right)


# --- the report --------------------------------------------------------------------------------

def _section_header(number: int, title: str, width: float) -> Table:
    badge = Paragraph(f"{number:02d}", _style(10, True, TA_LEFT, WHITE))
    head = Table([[badge, _para(title, 15, True, color=INK)]], colWidths=[10 * mm, width - 10 * mm])
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (0, 0), ACCENT), ("ROUNDEDCORNERS", [3, 3, 3, 3]),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("LEFTPADDING", (0, 0), (0, 0), 6), ("LEFTPADDING", (1, 0), (1, 0), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    head.hAlign = "LEFT"
    return head


RESULT_STATUS = {"profit": ("Dobitak", GREEN), "loss": ("Gubitak", RED), "zero": ("Nula", MUTED)}


def _result_figures(results) -> list[tuple]:
    """The accounting and the tax result as tiles (as on the page, user 2026-11-25): the
    accounting result (the balance 6 - 5) with its status, green above 0, red below; the tax
    result without status or colour (a loss only notes that tax and advance are 0)."""
    accounting = results.accounting
    status, color = RESULT_STATUS[accounting.status]
    value_color = GREEN if accounting.value > 0 else RED if accounting.value < 0 else INK
    figures = [("Knjigovodstveni rezultat (6 - 5)", format_value(accounting.value, "#,##0.00", True)[0],
                value_color, status, color)]
    tax = results.tax
    note = "Porez i akontacija su 0." if tax.status == "loss" else ""
    figures.append(("Poreski rezultat (poreska osnovica)", format_value(tax.value, "#,##0.00", True)[0], INK, note, MUTED))
    return figures


def _result_section(figures: list[tuple], width: float) -> Table:
    """The closing rows and the two results as one framed section (user, 2026-11-17)."""
    pad = 6
    box = Table([[_figure_strip(figures, width - 2 * pad)]], colWidths=[width])
    box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, RULE), ("ROUNDEDCORNERS", [5, 5, 5, 5]),
        ("LEFTPADDING", (0, 0), (-1, -1), pad), ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
    ]))
    box.hAlign = "LEFT"
    return box


def _canvas_class(footer_left: str):
    """A canvas that writes "Page x of y" once the page count is known."""

    class NumberedCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                width = PAGE[0]
                self.setStrokeColor(BORDER)
                self.setLineWidth(0.6)
                self.line(MARGIN_X, 11 * mm, width - MARGIN_X, 11 * mm)
                self.setFont(FONT, 7.5)
                self.setFillColor(MUTED)
                self.drawString(MARGIN_X, 7 * mm, footer_left)
                self.drawRightString(width - MARGIN_X, 7 * mm, f"Strana {self._pageNumber} od {total}")
                super().showPage()
            super().save()

    return NumberedCanvas


def build_pb1_pdf(tables: list, company: str, pib: str | None, year: int, report: str = "preliminary") -> bytes:
    """The PDF report of a company's PB-1 form; `tables`: the Pb1Table of each tab, in tab order;
    `report`: which of the company's two reports (preliminary, final) it is."""
    kind = "Konačni" if report == "final" else "Preliminarni"
    _register_fonts()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=PAGE, leftMargin=MARGIN_X, rightMargin=MARGIN_X, topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM, title=f"PB-1 {year} {company} ({kind.lower()})", author=APP_NAME,
        subject=f"PB-1 {year}", creator=APP_NAME,
    )
    width = doc.width
    frame_height = doc.height
    running = f"PB-1 · {kind} · {year} · {company}"
    # A submitted report says when (user, 2026-11-17).
    submitted_at = getattr(tables[0], "submitted_at", None) if tables else None
    submitted = (
        f" &nbsp;·&nbsp; Predato {submitted_at.astimezone().strftime('%d.%m.%Y. %H:%M')}" if submitted_at else ""
    )

    def decorate(c, _doc):
        c.saveState()
        top = PAGE[1] - 10 * mm
        c.setFont(FONT_BOLD, 7.5)
        c.setFillColor(ACCENT)
        c.drawString(MARGIN_X, top, APP_NAME.upper())
        c.setFont(FONT, 7.5)
        c.setFillColor(MUTED)
        c.drawRightString(PAGE[0] - MARGIN_X, top, running)
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.6)
        c.line(MARGIN_X, top - 3 * mm, PAGE[0] - MARGIN_X, top - 3 * mm)
        c.restoreState()

    story: list = [
        _para(company, 22, True, color=INK),
        Spacer(1, 1.5 * mm),
        Paragraph(
            f"{kind} PB-1 izveštaj &nbsp;·&nbsp; {year} &nbsp;·&nbsp; PIB {escape(pib or '-')}{submitted}",
            _style(10, color=MUTED),
        ),
        Spacer(1, 5 * mm),
    ]
    # No "Gubitak!" box at the top any more: the tax result (with its loss note) is shown with
    # the closing rows of Poreski bilans (user, 2026-11-17).

    for n, table in enumerate(tables, start=1):
        if n > 1:
            story.append(PageBreak())
        header = _section_header(n, table.sheet, width)
        story += [header, Spacer(1, 4 * mm)]
        if table.tab == "preliminarni":
            # On one page with its section header when the two columns fit (the frame's own
            # padding, 6 pt at the top and bottom, included).
            used = header.wrap(width, frame_height)[1] + 4 * mm + 12 + 1
            story += _preliminary(table, width, frame_height - used)
            continue
        if table.head:
            story += [_figure_strip(_head_figures(table), width), Spacer(1, 3 * mm)]
        section = _summary_figures(table)
        if section and table.results is not None:
            # The closing rows with the accounting and tax result: one section, as on the page.
            # As on the page (user, 2026-11-25): the accounting result, the tax result (= the tax
            # base, not written a second time), then Porez 15% and Mesecna akontacija.
            story += [_result_section(_result_figures(table.results) + section[1:], width), Spacer(1, 4 * mm)]
        elif section:
            story += [_figure_strip(section, width), Spacer(1, 4 * mm)]
        columns = table.columns  # the comment column is not one of them: comments are left out
        if table.tab == "uporedo" and len(columns) == 5:
            widths = [10 * mm, width - 10 * mm - 2 * 40 * mm - 50 * mm, 40 * mm, 40 * mm, 50 * mm]
            story.append(_form_table(table.rows, columns, widths, BODY + 0.5,
                                     index_key=columns[4].key, current_key=columns[2].key))
        else:
            widths = _widths(columns, width)
            story.append(_form_table(table.rows, columns, widths, BODY))

    generated = datetime.now().strftime("%d.%m.%Y. %H:%M")
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate,
              canvasmaker=_canvas_class(f"{APP_NAME} · {running} · Napravljen {generated}"))
    return buffer.getvalue()
