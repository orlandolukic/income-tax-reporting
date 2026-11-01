"""Reading an ePorezi synthetic report ("Синтетика у PDF формату", title "Konsolidovani upit stanja"): the state of
every account of the taxpayer, for the PURS page's "Stanje kod Poreske uprave".

Layout (from a real report, ID 36462347, 2026-10-13): every page repeats the header (Datum štampanja, Stranica,
Poreski obveznik: PIB, name, Sedište, Status) and a ruled table
  Konto | Poziv na broj | Opis računa | Izvor | Šifra opštine | Opština | Datum stanja | Naplaćena kamata | Osnovni dug |
  Kamata | Ukupan dug
(cells wrap; amounts 1,930.43). A konto without a Poziv na broj is one row (per opština); a konto can have several rows,
one per Poziv na broj (e.g. 711211 Porez na dobit: the same Pozivi na broj as its analytical report), and the
"Objedinjena naplata poreza i doprinosa" rows have konto "4" with their own Poziv na broj each. After the last row a text
line "Label Ukupno: <naplaćena kamata> <osnovni dug> <kamata> <ukupan dug>" gives the totals (checked against the rows).
Columns are found by their names, so a column added or moved still reads."""
import re
from pathlib import Path

from tim_automation.purs_analytics import _header, _one_line, amount

TOTAL_RE = re.compile(r"Ukupno:\s*((?:-?[\d,]+\.\d{2}\s*)+)$")
# Field name -> what its column head starts with (normalized: lower case, no diacritics, letters / digits only).
FIELDS = (("konto", ("konto", "racun")), ("poziv_na_broj", ("pozivnabroj",)), ("opis", ("opisracuna", "opis", "naziv")),
          ("izvor", ("izvor",)), ("sifra_opstine", ("sifraopstine",)), ("opstina", ("opstina",)),
          ("datum_stanja", ("datumstanja", "datum")), ("grupa", ("fiskalnagrupa", "grupa")))
AMOUNT_WORDS = ("duguje", "potrazuje", "kamata", "dug", "saldo", "preplata", "uplata", "zaduzenje", "iznos")


def _norm(text: str) -> str:
    text = _one_line(text).casefold().replace("đ", "dj")
    for a, b in (("č", "c"), ("ć", "c"), ("š", "s"), ("ž", "z")):
        text = text.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", text)


def _columns(heads: list[str]) -> dict | None:
    """Column index of every known field and of the amount columns; None unless this is the accounts table."""
    norm = [_norm(h) for h in heads]
    found: dict = {}
    for name, starts in FIELDS:
        found[name] = next((i for i, n in enumerate(norm) if i not in found.values() and n and any(
            n.startswith(s) for s in starts)), None)
    if found["konto"] is None:
        return None
    taken = {i for i in found.values() if i is not None}
    found["iznosi"] = [i for i, n in enumerate(norm) if i not in taken and any(w in n for w in AMOUNT_WORDS)]
    return found if found["iznosi"] else None


def parse(path: Path) -> dict:
    """{"zaglavlje" (+ "stanje_na_dan" from Datum stanja), "kolone": amount columns, "racuni": [one per row: konto,
    poziv_na_broj, opis, izvor, sifra_opstine, opstina, datum_stanja, grupa, vrednosti {column: amount}, strana],
    "ukupno": sums of the rows, "ukupno_izvestaj": the report's own "Ukupno" line, "provera": {slaze, problemi},
    "broj_strana"}."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("Nedostaje biblioteka pdfplumber: pokrenite „pip install -r requirements.txt“.") from None
    header: dict = {}
    columns: list[str] = []
    rows_out: list[dict] = []
    report_total: list[float] | None = None
    with pdfplumber.open(path) as pdf:
        pages = len(pdf.pages)
        for number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=1.5) or ""
            if number == 1:
                header = _header(text)
            for line in text.splitlines():
                m = TOTAL_RE.search(line.strip())
                if m:
                    report_total = [amount(v) for v in m.group(1).split()]
            for table in page.find_tables():
                rows = table.extract(x_tolerance=1.5)
                if not rows:
                    continue
                for h, row in enumerate(rows[:3]):  # the head row may be below a title row
                    found = _columns([_one_line(c) for c in row])
                    if found:
                        break
                else:
                    continue
                heads = [_one_line(c) for c in rows[h]]
                for i in found["iznosi"]:
                    if heads[i] not in columns:
                        columns.append(heads[i])
                for row in rows[h + 1:]:
                    cells = [_one_line(c) for c in row] + [""] * len(heads)
                    konto = cells[found["konto"]]
                    if not re.fullmatch(r"\d+", konto or ""):
                        continue
                    item = {name: (cells[found[name]] if found[name] is not None else "") for name, _ in FIELDS}
                    item.update(vrednosti={heads[i]: amount(cells[i]) for i in found["iznosi"]}, strana=number)
                    rows_out.append(item)
    totals = {c: round(sum(r["vrednosti"].get(c) or 0 for r in rows_out), 2) for c in columns}
    problems = []
    shown = {}
    if report_total is not None:
        shown = dict(zip(columns[-len(report_total):] if len(report_total) <= len(columns) else columns, report_total))
        for c, v in shown.items():
            if v is not None and abs(v - totals.get(c, 0)) > 0.005:
                problems.append(f"{c}: zbir redova {totals.get(c, 0):,.2f}, u izveštaju {v:,.2f}")
    elif rows_out:
        problems.append("U izveštaju nema reda „Ukupno“.")
    dates = sorted({r["datum_stanja"] for r in rows_out if r["datum_stanja"]})
    if dates and "stanje_na_dan" not in header:
        header["stanje_na_dan"] = dates[-1] if len(dates) == 1 else f"{dates[0]} – {dates[-1]}"
    return {"zaglavlje": header, "kolone": columns, "racuni": rows_out, "ukupno": totals, "ukupno_izvestaj": shown,
            "provera": {"slaze": not problems, "problemi": problems}, "broj_strana": pages}
