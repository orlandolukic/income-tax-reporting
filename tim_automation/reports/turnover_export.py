"""PDF and Excel layout of "Promet u poslednjih 12 meseci", following the page (web/src/reports/TurnoverView.tsx):
summary tiles, limit bar, the month table with the running total, notes, then each month's konta and, if they were
read (setting "Pojedinačni iznosi po kontu"), each konto's individual entries."""
import time

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Spacer, Table, TableStyle

from tim_automation.pages.app_page import format_amount, normalize
from tim_automation.reports import export as x
from tim_automation.reports.export import esc, p
from tim_automation.reports.turnover import BEZ_RACUNA, item_columns, item_konta, mismatch_note

STATUS = {"done": "Završen", "failed": "Greška", "cancelled": "Zaustavljen", "running": "U izradi"}


def _level(value: dict) -> str:
    return "over" if value["prekoracen"] else "near" if value["procenat"] >= 80 else "ok"


def _amount(n) -> str:
    return format_amount(n) if n is not None else ""


def _dots(date: str) -> str:
    return date.replace("/", ".") + "."


def _percent(value: dict) -> str:
    return f"{value['procenat']:.1f}".replace(".", ",")


def _period(value: dict) -> str:
    months = value["meseci"]
    return f"{months[0]['naziv']} – {months[-1]['naziv']}" if months else ""


def _base(m: dict):
    """A month's (or the total's) amount on all konta: "osnova" (older results: Potražuje)."""
    return m.get("osnova", m.get("potrazuje"))


def _column(value: dict) -> str:
    return value.get("kolona", "Potražuje 6–7")


def _excluded(value: dict) -> list[str]:
    return value.get("izuzeta", [value["izuzet_konto"]] if value.get("izuzet_konto") else [])


def _is_excluded(value: dict, konto: str) -> bool:
    return any(konto.startswith(k) for k in _excluded(value))


def _excluded_header(value: dict) -> str:
    return f"Konto {value['izuzet_konto']} (izuzeto)" if _excluded(value) else "Izuzeto"


def _tile_label(value: dict) -> str:
    return f"Promet u poslednjih {value.get('broj_meseci', len(value['meseci']))} meseci"


def _description(value: dict) -> str:
    konta = f"{value.get('konto_od', '6')}–{value.get('konto_do', '7')}"
    text = (f"Promet za limit iz Zakona o PDV ({_amount(value['limit'])} RSD), po mesecima: {value.get('iznos', 'Potražuje')} "
            f"na kontima {konta} iz popisa salda analitike (sintetika)")
    return text + (f", bez konta {value['izuzet_konto']}." if _excluded(value) else ".")


def _company(result: dict) -> str:
    parts = [f"Firma: <b>{esc(result.get('firma') or '')}</b>"]
    if result.get("pib"):
        parts.append(f"PIB {esc(result['pib'])}")
    return " · ".join(parts)


# --- PDF -----------------------------------------------------------------------------------------


def pdf(result: dict) -> bytes:
    value = result["value"]
    width = x.content_width()
    level = _level(value)
    bg, fg = x.LEVELS[level]
    total = value["ukupno"]
    started = time.strftime("%d.%m.%Y. %H:%M", time.localtime(result["started_at"]))
    story = [
        p("TiM ERP · Izveštaji", x.SMALL),
        Spacer(0, 2 * mm),
        p(esc(result["title"]), x.H1),
        Spacer(0, 1.5 * mm),
        p(f"{_company(result)} · izveštaj od {started} · {STATUS.get(result['status'], result['status'])}",
          x.style("meta", 9, x.MUTED)),
        Spacer(0, 1 * mm),
        p(esc(_description(value)), x.style("desc", 9, x.MUTED)),
        Spacer(0, 5 * mm),
    ]
    if result.get("error"):
        story += [p(esc(result["error"]), x.style("err", 9.5, x.ERROR)), Spacer(0, 3 * mm)]
    sub = _period(value) + ("" if value["potpun"] else f" · pročitano {total['meseci']} od {len(value['meseci'])} meseci")
    story.append(x.tiles([
        ([p(_tile_label(value), x.TILE_LABEL), p(f"{_amount(total['promet'])} RSD", x.TILE_VALUE),
          p(esc(sub), x.SMALL)], None, None),
        ([p("Limit (Zakon o PDV)", x.TILE_LABEL), p(f"{_amount(value['limit'])} RSD", x.TILE_VALUE)], None, None),
        ([p("Prekoračeno za" if value["prekoracen"] else "Preostalo do limita", x.style("l", 8.5, fg)),
          p(f"{_amount(abs(value['preostalo']))} RSD", x.style("v", 15, fg, bold=True, leading=19)),
          p(f"{_percent(value)} % limita", x.style("s", 8.5, fg))], bg, fg),
    ], width))
    story += [Spacer(0, 4 * mm), x.Meter(value["procenat"], fg), Spacer(0, 4 * mm)]
    if not value["potpun"]:
        story += [p("Nisu pročitani svi meseci: ukupan promet je nepotpun (vidi napomene).", x.style("w", 9, x.WARNING)),
                  Spacer(0, 2 * mm)]
    story.append(_months_table(value, width))
    story.append(Spacer(0, 4 * mm))
    for i, note in enumerate(value["napomene"]):
        story.append(p(f"•&nbsp;&nbsp;{esc(note)}", x.style(f"n{i}", 8.5, x.WARNING if i == 0 else x.MUTED,
                                                           leftIndent=9, firstLineIndent=-9, spaceAfter=2)))
    konta = [m for m in value["meseci"] if m["konta"]]
    if konta:
        story += [Spacer(0, 3 * mm), p("Konta po mesecima", x.H2)]
        story += [_konta_table(m, value, width) for m in konta]
    if value.get("po_klijentima"):
        story += [Spacer(0, 3 * mm), p("Promet po klijentima", x.H2),
                  p(f"{len(value.get('racuni') or [])} izlaznih računa veleprodaje; stavke kartica su povezane sa računima "
                    "preko broja finansijskog naloga.", x.SMALL), Spacer(0, 2 * mm), _clients_table(value, width)]
    items = item_konta(value)
    if items:
        story += [Spacer(0, 3 * mm), p("Pojedinačni iznosi po kontu", x.H2)]
        story += [_items_table(m, k, width) for m, k in items]
    return x.document(story, result["title"], f"{result.get('firma', '')} · {_period(value)}")


def _months_table(value: dict, width: float) -> Table:
    excluded = value["izuzet_konto"]
    head = x.style("th", 8.5, bold=True)
    head_r = x.style("thr", 8.5, bold=True, right=True)
    cell = x.style("td", 9)
    right = x.style("tdr", 9, right=True)
    rows = [[p("Mesec", head), p("Period", head), p(esc(_column(value)), head_r), p(esc(_excluded_header(value)), head_r),
             p("Promet", head_r), p("Kumulativno", head_r)]]
    commands = [
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, x.BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.8, x.BORDER),
        ("ROUNDEDCORNERS", [5, 5, 5, 5]),
    ]
    cumulative = 0.0
    for m in value["meseci"]:
        r = len(rows)
        period = p(f"{_dots(m['od'])} – {_dots(m['do'])}", x.style("per", 8, x.MUTED))
        if m["status"] == "ok":
            cumulative += m["promet"]
            rows.append([p(esc(m["naziv"]), cell), period, p(_amount(_base(m)), right),
                         p(_amount(m["izuzeto"]), x.style("ex", 9, x.WARNING if m["izuzeto"] else x.MUTED, right=True)),
                         p(_amount(m["promet"]), x.style("pr", 9, bold=True, right=True)),
                         p(_amount(cumulative), x.style("cu", 9, x.MUTED, right=True))])
        else:
            text = f"Nije pročitano: {esc(m['napomena'])}" if m["status"] == "nedostupno" else "nije pročitano"
            rows.append([p(esc(m["naziv"]), cell), period,
                         p(text, x.style("na", 8.5, x.WARNING if m["status"] == "nedostupno" else x.MUTED)), "", "", ""])
            commands.append(("SPAN", (2, r), (5, r)))
        commands.append(("LINEABOVE", (0, r), (-1, r), 0.5, x.BORDER))
    t = value["ukupno"]
    total = x.style("tot", 9.5, bold=True, right=True)
    rows.append([p("Ukupno", x.style("totl", 9.5, bold=True)), "", p(_amount(_base(t)), total),
                 p(_amount(t["izuzeto"]), total), p(_amount(t["promet"]), total), ""])
    commands += [("LINEABOVE", (0, -1), (-1, -1), 1, x.BORDER), ("SPAN", (0, -1), (1, -1)),
                 ("TOPPADDING", (0, -1), (-1, -1), 6), ("BOTTOMPADDING", (0, -1), (-1, -1), 6)]
    widths = [w * mm for w in (31, 40, 28, 31, 25, 25)]
    scale = width / sum(widths)
    table = Table(rows, colWidths=[w * scale for w in widths], repeatRows=1)
    table.setStyle(TableStyle(commands))
    return table


def _konta_table(m: dict, value: dict, width: float):
    excluded = value["izuzet_konto"]
    head = x.style("kh", 8, x.TEXT, bold=True)
    head_r = x.style("khr", 8, x.TEXT, bold=True, right=True)
    rows = [[p(esc(m["naziv"]), x.style("km", 9, bold=True)), "", "", ""],
            [p("Konto", head), p("Naziv", head), p("Duguje", head_r), p("Potražuje", head_r)]]
    commands = [
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, -1), x.NEUTRAL_BG),
        ("LINEBELOW", (0, 1), (-1, 1), 0.5, x.BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("ROUNDEDCORNERS", [5, 5, 5, 5]),
    ]
    for k in m["konta"]:
        out = _is_excluded(value, k["konto"])
        color = x.WARNING if out else x.TEXT
        name = esc(k["naziv"]) + ("&nbsp;&nbsp;<font size='7'>[izuzeto]</font>" if out else "")
        rows.append([p(esc(k["konto"]), x.style("kk", 8.5, color)), p(name, x.style("kn", 8.5, color)),
                     p(_amount(k["duguje"]), x.style("kd", 8.5, color, right=True)),
                     p(_amount(k["potrazuje"]), x.style("kp", 8.5, color, right=True))])
        commands.append(("LINEABOVE", (0, len(rows) - 1), (-1, len(rows) - 1), 0.3, x.BORDER))
    if m["konta_potpuna"] is False:
        rows.append([p(f"Tabela na sajtu nije prikazala sva konta; izuzeta konta ({excluded}) su pročitana posebnom pretragom.",
                       x.style("kx", 7.5, x.MUTED)), "", "", ""])
        commands.append(("SPAN", (0, len(rows) - 1), (-1, len(rows) - 1)))
    table = Table(rows, colWidths=[22 * mm, width - 22 * mm - 56 * mm, 28 * mm, 28 * mm])
    table.setStyle(TableStyle(commands))
    return KeepTogether([table, Spacer(0, 3 * mm)])


def _amount_column(st: dict, column: str) -> bool:
    return column in (st.get("kolona_duguje"), st.get("kolona_potrazuje")) or \
        any(w in normalize(column) for w in ("saldo", "iznos", "duguje", "potrazuje"))


def _items(n: int) -> str:
    """"1 stavka", "3 stavke", "5 stavki" (Serbian plural)."""
    last, last_two = n % 10, n % 100
    word = "stavka" if last == 1 and last_two != 11 else "stavke" if 2 <= last <= 4 and not 12 <= last_two <= 14 else "stavki"
    return f"{n} {word}"


def _items_table(m: dict, k: dict, width: float):
    st = k["stavke"]
    title = f"{esc(m['naziv'])} · konto {esc(k['konto'])} – {esc(k['naziv'])}"
    if st.get("greska"):
        return KeepTogether([p(title, x.style("ih", 9, bold=True)), p(esc(st["greska"]), x.style("ie", 8, x.ERROR)),
                             Spacer(0, 3 * mm)])
    columns = st["kolone"]
    amounts = [c for c in columns if _amount_column(st, c)]
    amount_w = 24 * mm
    other_w = (width - amount_w * len(amounts)) / max(len(columns) - len(amounts), 1)
    head = x.style("ich", 7.5, x.TEXT, bold=True)
    head_r = x.style("icr", 7.5, x.TEXT, bold=True, right=True)
    cell = x.style("ic", 7.5)
    cell_r = x.style("ir", 7.5, right=True)
    summary = (f"{_items(st['broj'])} · duguje {_amount(st['duguje'])} · potražuje {_amount(st['potrazuje'])}"
               + (f" · van meseca izostavljeno: {_items(st['van_perioda'])}" if st["van_perioda"] else ""))
    rows = [[p(f"{title}&nbsp;&nbsp;<font size='7.5' color='#6b7280'>{esc(summary)}</font>", x.style("ih", 8.5, bold=True))]
            + [""] * (len(columns) - 1),
            [p(esc(c), head_r if c in amounts else head) for c in columns]]
    for r in st["redovi"]:
        rows.append([p(esc(r["kolone"].get(c, "")), cell_r if c in amounts else cell) for c in columns])
    commands = [
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 1), x.NEUTRAL_BG),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, x.BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
    ]
    if not st["slaze"]:
        rows.append([p(esc(mismatch_note(k)), x.style("iw", 7.5, x.WARNING))] + [""] * (len(columns) - 1))
        commands.append(("SPAN", (0, len(rows) - 1), (-1, len(rows) - 1)))
    table = Table(rows, colWidths=[amount_w if c in amounts else other_w for c in columns], repeatRows=2)
    table.setStyle(TableStyle(commands))
    return KeepTogether([table, Spacer(0, 3 * mm)]) if len(rows) < 25 else table


# --- Excel ---------------------------------------------------------------------------------------


def excel(workbook, result: dict) -> None:
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    value = result["value"]
    excluded = value["izuzet_konto"]
    hexc = lambda c: c.hexval()[2:].upper()  # reportlab colour -> "RRGGBB"
    fill = lambda c: PatternFill("solid", fgColor=hexc(c))
    font = lambda **kw: Font(name="Segoe UI", size=kw.pop("size", 10), **kw)
    thin = Side(style="thin", color=hexc(x.BORDER))
    money = "#,##0.00"
    level_bg, level_fg = x.LEVELS[_level(value)]

    ws = workbook.active
    ws.title = "Promet"
    ws.sheet_view.showGridLines = False
    started = time.strftime("%d.%m.%Y. %H:%M", time.localtime(result["started_at"]))
    ws["A1"] = result["title"]
    ws["A1"].font = font(size=16, bold=True)
    ws["A2"] = " · ".join(filter(None, [f"Firma: {result.get('firma', '')}",
                                        f"PIB {result['pib']}" if result.get("pib") else "",
                                        f"izveštaj od {started}", STATUS.get(result["status"], result["status"])]))
    ws["A2"].font = font(color=hexc(x.MUTED))
    ws["A3"] = f"Period: {_period(value)} · {_description(value)}"
    ws["A3"].font = font(color=hexc(x.MUTED))
    row = 4
    if result.get("error"):
        ws.cell(row, 1, result["error"]).font = font(color=hexc(x.ERROR))
        row += 1

    # Months table first (the summary refers to its total row).
    head_row = row + 6
    first = head_row + 1
    last = first + len(value["meseci"]) - 1
    total_row = last + 1
    headers = ["Mesec", "Period", _column(value), _excluded_header(value), "Promet", "Kumulativno", "Napomena"]
    for c, h in enumerate(headers, 1):
        cell = ws.cell(head_row, c, h)
        cell.font = font(bold=True)
        cell.fill = fill(x.NEUTRAL_BG)
        cell.border = Border(top=thin, bottom=thin)
        cell.alignment = Alignment(horizontal="right" if 3 <= c <= 6 else "left", vertical="center")
    for i, m in enumerate(value["meseci"]):
        r = first + i
        ws.cell(r, 1, m["naziv"])
        ws.cell(r, 2, f"{_dots(m['od'])} – {_dots(m['do'])}").font = font(color=hexc(x.MUTED), size=9)
        if m["status"] == "ok":
            ws.cell(r, 3, _base(m))
            ws.cell(r, 4, m["izuzeto"]).font = font(color=hexc(x.WARNING if m["izuzeto"] else x.MUTED))
            ws.cell(r, 5, f"=C{r}-D{r}").font = font(bold=True)
            ws.cell(r, 6, f"=SUM(E${first}:E{r})").font = font(color=hexc(x.MUTED))
            if m["napomena"]:
                ws.cell(r, 7, m["napomena"]).font = font(color=hexc(x.WARNING))
        else:
            text = f"Nije pročitano: {m['napomena']}" if m["status"] == "nedostupno" else "Nije pročitano"
            ws.cell(r, 7, text).font = font(color=hexc(x.WARNING))
        for c in range(1, 8):
            ws.cell(r, c).border = Border(bottom=thin)
            if 3 <= c <= 6:
                ws.cell(r, c).number_format = money
    ws.cell(total_row, 1, "Ukupno")
    for c, col in ((3, "C"), (4, "D"), (5, "E")):
        ws.cell(total_row, c, f"=SUM({col}{first}:{col}{last})").number_format = money
    for c in range(1, 8):
        ws.cell(total_row, c).font = font(bold=True)
        ws.cell(total_row, c).border = Border(top=Side(style="medium", color=hexc(x.BORDER)))

    # Summary "tiles" above the table, with formulas on the table.
    summary = [
        (_tile_label(value), f"=E{total_row}", money, None, None),
        ("Limit (Zakon o PDV)", value["limit"], money, None, None),
        ("Preostalo do limita (minus = prekoračeno)", f"=B{row + 2}-B{row + 1}", money, level_bg, level_fg),
        ("% limita", f"=B{row + 1}/B{row + 2}", "0.0%", level_bg, level_fg),
    ]
    for i, (label, formula, fmt, bg, fg) in enumerate(summary):
        r = row + 1 + i
        a, b = ws.cell(r, 1, label), ws.cell(r, 2, formula)
        a.font = font(color=hexc(fg or x.MUTED))
        b.font = font(size=12, bold=True, color=hexc(fg or x.TEXT))
        b.number_format = fmt
        b.alignment = Alignment(horizontal="right")
        for cell in (a, b):
            cell.border = Border(top=thin, bottom=thin, left=thin if cell is a else None, right=thin if cell is b else None)
            if bg is not None:
                cell.fill = fill(bg)
    if not value["potpun"]:
        ws.cell(row + 5, 1, "Nisu pročitani svi meseci: ukupan promet je nepotpun (vidi napomene).").font = \
            font(color=hexc(x.WARNING))

    r = total_row + 2
    for i, note in enumerate(value["napomene"]):
        ws.cell(r + i, 1, f"• {note}").font = font(size=9, color=hexc(x.WARNING if i == 0 else x.MUTED))
    for col, w in zip("ABCDEFG", (34, 26, 17, 22, 17, 17, 50)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = ws.cell(first, 1)
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    # Every month's konta.
    kt = workbook.create_sheet("Konta")
    kt.sheet_view.showGridLines = False
    for c, h in enumerate(["Mesec", "Konto", "Naziv", "Duguje", "Potražuje", "Izuzeto (izvoz)"], 1):
        cell = kt.cell(1, c, h)
        cell.font = font(bold=True)
        cell.fill = fill(x.NEUTRAL_BG)
        cell.border = Border(bottom=thin)
    r = 2
    for m in value["meseci"]:
        for k in m["konta"]:
            out = _is_excluded(value, k["konto"])
            values = [m["naziv"], k["konto"], k["naziv"], k["duguje"], k["potrazuje"], "da" if out else ""]
            for c, v in enumerate(values, 1):
                cell = kt.cell(r, c, v)
                cell.font = font(color=hexc(x.WARNING if out else x.TEXT))
                cell.border = Border(bottom=thin)
                if c in (4, 5):
                    cell.number_format = money
            r += 1
    for col, w in zip("ABCDEF", (18, 10, 40, 16, 16, 16)):
        kt.column_dimensions[col].width = w
    if r > 2:
        kt.auto_filter.ref = f"A1:{get_column_letter(6)}{r - 1}"
    kt.freeze_panes = "A2"
    kt.page_setup.fitToWidth, kt.page_setup.fitToHeight = 1, 0
    kt.sheet_properties.pageSetUpPr.fitToPage = True

    _client_sheets(workbook, value)
    # Every konto's individual entries (setting "Pojedinačni iznosi po kontu").
    items = item_konta(value)
    if not items:
        return
    columns = item_columns(value)
    it = workbook.create_sheet("Stavke")
    it.sheet_view.showGridLines = False
    headers = ["Mesec", "Konto", *columns, "Iznos", "Napomena"]
    for c, h in enumerate(headers, 1):
        cell = it.cell(1, c, h)
        cell.font = font(bold=True)
        cell.fill = fill(x.NEUTRAL_BG)
        cell.border = Border(bottom=thin)
    r = 2
    for m, k in items:
        st = k["stavke"]
        lines = [([m["naziv"], k["konto"], *[""] * len(columns), None, st["greska"]], x.ERROR)] if st.get("greska") else []
        for row in st.get("redovi", []):
            texts = [row["kolone"].get(c, "") for c in columns]
            cells = [_number(t) if _amount_column(st, c) else t for c, t in zip(columns, texts)]
            lines.append(([m["naziv"], k["konto"], *cells, row["iznos"], ""], x.TEXT))
        if not st.get("greska") and not st["slaze"]:
            lines.append(([m["naziv"], k["konto"], *[""] * len(columns), None, mismatch_note(k)], x.WARNING))
        for values, color in lines:
            for c, v in enumerate(values, 1):
                cell = it.cell(r, c, v)
                cell.font = font(color=hexc(color))
                cell.border = Border(bottom=thin)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    cell.number_format = money
            r += 1
    for c in range(1, len(headers) + 1):
        it.column_dimensions[get_column_letter(c)].width = 18 if c > 2 else 14
    it.column_dimensions[get_column_letter(len(headers))].width = 50
    if r > 2:
        it.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{r - 1}"
    it.freeze_panes = "A2"
    it.page_setup.orientation = "landscape"
    it.page_setup.fitToWidth, it.page_setup.fitToHeight = 1, 0
    it.sheet_properties.pageSetUpPr.fitToPage = True


def _sheet(workbook, title: str, headers: list[str], lines: list[tuple[list, object]], widths: dict | None = None):
    """A plain sheet: bold header with a filter, one row per (values, colour); floats as money."""
    from openpyxl.styles import Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    hexc = lambda c: c.hexval()[2:].upper()
    thin = Side(style="thin", color=hexc(x.BORDER))
    ws = workbook.create_sheet(title)
    ws.sheet_view.showGridLines = False
    for c, h in enumerate(headers, 1):
        cell = ws.cell(1, c, h)
        cell.font = Font(name="Segoe UI", size=10, bold=True)
        cell.fill = PatternFill("solid", fgColor=hexc(x.NEUTRAL_BG))
        cell.border = Border(bottom=thin)
    for r, (values, color) in enumerate(lines, 2):
        for c, v in enumerate(values, 1):
            cell = ws.cell(r, c, v)
            cell.font = Font(name="Segoe UI", size=10, color=hexc(color))
            cell.border = Border(bottom=thin)
            if isinstance(v, float):
                cell.number_format = "#,##0.00"
    for c, h in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(c)].width = (widths or {}).get(h, 16)
    if lines:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(lines) + 1}"
    ws.freeze_panes = "A2"
    return ws


def _client_sheets(workbook, value: dict) -> None:
    """Sheets of "Računi veleprodaje po klijentima": Klijenti, Računi, Stavke računa, Konta naloga."""
    clients = value.get("po_klijentima") or []
    invoices = value.get("racuni") or []
    if not clients and not invoices:
        return
    _sheet(workbook, "Klijenti", ["Komitent", "Naziv", "Promet", "Izuzeto", "Broj računa", "Iznos računa"],
           [([c["sifra"], c["naziv"], float(c["promet"]), float(c["izuzeto"]), c["broj_racuna"], float(c["iznos_racuna"])],
             x.MUTED if c["naziv"] == BEZ_RACUNA else x.TEXT) for c in clients], {"Naziv": 40})
    fields = list(dict.fromkeys(f for inv in invoices for f in (inv.get("polja") or {})))
    lines = []
    for inv in invoices:
        row = [inv["godina"], inv["dokument"], inv["datum"], inv["vrsta"], inv["komitent"], inv["naziv"],
               float(inv["iznos"]), inv["status"], inv["nalog"]]
        row += [(inv.get("polja") or {}).get(f, "") for f in fields]
        lines.append((row + [inv["greska"]], x.ERROR if inv["greska"] else x.TEXT))
    _sheet(workbook, "Računi", ["Godina", "Dokument", "Datum", "Vrsta", "Komitent", "Naziv", "Prod. vred.", "Status",
                                "Finansijski nalog", *fields, "Greška"], lines, {"Naziv": 34, "Opis": 40, "Greška": 40})
    columns = list(dict.fromkeys(c for inv in invoices for c in (inv.get("stavke") or {}).get("kolone", [])))
    lines = [([inv["dokument"], inv["datum"], inv["naziv"], *[_number(r.get(c, "")) if c in ("Kol.", "Cena", "Iznos")
                                                            else r.get(c, "") for c in columns]], x.TEXT)
             for inv in invoices for r in (inv.get("stavke") or {}).get("redovi", [])]
    _sheet(workbook, "Stavke računa", ["Dokument", "Datum", "Komitent", *columns], lines, {"Komitent": 34, "Naziv": 34})
    lines = []
    for order in (value.get("nalozi") or {}).values():
        if order.get("greska"):
            lines.append(([order["broj"], "", "", None, None, order["greska"]], x.ERROR))
        for r in order.get("redovi", []):
            lines.append(([order["broj"], r.get("Konto", ""), r.get("Analitka", ""), _number(r.get("Duguje", "")),
                           _number(r.get("Potražuje", "")), ""], x.TEXT))
    _sheet(workbook, "Konta naloga", ["Nalog", "Konto", "Analitika", "Duguje", "Potražuje", "Greška"], lines,
           {"Analitika": 34, "Greška": 40})


def _clients_table(value: dict, width: float):
    head = x.style("ch", 8, x.TEXT, bold=True)
    head_r = x.style("chr", 8, x.TEXT, bold=True, right=True)
    rows = [[p("Komitent", head), p("Naziv", head), p("Računa", head_r), p("Iznos računa", head_r),
             p("Izuzeto", head_r), p("Promet", head_r)]]
    for c in value["po_klijentima"]:
        color = x.MUTED if c["naziv"] == BEZ_RACUNA else x.TEXT
        st = x.style("cc", 8.5, color)
        st_r = x.style("cr", 8.5, color, right=True)
        rows.append([p(esc(c["sifra"]), st), p(esc(c["naziv"]), st), p(str(c["broj_racuna"]), st_r),
                     p(_amount(c["iznos_racuna"]), st_r), p(_amount(c["izuzeto"]), st_r),
                     p(f"<b>{_amount(c['promet'])}</b>", st_r)])
    table = Table(rows, colWidths=[24 * mm, width - 24 * mm - 15 * mm - 3 * 27 * mm, 15 * mm, 27 * mm, 27 * mm, 27 * mm],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), x.NEUTRAL_BG),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, x.BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _number(text: str):
    """An amount from the card as a number for Excel (the text if it isn't one)."""
    from tim_automation.pages.app_page import parse_amount
    value = parse_amount(text) if text.strip() else None
    return value if value is not None else text
