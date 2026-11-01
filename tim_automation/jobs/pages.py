"""What is known about each application page (title, tables, columns, search field), by menu path.

KNOWN holds pages described from saved HTML; every "Otvori stranicu" run adds or updates the page in
data/pages.json. The job page uses this to offer the right column names when configuring tasks."""
import json
import threading
import time
from pathlib import Path

DATA_FILE = Path("data") / "pages.json"

TEXT_OPS = ["Jednako", "Različito od", "Veće od", "Veće ili jednako", "Manje od", "Manje ili jednako", "Počinje sa",
            "Sadrži", "Završava se na", "Ne počinje sa", "Ne sadrži", "Ne završava se na", "Između"]
RANGE_OPS = ["Jednako", "Različito od", "Veće od", "Veće ili jednako", "Manje od", "Manje ili jednako", "Između"]
LIST_OPS = ["Je u listi", "Nije u listi"]

# From the HTML of Maloprodaja > Izlazi and its "Napredni filteri" window (2026-10-07). Only structure.
# A filter: id "<tabela>.<polje>" as the window labels it, kind text/date/number/list/bool.
KNOWN: dict[str, dict] = {
    "Maloprodaja > Izlazi": {
        "naslov": "Izlazni računi maloprodaje",
        "filter": True,
        "tabele": [
            {"id": "I2", "naziv": "", "kolone": ["Mag.", "Vrsta", "Dokument", "Datum", "Komitent", "Naziv",
                                                   "Prod. vred.", "Status"]},
            {"id": "I42", "naziv": "STAVKE IZLAZNOG DOKUMENTA", "kolone": ["Roba", "Naziv", "Kol.", "Cena", "Iznos"]},
        ],
        "filteri": [
            {"id": "racun.Dokument", "naziv": "Dokument", "vrsta": "text", "operatori": TEXT_OPS},
            {"id": "racun.Datum", "naziv": "Datum", "vrsta": "date", "operatori": RANGE_OPS},
            {"id": "racun.Broj kalkulacije", "naziv": "Broj kalkulacije", "vrsta": "number", "operatori": RANGE_OPS},
            {"id": "magacin.Sifra", "naziv": "Magacin – šifra", "vrsta": "text", "operatori": TEXT_OPS},
            {"id": "komitent.Šifra", "naziv": "Komitent – šifra", "vrsta": "text", "operatori": TEXT_OPS},
            {"id": "racun.Podvrsta", "naziv": "Podvrsta", "vrsta": "list", "operatori": LIST_OPS,
             "opcije": ["Pazar", "Izlazni račun", "Interni prenos", "Prenos u komisioni magacin",
                        "Interni izlaz koji ide u KIR"]},
            {"id": "racun.Status", "naziv": "Status", "vrsta": "list", "operatori": LIST_OPS,
             "opcije": ["priprema na kasi", "u pripremi", "vraćeno", "knjiženo", "neispravan fin.nal.", "završeno"]},
            {"id": "racun.Vrsta PDV evidencije", "naziv": "Vrsta PDV evidencije", "vrsta": "list", "operatori": LIST_OPS,
             "opcije": ["E-Faktura", "E-Fiskalizacija", "Pojedinačna Evidencija PDV", "Zbirna Evidencija PDV"]},
            {"id": "racun.Razduzen po normativu", "naziv": "Razdužen po normativu", "vrsta": "bool",
             "operatori": ["Jednako"], "opcije": ["Ne", "Da"]},
        ],
        "izvor": "HTML stranice",
    },
}

_lock = threading.Lock()


def _read() -> dict:
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def catalog() -> dict[str, dict]:
    """Known pages; what a run found is merged over what was known in advance (e.g. filters stay)."""
    with _lock:
        saved = _read()
    return {path: {**KNOWN.get(path, {}), **saved.get(path, {})} for path in {*KNOWN, *saved}}


def save(path: str, info: dict) -> None:
    """Remember what "Otvori stranicu" found on a page (structure only, no row data)."""
    entry = {
        "naslov": info.get("naslov", ""),
        "filter": info.get("filter", False),
        "tabele": [{k: t[k] for k in ("id", "naziv", "kolone")} for t in info.get("tabele", [])],
        "izvor": "pokretanje",
        "vreme": time.time(),
    }
    with _lock:
        data = _read()
        data[path] = entry
        DATA_FILE.parent.mkdir(exist_ok=True)
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
