"""Reading an ePorezi analytical report ("Аналитика за фискалну групу у PDF формату", title "Konsolidovani upit stanja")
into its accounts, for the PURS page's "Knjiženje" view.

Layout (from a real PDP report, 2026-10-13): every page repeats the header (Stanje na dan, Datum štampanja, Stranica,
Poreski obveznik: PIB, name, Sedište, Status). Then, per account + "Poziv na broj":
  a line "Račun: 711211 Poziv na broj: 7302190000006544288 Izvor podatka: DIS Opština: (021) - Beograd–Zemun",
  a ruled table: Datum | Opis | Dokument | Duguje | Potražuje | Kamata | Nap. kamata | Trenutno stanje: Osn. dug | Kamata
  (cells wrap over lines; Dokument = the document and, on a second line, its period "01.01.2024 31.12.2024"),
  a line "Ukupno: <duguje> <potražuje> <kamata> <nap. kamata>",
  a ruled table: Račun \\ Poziv na broj | Opis računa | Duguje | Potražuje | Naplaćena kamata | Osnovni dug | Kamata |
  Ukupan dug.
An account's entries can continue on the next page (the header line is repeated there): they are joined by account +
Poziv na broj. Amounts are written 1,930.43 (comma = thousands). Interest calculation lines have no document."""
import re
from pathlib import Path

ENTRY_HEADS = ("Datum", "Opis", "Dokument", "Duguje", "Potražuje", "Kamata", "Nap. kamata", "Osn. dug", "Kamata")
ENTRY_KEYS = ("datum", "opis", "dokument", "duguje", "potrazuje", "kamata", "nap_kamata", "osn_dug", "kamata_stanje")
SUMMARY_KEYS = ("racun_poziv", "opis_racuna", "duguje", "potrazuje", "naplacena_kamata", "osnovni_dug", "kamata",
                "ukupan_dug")
AMOUNTS = ("duguje", "potrazuje", "kamata", "nap_kamata", "osn_dug", "kamata_stanje")

ACCOUNT_RE = re.compile(r"Račun:\s*(?P<racun>\S+)\s+Poziv na broj:\s*(?P<poziv>\S+)"
                        r"(?:\s+Izvor podatka:\s*(?P<izvor>.*?))?(?:\s+Opština:\s*(?P<opstina>.*?))?"
                        r"(?:\s+Trenutno stanje)?\s*$")
TOTAL_RE = re.compile(r"^Ukupno:\s*(.*)$")
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
PERIOD_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})")


def amount(text) -> float | None:
    text = " ".join(str(text or "").split()).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _one_line(text) -> str:
    return " ".join(str(text or "").split())


def kind_of(entry: dict) -> str:
    """What an entry is, for grouping on the page."""
    opis = entry["opis"].casefold()
    if opis.startswith("storno"):
        return "Storno"
    if opis.startswith("početno stanje"):
        return "Početno stanje"
    if "broj dana" in opis and "osnovica" in opis:
        return "Obračun kamate"
    if opis.startswith("uplata"):
        return "Uplata"
    if "prenos" in opis:
        return "Prenos"
    if not opis and entry["nap_kamata"] is not None:
        return "Naplata kamate"
    if "zaduženje" in opis or "akontacij" in opis or entry["duguje"]:
        return "Zaduženje"
    return "Ostalo"


def _header(text: str) -> dict:
    """Stanje na dan, Datum štampanja, PIB, name, Sedište, Status from the page header's text."""
    out: dict = {}
    m = re.search(r"Stanje na dan:\s*(\S+)", text)
    if m:
        out["stanje_na_dan"] = m.group(1)
    m = re.search(r"Datum štampanja:\s*(\S+)", text)
    if m:
        out["datum_stampanja"] = m.group(1)
    m = re.search(r"PIB:\s*(\d+)", text)
    if m:
        out["pib"] = m.group(1)
    lines = [l.strip() for l in text.splitlines()]
    if "PIB:" in text:
        start = next(i for i, l in enumerate(lines) if l.startswith("PIB:")) + 1
        name = []
        for line in lines[start:]:
            if line.startswith(("Sedište:", "Status:", "Račun:")):
                break
            name.append(line)
        out["naziv"] = " ".join(name)
    m = re.search(r"Sedište:\s*(.+)", text)
    if m:
        out["sediste"] = m.group(1).strip()
    m = re.search(r"Status:\s*(.+)", text)
    if m:
        out["status"] = m.group(1).strip()
    return out


def parse(path: Path) -> dict:
    """{"zaglavlje", "pozivi": [{racun, poziv_na_broj, izvor, opstina, opis_racuna, stavke, ukupno, stanje, provera}],
    "ukupno", "upozorenja", "broj_strana"}."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("Nedostaje biblioteka pdfplumber: pokrenite „pip install -r requirements.txt“.") from None
    header: dict = {}
    groups: dict[tuple, dict] = {}
    order: list[tuple] = []
    warnings: list[str] = []
    current: dict | None = None
    with pdfplumber.open(path) as pdf:
        pages = len(pdf.pages)
        for number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=1.5) or ""
            if number == 1:
                header = _header(text)
                if "upit stanja" not in text.casefold() or "Poziv na broj" not in text:
                    raise ValueError("Ovo nije analitički izveštaj „Konsolidovani upit stanja“ (nema „Poziv na broj“).")
            # Lines (account headers, totals) and tables in the order they are on the page.
            items: list[tuple[float, str, object]] = []
            for line in page.extract_text_lines(x_tolerance=1.5):
                t = line["text"].strip()
                if ACCOUNT_RE.match(t) or TOTAL_RE.match(t):
                    items.append((line["top"], "line", t))
            for table in page.find_tables():
                rows = table.extract(x_tolerance=1.5)
                if not rows:
                    continue
                first = [_one_line(c) for c in rows[0]]
                second = [_one_line(c) for c in rows[1]] if len(rows) > 1 else []
                if tuple(second[:len(ENTRY_HEADS)]) == ENTRY_HEADS or tuple(first[:len(ENTRY_HEADS)]) == ENTRY_HEADS:
                    # The table's box starts on the account's own line ("… Trenutno stanje"): place it by its
                    # column heads ("Datum", "Opis", …), which are below that line.
                    heads_row = 1 if tuple(second[:len(ENTRY_HEADS)]) == ENTRY_HEADS else 0
                    items.append((table.rows[heads_row].bbox[1], "entries", rows))
                elif first and first[0].startswith("Račun") and "Poziv na broj" in first[0] and "Opis računa" in first:
                    items.append((table.bbox[1], "summary", rows))
            for _, what, content in sorted(items, key=lambda x: x[0]):
                if what == "line" and ACCOUNT_RE.match(content):
                    m = ACCOUNT_RE.match(content)
                    key = (m.group("racun"), m.group("poziv"))
                    if key not in groups:
                        groups[key] = {"racun": key[0], "poziv_na_broj": key[1], "izvor": (m.group("izvor") or "").strip(),
                                       "opstina": (m.group("opstina") or "").strip(), "opis_racuna": "", "stavke": [],
                                       "ukupno": None, "stanje": None, "strane": []}
                        order.append(key)
                    current = groups[key]
                    if number not in current["strane"]:
                        current["strane"].append(number)
                elif current is None:
                    warnings.append(f"Strana {number}: tabela pre prvog „Račun / Poziv na broj“ je preskočena.")
                elif what == "line":
                    values = [amount(v) for v in TOTAL_RE.match(content).group(1).split()]
                    current["ukupno"] = dict(zip(("duguje", "potrazuje", "kamata", "nap_kamata"), values))
                elif what == "entries":
                    for row in content:
                        cells = [c if c is not None else "" for c in row] + [""] * len(ENTRY_KEYS)
                        if not DATE_RE.match(_one_line(cells[0])):
                            continue
                        entry = dict(zip(ENTRY_KEYS, cells))
                        document = [l.strip() for l in str(entry["dokument"]).splitlines() if l.strip()]
                        period = PERIOD_RE.search(" ".join(document[1:])) if len(document) > 1 else None
                        entry.update(datum=_one_line(entry["datum"]), opis=_one_line(entry["opis"]),
                                     dokument=document[0] if document else "",
                                     dokument_dodatak=" ".join(document[1:]),
                                     period=f"{period.group(1)} – {period.group(2)}" if period else "",
                                     strana=number)
                        for k in AMOUNTS:
                            entry[k] = amount(entry[k])
                        entry["vrsta"] = kind_of(entry)
                        current["stavke"].append(entry)
                elif what == "summary":
                    for row in content[1:]:
                        cells = [_one_line(c) for c in row]
                        if not cells or "\\" not in cells[0]:
                            continue
                        values = dict(zip(SUMMARY_KEYS, cells))
                        current["opis_racuna"] = values.get("opis_racuna", "")
                        current["stanje"] = {k: amount(values.get(k)) for k in SUMMARY_KEYS[2:]}
    result = []
    for key in order:
        g = groups[key]
        sums = {k: round(sum(e[k] or 0 for e in g["stavke"]), 2) for k in ("duguje", "potrazuje", "kamata", "nap_kamata")}
        g["zbir_stavki"] = sums
        problems = []
        if g["ukupno"]:
            for k, label in (("duguje", "Duguje"), ("potrazuje", "Potražuje"), ("kamata", "Kamata"),
                             ("nap_kamata", "Nap. kamata")):
                shown = g["ukupno"].get(k)
                if shown is not None and abs(shown - sums[k]) > 0.005:
                    problems.append(f"{label}: zbir stavki {sums[k]:,.2f}, u izveštaju {shown:,.2f}")
        else:
            problems.append("Nema reda „Ukupno“.")
        if g["stanje"] is None:
            problems.append("Nema tabele sa stanjem (Osnovni dug / Kamata / Ukupan dug).")
        g["provera"] = {"slaze": not problems, "problemi": problems}
        result.append(g)
        warnings += [f"{g['racun']} \\ {g['poziv_na_broj']}: {p}" for p in problems]
    totals = {k: round(sum((g["stanje"] or {}).get(k) or 0 for g in result), 2)
              for k in ("duguje", "potrazuje", "naplacena_kamata", "osnovni_dug", "kamata", "ukupan_dug")}
    return {"zaglavlje": header, "pozivi": result, "ukupno": totals, "upozorenja": warnings, "broj_strana": pages,
            "broj_stavki": sum(len(g["stavke"]) for g in result)}
