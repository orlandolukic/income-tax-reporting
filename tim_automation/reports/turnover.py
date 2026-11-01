"""Report "Promet u poslednjih 12 meseci": the turnover that counts toward the VAT registration limit
(Zakon o PDV: 8.000.000 RSD in the last 12 months).

For each month (by default the last 12, the current one included), Finansije › Izveštaji › Popis salda
analitike (sintetika) is shown for a konto range (default 6–65) with a date filter in that month (default
"stavka fin.naloga.Datum", the item's date); the month's turnover is the Potražuje total (default; the
user chose credits only: storno and year-end closing on the Duguje side are not subtracted) minus that of
the excluded konta (default 6050, income from exported services, not subject to VAT), which are reported
separately. Months of an earlier year are read after opening the company in that year. All of these are
settings (⚙ on the page, SETTINGS / check_settings), kept per company.

With "Pojedinačni iznosi po kontu" (setting `stavke`, off by default) each konto of a month is opened (its header
is a link to the konto's card), the individual entries are read (`konto["stavke"]`) and checked against the konto's
sum, then the card's back arrow returns to the report. A konto whose card can't be read gets `stavke.greska`; the
month's amounts still come from the report.

With "Računi veleprodaje po klijentima" (setting `klijenti`, off by default; it reads the konto cards too) each year's
Veleprodaja › Izlazi is read after that year's months (`_read_invoices`): the list, then every invoice dated in the
report's period (fields, items, links) and the financial order it was booked with (konta, `value["nalozi"]`, by
`izlazi_vp.order_key`). `group_clients` then puts every card entry under the client of the invoice whose order it
belongs to (the order number is looked for in any column of the card), or under "Bez računa veleprodaje".
"""
import calendar
import datetime
import re
import time

from tim_automation.pages import izlazi_vp, sinteticka
from tim_automation.pages.app_page import format_amount, parse_amount

MONTH_NAMES = ("Januar", "Februar", "Mart", "April", "Maj", "Jun", "Jul", "Avgust", "Septembar", "Oktobar",
               "Novembar", "Decembar")
DATE_FIELDS = {"Datum stavke naloga": "stavka fin.naloga.Datum", "Datum naloga": "finansijski nalog.Datum"}
CREDIT, NET = "Potražuje", "Potražuje − Duguje"
MAX_MONTHS = 24


def last_months(today: datetime.date, count: int = 12, current: bool = True) -> list[tuple[int, int]]:
    """(year, month) of the last `count` months up to today's month (or the month before it), oldest first."""
    year, month = today.year, today.month
    if not current:
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    months = []
    for _ in range(count):
        months.append((year, month))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return months[::-1]


def month_entry(year: int, month: int) -> dict:
    last = calendar.monthrange(year, month)[1]
    return {
        "mesec": f"{year}-{month:02d}", "naziv": f"{MONTH_NAMES[month - 1]} {year}", "godina": str(year),
        "od": f"01/{month:02d}/{year}", "do": f"{last:02d}/{month:02d}/{year}",
        "status": "ceka", "osnova": None, "potrazuje": None, "duguje": None, "izuzeto": None, "promet": None,
        "konta": [], "konta_potpuna": None, "napomena": "",
    }


def excluded_list(text: str) -> list[str]:
    return list(dict.fromkeys(k for k in re.split(r"[\s,;]+", text or "") if k))


def _konta(value: dict) -> str:
    return ", ".join(value["izuzeta"])


def excluded_note(value: dict) -> str:
    if not value["izuzeta"]:
        return "Nijedno konto nije izuzeto iz prometa."
    if value["izuzeta"] == ["6050"]:
        return ("Konto 6050 (prihodi od izvoza usluga) nije uračunat u promet: izvoz nije predmet PDV-a. "
                "Iznos je prikazan posebno.")
    return (f"Konta {_konta(value)} (i njihova podkonta) nisu uračunata u promet (izuzeta u podešavanjima, npr. izvoz "
            "koji nije predmet PDV-a). Iznos je prikazan posebno.")


def amount_note(value: dict) -> str:
    by = "datumu stavke naloga" if value["datum"] == "Datum stavke naloga" else "datumu naloga"
    note = (f"Promet = {value['iznos']} na kontima {value['konto_od']}–{value['konto_do']} (popis salda analitike "
            f"(sintetika), po {by})")
    if value["iznos"] == CREDIT:
        note += "; Duguje strana (storna, zatvaranje klasa) se ne oduzima"
    return note + ". Uključeni su nalozi u svim statusima."


def run(ctx, today: datetime.date | None = None) -> dict:
    s = check_settings({**SETTING_DEFAULTS, **(ctx.settings or {})})
    today = today or datetime.date.today()
    months = [month_entry(y, m) for y, m in last_months(today, int(s["meseci"]), s["tekuci"])]
    value = {
        "od": months[0]["mesec"], "do": months[-1]["mesec"], "danas": today.isoformat(),
        "limit": parse_amount(s["limit"]), "konto_od": s["konto_od"], "konto_do": s["konto_do"],
        "izuzeta": excluded_list(s["izuzeta"]), "iznos": s["iznos"], "datum": s["datum"],
        "meseci": months, "broj_meseci": len(months), "stavke": s["stavke"] or s["klijenti"],
        "klijenti": s["klijenti"],
    }
    if value["klijenti"]:
        value.update(racuni=[], nalozi={}, po_klijentima=[], racuni_godine={})
    value["izuzet_konto"] = _konta(value)
    value["kolona"] = f"{value['iznos']} {value['konto_od']}–{value['konto_do']}"
    value["napomene"] = [excluded_note(value), amount_note(value)]
    if value["stavke"]:
        value["napomene"].append("Pojedinačni iznosi su pročitani sa kartice svakog konta (klik na konto u popisu salda).")
    if value["klijenti"]:
        value["napomene"].append("Po klijentima: stavke kartica su povezane sa izlaznim računima veleprodaje preko broja "
                                 "finansijskog naloga; stavke bez računa veleprodaje su prikazane posebno.")
    _totals(value)
    ctx.update(value)
    years = sorted({e["godina"] for e in months}, reverse=True)
    if ctx.year in years:  # the open year first: no need to change it
        years.remove(ctx.year)
        years.insert(0, ctx.year)
    for year in years:
        entries = [e for e in months if e["godina"] == year]
        ctx.check_cancel()
        if year != ctx.year:
            reason = _open_year(ctx, year)
            if reason:
                for e in entries:
                    e["status"], e["napomena"] = "nedostupno", reason
                value["napomene"].append(f"Godina {year}: {reason}")
                _totals(value)
                ctx.update(value)
                continue
        sinteticka.open_page(ctx.driver)
        for e in reversed(entries):  # newest first
            ctx.check_cancel()
            ctx.progress(f"{e['naziv']}: popis salda analitike (sintetika), konta {value['konto_od']}–{value['konto_do']}...")
            e["status"] = "radi"
            ctx.update(value)
            _read_month(ctx, value, e)
            _totals(value)
            ctx.update(value)
        if value["klijenti"]:
            _read_invoices(ctx, value, year, entries)
            value["po_klijentima"] = group_clients(value)
            ctx.update(value)
    if value["izuzeta"]:
        if value["ukupno"]["izuzeto"]:
            value["napomene"][0] += f" Ukupno izuzeto: {format_amount(value['ukupno']['izuzeto'])} RSD."
        else:
            value["napomene"][0] += f" U periodu nema prometa na kontima {_konta(value)}."
    return value


def _iso(date: str) -> str:
    return sinteticka.card_date(date)


def _read_invoices(ctx, value: dict, year: str, entries: list[dict]) -> None:
    """Veleprodaja › Izlazi of the open year: every invoice dated in the year's months of the report, with its
    financial order (see the module doc). A failing invoice / order is marked and the rest go on."""
    first, last = min(_iso(e["od"]) for e in entries), max(_iso(e["do"]) for e in entries)
    ctx.progress(f"Godina {year}: izlazni računi veleprodaje, lista...")
    try:
        izlazi_vp.open_page(ctx.driver)
        rows = izlazi_vp.read_list(ctx.driver, on_progress=lambda n, total: ctx.progress(
            f"Godina {year}: izlazni računi veleprodaje, lista {n} / {total}..."))
    except Exception as err:
        value["napomene"].append(f"Godina {year}: izlazni računi veleprodaje nisu pročitani ({err}).")
        value["racuni_godine"][year] = {"greska": str(err)}
        return
    inside = [r for r in rows if first <= _iso(r.get("Datum", "")) <= last]
    value["racuni_godine"][year] = {"u_listi": len(rows), "u_periodu": len(inside)}
    print(f"    {year}: {len(rows)} invoices in Veleprodaja > Izlazi, {len(inside)} in {first} - {last}")
    shown = time.monotonic()
    for i, row in enumerate(inside):
        ctx.check_cancel()
        doc = row.get("Dokument", "")
        ctx.progress(f"Godina {year}: račun {doc} ({i + 1} / {len(inside)})...")
        inv = {"godina": year, "dokument": doc, "datum": row.get("Datum", ""), "vrsta": row.get("Vrsta", ""),
               "komitent": row.get("Komitent", ""), "naziv": row.get("Naziv", ""), "status": row.get("Status", ""),
               "iznos": parse_amount(row.get("Prod. vred.", "")) or 0.0, "lista": row, "nalog": "", "greska": ""}
        try:
            inv.update(izlazi_vp.read_invoice(ctx.driver, doc))
            inv["nalog"] = inv["veze"].get("Finansijski nalog", "")
            key = izlazi_vp.order_key(inv["nalog"])
            if key and key not in value["nalozi"]:
                try:
                    value["nalozi"][key] = izlazi_vp.read_order(ctx.driver, inv["nalog"])
                except Exception as err:
                    value["nalozi"][key] = {"broj": inv["nalog"], "greska": f"Nalog nije pročitan: {err}"}
                    print(f"    Order {inv['nalog']}: {err}")
        except Exception as err:
            inv["greska"] = f"Račun nije pročitan: {err}"
            print(f"    Invoice {doc}: {err}")
            try:
                izlazi_vp.back_to_invoices(ctx.driver)
            except Exception as again:
                print(f"    Could not open the invoices again: {again}")
        value["racuni"].append(inv)
        if time.monotonic() - shown > 3:  # the value gets big: don't publish it after every invoice
            value["po_klijentima"] = group_clients(value)
            ctx.update(value)
            shown = time.monotonic()
    try:
        izlazi_vp.clear_filter(ctx.driver)
    except Exception:
        pass


def group_clients(value: dict) -> list[dict]:
    """Card entries (and invoices) by client: [{sifra, naziv, promet, izuzeto, broj_racuna, iznos_racuna,
    racuni: [index in value["racuni"]], stavke: [{mesec, konto, nalog, iznos, racun}]}], biggest promet first,
    "Bez računa veleprodaje" last."""
    invoices = value.get("racuni", [])
    by_order = {}
    for i, inv in enumerate(invoices):
        key = izlazi_vp.order_key(inv.get("nalog", ""))
        if key:
            by_order.setdefault(key, i)
    clients: dict[str, dict] = {}

    def client(sifra: str, naziv: str) -> dict:
        key = sifra or naziv
        if key not in clients:
            clients[key] = {"sifra": sifra, "naziv": naziv, "promet": 0.0, "izuzeto": 0.0, "broj_racuna": 0,
                            "iznos_racuna": 0.0, "racuni": [], "stavke": []}
        return clients[key]

    for i, inv in enumerate(invoices):
        c = client(inv["komitent"], inv["naziv"])
        c["racuni"].append(i)
        c["broj_racuna"] += 1
        c["iznos_racuna"] = round(c["iznos_racuna"] + inv["iznos"], 2)
    excluded = value.get("izuzeta", [])
    for e in value["meseci"]:
        for k in e.get("konta", []):
            for r in (k.get("stavke") or {}).get("redovi", []):
                keys = [izlazi_vp.order_key(v) for v in r["kolone"].values()]
                found = next((by_order[x] for x in keys if x in by_order), None)
                order = next((v for (col, v), x in zip(r["kolone"].items(), keys)
                              if x and (x in by_order or "nalog" in col.lower())), "")
                if found is None:
                    c = client("", BEZ_RACUNA)
                else:
                    c = client(invoices[found]["komitent"], invoices[found]["naziv"])
                out = any(k["konto"].startswith(x) for x in excluded)
                c["izuzeto" if out else "promet"] = round(c["izuzeto" if out else "promet"] + r["iznos"], 2)
                c["stavke"].append({"mesec": e["naziv"], "konto": k["konto"], "nalog": order, "iznos": r["iznos"],
                                    "izuzeto": out, "racun": found, "kolone": r["kolone"]})
    return sorted(clients.values(), key=lambda c: (c["naziv"] == BEZ_RACUNA, -c["promet"], c["naziv"]))


BEZ_RACUNA = "Bez računa veleprodaje"


def _open_year(ctx, year: str) -> str:
    """Open the company in `year`. "" if done, else why it couldn't be done (those months are skipped)."""
    if ctx.switch_year is None:
        return "firma je izabrana u pretraživaču, pa program ne može sam da promeni godinu."
    try:
        ctx.switch_year(year)
    except LookupError as e:  # main.YearUnavailable
        return str(e)
    ctx.year = year
    return ""


def _amount(value: dict, duguje: float, potrazuje: float) -> float:
    return potrazuje - duguje if value["iznos"] == NET else potrazuje


def _read_month(ctx, value: dict, e: dict) -> None:
    dates = {"polje": DATE_FIELDS[value["datum"]], "operator": "Između", "vrednost": e["od"], "do": e["do"]}
    konta = {"polje": "konto.sifra", "operator": "Između", "vrednost": value["konto_od"], "do": value["konto_do"]}
    result = sinteticka.show(ctx.driver, [konta, dates])
    e["potrazuje"], e["duguje"] = result["potrazuje"], result["duguje"]
    e["osnova"] = round(_amount(value, result["duguje"], result["potrazuje"]), 2)
    e["konta"], e["konta_potpuna"] = result["konta"], result["konta_potpuna"]
    if value["stavke"]:  # also on with "klijenti"
        _read_items(ctx, value, e, [konta, dates])
    excluded = 0.0
    if result["konta_potpuna"]:
        excluded = sum(_amount(value, k["duguje"], k["potrazuje"]) for k in result["konta"]
                       if any(k["konto"].startswith(x) for x in value["izuzeta"]))
    else:
        # Not every konto is shown in the table: ask the site for each excluded konto alone.
        for konto in value["izuzeta"]:
            ctx.progress(f"{e['naziv']}: konto {konto} posebno...")
            alone = sinteticka.show(ctx.driver, [{"polje": "konto.sifra", "operator": "Počinje sa", "vrednost": konto}, dates])
            excluded += _amount(value, alone["duguje"], alone["potrazuje"])
    e["izuzeto"] = round(excluded, 2)
    e["promet"] = round(e["osnova"] - excluded, 2)
    e["status"] = "ok"
    print(f"    {e['naziv']}: {value['iznos']} {format_amount(e['osnova'])}, izuzeto {format_amount(excluded)}, "
          f"promet {format_amount(e['promet'])}")


def _read_items(ctx, value: dict, e: dict, filter_list: list[dict]) -> None:
    """Open each konto of the month's table, read its individual entries and go back (see the module doc)."""
    shown = sinteticka.shown_konta(ctx.driver)
    todo = [k for k in e["konta"] if k["konto"] in shown]
    missing = [k["konto"] for k in e["konta"] if k["konto"] not in shown]
    for k in e["konta"]:
        if k["konto"] not in shown:
            k["stavke"] = {"greska": "Konto nije prikazano u tabeli na sajtu, pa kartica nije otvorena."}
    for i, k in enumerate(todo):
        ctx.check_cancel()
        what = f"{e['naziv']}: konto {k['konto']} ({i + 1} / {len(todo)}), pojedinačni iznosi"
        ctx.progress(f"{what}...")
        if k["konto"] not in sinteticka.shown_konta(ctx.driver):  # the page came back without the result
            sinteticka.show(ctx.driver, filter_list)
        try:
            sinteticka.open_konto(ctx.driver, k["konto"])
        except Exception as err:
            k["stavke"] = {"greska": f"Kartica nije otvorena: {err}"}
            print(f"    Konto {k['konto']}: {k['stavke']['greska']}")
            sinteticka.open_page(ctx.driver)
            continue
        try:
            card = sinteticka.read_card(ctx.driver, on_progress=lambda n, total: ctx.progress(f"{what} {n} / {total}..."))
            k["stavke"] = _items(value, e, k, card)
        except Exception as err:
            k["stavke"] = {"greska": f"Kartica nije pročitana: {err}"}
        finally:
            try:
                sinteticka.back(ctx.driver)
            except Exception as err:
                print(f"    Back to the report failed ({err}); opening it again from the menu.")
                sinteticka.open_page(ctx.driver)
        st = k["stavke"]
        if st.get("greska"):
            print(f"    Konto {k['konto']}: {st['greska']}")
        else:
            print(f"    Konto {k['konto']}: {st['broj']} items, potražuje {format_amount(st['potrazuje'])}, "
                  f"duguje {format_amount(st['duguje'])}" + ("" if st["slaze"] else " (does NOT match the konto's sum)")
                  + (f", {st['van_perioda']} outside the month left out" if st["van_perioda"] else ""))
        ctx.update(value)
    if missing:
        e["napomena"] = f"Pojedinačni iznosi nisu pročitani za konta {', '.join(missing)} (nisu prikazana u tabeli)."
    elif e["konta_potpuna"] is False:
        e["napomena"] = "Tabela na sajtu nije prikazala sva konta: pojedinačni iznosi su pročitani samo za prikazana konta."


def _items(value: dict, e: dict, k: dict, card: dict) -> dict:
    """The card's rows -> the konto's individual entries in the month, with sums checked against the konto."""
    first, last = (f"{d[6:]}-{d[3:5]}-{d[:2]}" for d in (e["od"], e["do"]))
    rows, outside = [], 0
    for row in card["redovi"]:
        date = sinteticka.card_date(row.get(card["datum"], "")) if card["datum"] else ""
        if date and not first <= date <= last:
            outside += 1  # the card showed more than the month (e.g. the whole year)
            continue
        duguje = sinteticka.card_amount(row.get(card["duguje"], "")) if card["duguje"] else 0.0
        potrazuje = sinteticka.card_amount(row.get(card["potrazuje"], "")) if card["potrazuje"] else 0.0
        rows.append({"kolone": row, "duguje": duguje, "potrazuje": potrazuje,
                     "iznos": round(_amount(value, duguje, potrazuje), 2)})
    sums = {key: round(sum(r[key] for r in rows), 2) for key in ("duguje", "potrazuje")}
    same = all(abs(sums[key] - k[key]) < 0.005 for key in ("duguje", "potrazuje") if card[key])
    return {"kolone": card["kolone"], "redovi": rows, "broj": len(rows), "van_perioda": outside, **sums,
            "kolona_duguje": card["duguje"], "kolona_potrazuje": card["potrazuje"], "kolona_datum": card["datum"],
            "slaze": same, "greska": ""}


def _totals(value: dict) -> None:
    done = [e for e in value["meseci"] if e["status"] == "ok"]
    total = round(sum(e["promet"] for e in done), 2)
    limit = value["limit"]
    value["ukupno"] = {
        "promet": total,
        "izuzeto": round(sum(e["izuzeto"] for e in done), 2),
        "osnova": round(sum(e["osnova"] for e in done), 2),
        "potrazuje": round(sum(e["potrazuje"] for e in done), 2),
        "meseci": len(done),
    }
    value["preostalo"] = round(limit - total, 2)
    value["procenat"] = round(total / limit * 100, 1) if limit else 0.0
    value["prekoracen"] = total > limit
    value["potpun"] = len(done) == len(value["meseci"])


# --- settings ------------------------------------------------------------------------------------


def check_settings(values: dict) -> dict:
    """Check and normalize the settings from the page (raises ValueError with a message for the user)."""
    out = dict(values)
    for key, label in (("konto_od", "Konto od"), ("konto_do", "Konto do")):
        out[key] = str(values.get(key) or "").strip()
        if not out[key] or re.search(r"\s", out[key]):
            raise ValueError(f"„{label}“: upišite jedno konto (bez razmaka), npr. 6.")
    if out["konto_od"] > out["konto_do"]:
        raise ValueError(f"„Konto od“ ({out['konto_od']}) dolazi posle „Konto do“ ({out['konto_do']}).")
    excluded = excluded_list(str(values.get("izuzeta") or ""))
    outside = [k for k in excluded if not out["konto_od"] <= k <= out["konto_do"]]
    if outside:
        raise ValueError(f"Izuzeto konto {', '.join(outside)} nije između {out['konto_od']} i {out['konto_do']}.")
    out["izuzeta"] = ", ".join(excluded)
    limit = parse_amount(str(values.get("limit") or ""))
    if limit is None or limit <= 0:
        raise ValueError("„Limit“: upišite iznos, npr. 8.000.000,00.")
    out["limit"] = format_amount(limit)
    try:
        months = int(str(values.get("meseci") or "").strip())
    except ValueError:
        months = 0
    if not 1 <= months <= MAX_MONTHS:
        raise ValueError(f"„Broj meseci“: od 1 do {MAX_MONTHS}.")
    out["meseci"] = str(months)
    out["tekuci"] = bool(values.get("tekuci"))
    out["stavke"] = bool(values.get("stavke"))
    out["klijenti"] = bool(values.get("klijenti"))
    for key, options in (("datum", tuple(DATE_FIELDS)), ("iznos", (CREDIT, NET))):
        if values.get(key) not in options:
            raise ValueError(f"Nepoznata vrednost „{values.get(key)}“.")
    return out


def csv_rows(value: dict) -> list[list]:
    main = value.get("kolona", "Potražuje 6-7")
    rows = [["Mesec", "Od", "Do", main, (f"Konto {value['izuzet_konto']} (izuzeto)" if value.get("izuzet_konto") else "Izuzeto"), "Promet", "Status", "Napomena"]]
    for e in value["meseci"]:
        amount = lambda k: format_amount(e[k]) if e.get(k) is not None else ""
        rows.append([e["naziv"], e["od"], e["do"], amount("osnova"), amount("izuzeto"), amount("promet"),
                     e["status"], e["napomena"]])
    t = value["ukupno"]
    rows.append(["Ukupno", "", "", format_amount(t["osnova"]), format_amount(t["izuzeto"]), format_amount(t["promet"]),
                 "", ""])
    rows.append(["Limit (Zakon o PDV)", "", "", "", "", format_amount(value["limit"]), "", ""])
    rows.append(["Preostalo do limita", "", "", "", "", format_amount(value["preostalo"]), "", ""])
    rows.extend([[n] for n in value["napomene"]])
    items = item_rows(value)
    if items:
        rows += [[], ["Pojedinačni iznosi"]] + items
    if value.get("po_klijentima"):
        rows += [[], ["Po klijentima"], ["Komitent", "Naziv", "Promet", "Izuzeto", "Broj računa", "Iznos računa"]]
        rows += [[c["sifra"], c["naziv"], format_amount(c["promet"]), format_amount(c["izuzeto"]), c["broj_racuna"],
                  format_amount(c["iznos_racuna"])] for c in value["po_klijentima"]]
    return rows


def item_konta(value: dict) -> list[tuple[dict, dict]]:
    """(month, konto) pairs whose individual entries were asked for (setting "Pojedinačni iznosi po kontu")."""
    return [(e, k) for e in value["meseci"] for k in e.get("konta", []) if k.get("stavke")]


def item_columns(value: dict) -> list[str]:
    return list(dict.fromkeys(c for _, k in item_konta(value) for c in k["stavke"].get("kolone", [])))


def item_rows(value: dict) -> list[list]:
    """Every konto's individual entries: a header row, then month, konto, the card's columns, Iznos, note.
    [] when none were read."""
    konta = item_konta(value)
    if not konta:
        return []
    columns = item_columns(value)
    rows = [["Mesec", "Konto", *columns, "Iznos", "Napomena"]]
    for e, k in konta:
        st = k["stavke"]
        if st.get("greska"):
            rows.append([e["naziv"], k["konto"], *[""] * len(columns), "", st["greska"]])
            continue
        for r in st["redovi"]:
            rows.append([e["naziv"], k["konto"], *[r["kolone"].get(c, "") for c in columns], format_amount(r["iznos"]), ""])
        if not st["slaze"]:
            rows.append([e["naziv"], k["konto"], *[""] * len(columns), "", mismatch_note(k)])
    return rows


def mismatch_note(k: dict) -> str:
    st = k["stavke"]
    return (f"Zbir pojedinačnih iznosa (duguje {format_amount(st['duguje'])}, potražuje {format_amount(st['potrazuje'])}) "
            f"se ne slaže sa kontom (duguje {format_amount(k['duguje'])}, potražuje {format_amount(k['potrazuje'])}).")


def pdf(result: dict) -> bytes:
    from tim_automation.reports import turnover_export
    return turnover_export.pdf(result)


def excel(workbook, result: dict) -> None:
    from tim_automation.reports import turnover_export
    turnover_export.excel(workbook, result)


from tim_automation.reports import ReportType, Setting, report_type  # noqa: E402

SETTINGS = [
    Setting("konto_od", "Konto od", "text", "6", help="Pretraga konta „Između“ od – do (kako ih poredi sajt)."),
    Setting("konto_do", "Konto do", "text", "65"),
    Setting("izuzeta", "Izuzeta konta", "text", "6050",
            help="Ne ulaze u promet, prikazuju se posebno (i podkonta). Više konta odvojite zarezom."),
    Setting("limit", "Limit (RSD)", "number", "8.000.000,00", help="Limit iz Zakona o PDV."),
    Setting("meseci", "Broj meseci", "number", "12", help=f"Koliko poslednjih meseci (1–{MAX_MONTHS})."),
    Setting("tekuci", "Uključi tekući mesec", "bool", True, help="Isključeno: poslednji završeni meseci."),
    Setting("stavke", "Pojedinačni iznosi po kontu", "bool", False,
            help="Za svako konto otvara njegovu karticu (klik na konto) i čita pojedinačne iznose; traje duže."),
    Setting("klijenti", "Računi veleprodaje po klijentima", "bool", False,
            help="Za svaku godinu čita izlazne račune veleprodaje iz perioda (podaci, stavke i konta finansijskog "
                 "naloga) i grupiše promet po klijentima. Uključuje i pojedinačne iznose; traje dugo."),
    Setting("datum", "Mesec određuje", "select", "Datum stavke naloga", tuple(DATE_FIELDS)),
    Setting("iznos", "Iznos", "select", CREDIT, (CREDIT, NET),
            help="„Potražuje − Duguje“ oduzima storna, ali i zatvaranje klasa 31.12."),
]
SETTING_DEFAULTS = {s.name: s.default for s in SETTINGS}

report_type(ReportType(
    id="promet_12_meseci",
    title="Promet u poslednjih 12 meseci",
    description="Promet za limit iz Zakona o PDV po mesecima, iz popisa salda analitike (sintetika), bez izuzetih "
                "konta (izvoz usluga). Konta, limit, period i ostalo podešavate dugmetom ⚙.",
    run=run,
    csv_rows=csv_rows,
    pdf=pdf,
    excel=excel,
    settings=SETTINGS,
    check_settings=check_settings,
    notes=[
        "Meseci prethodne godine se čitaju posle otvaranja firme u toj godini, pa se na kraju ponovo otvara vaša godina.",
        "Podrazumevano: konta 6–65, Potražuje, po datumu stavke naloga, bez konta 6050 (izvoz usluga nije predmet PDV-a), "
        "poslednjih 12 meseci sa tekućim, limit 8.000.000,00 RSD.",
    ],
))
