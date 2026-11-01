"""Reading a PDF report from ePorezi (e.g. "Упит стања" → "Синтетика у PDF формату"): the text of every page, its
lines and the tables pdfplumber recognizes. The layout of PURS's PDFs is not known yet, so this returns everything;
specific fields can be picked out once a real report has been read."""
from pathlib import Path


def read(path: Path) -> dict:
    """{"broj_strana", "tekst" (pages joined), "strane": [text per page], "kolone": ["Strana", "Red", "Tekst"],
    "redovi": [one per text line], "broj", "tabele": [{"strana", "kolone", "redovi"}]}."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("Nedostaje biblioteka pdfplumber: pokrenite „pip install -r requirements.txt“.") from None
    pages: list[str] = []
    lines: list[dict] = []
    tables: list[dict] = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages.append(text)
            for i, line in enumerate((l for l in text.splitlines() if l.strip()), start=1):
                lines.append({"Strana": number, "Red": i, "Tekst": line.strip()})
            for table in page.extract_tables() or []:
                rows = [[(cell or "").strip() for cell in row] for row in table if any(cell for cell in row)]
                if not rows:
                    continue
                heads = _heads(rows[0])
                tables.append({"strana": number, "kolone": heads,
                               "redovi": [dict(zip(heads, row)) for row in rows[1:]]})
    return {"broj_strana": len(pages), "tekst": "\n\n".join(pages), "strane": pages,
            "kolone": ["Strana", "Red", "Tekst"], "redovi": lines, "broj": len(lines), "tabele": tables}


def _heads(row: list[str]) -> list[str]:
    """Column names from a table's first row (unique, never empty)."""
    heads: list[str] = []
    for i, cell in enumerate(row, start=1):
        name = " ".join(cell.split()) or f"Kolona {i}"
        while name in heads:
            name += "*"
        heads.append(name)
    return heads
