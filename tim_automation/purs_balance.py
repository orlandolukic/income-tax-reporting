"""Sending an ePorezi "Упит стања" request and recording / watching it: used by the task "Upit stanja" and by the
PURS page ("Zatraži sintetiku" / "Zatraži analitiku"). Runs as an item of the PURS queue (its worker thread, the ePorezi
browser, the taxpayer already chosen); the report is then checked for in the queue's rounds (purs_reports.watch).

When the site makes no new report (one of a type, and group, per day), today's request of that type is used instead:
its saved file, or it is watched and downloaded once."""
import time

from tim_automation import purs_reports
from tim_automation.pages import purs


def request(driver, kind: str, group: str = "", email: str = "", *, log=print, progress=lambda text: None,
            check_cancel=lambda: None, job_name: str = "", firma: tuple[str | None, str] | None = None) -> dict:
    """{"request": the recorded request, "done": the watcher's event (None when the report is already here), "sent":
    what the site showed, "reused": True when today's earlier report is the answer, "today": its table row}.
    `firma` = (key, label) of the TiM company the request belongs to (default: the one open now)."""
    group = group if kind == purs.ANALYTICAL else ""
    firma = firma or purs_reports.current_company()
    purs.open_tab(driver)
    sent = purs.send_balance_request(driver, kind, group, email.strip(), log=log, progress=progress,
                                     check_cancel=check_cancel)
    taxpayer = getattr(driver, purs.TAXPAYER_ATTR, {}) or {}
    kod = purs.BALANCE_TYPES[kind][1] + (f"-{purs.BALANCE_GROUPS[group]}" if group else "")
    today = None if sent["id"] else todays_request(sent.get("danasnji") or [], kind, group, log, firma[0])
    reused = False
    if today:  # the site made no new report: this type's report of today is the answer
        site_id = today["id"]
        entry = purs_reports.find(site_id, firma[0])
        reused = True
        log(f"No new request: ePorezi already has today's {kind}{f' / {group}' if group else ''} report, "
            f"ID {site_id}" + (f" (saved here as {entry['fajl']})" if entry.get("fajl") else ""))
        if not entry:
            entry = purs_reports.add({"Tip zahteva": kind, "Grupa": group, "kod": kod, "PIB": taxpayer.get("PIB", ""),
                                      "Naziv": taxpayer.get("Naziv", ""), "red": today.get("red") or {},
                                      "posao": job_name, "sajt_id": site_id,
                                      "napomena": "Izveštaj ovog tipa za danas je već postojao na ePorezima."}, firma)
        purs_reports._update(entry["id"], ponovo_trazen=time.time())
        done = purs_reports.waiting(entry["id"])
        if entry.get("status") == purs_reports.DONE and entry.get("fajl"):
            done = None
        elif done is None:  # not downloaded and not watched (e.g. after a restart): watch it by its ID
            purs_reports._update(entry["id"], status=purs_reports.WAITING, greska="")
            done = purs_reports.watch(entry["id"], site_id=site_id, pib=taxpayer.get("PIB", ""))
    elif not sent["id"] and sent.get("danasnji") and sent.get("poruka"):
        # Refused, and today's requests of this type can't be used (another group, or one that can't be told).
        raise ValueError(f"ePorezi nije prihvatio zahtev: {sent['poruka']}. Danas već postoji zahtev ovog tipa (ID "
                         f"{', '.join(r['id'] for r in sent['danasnji'])}), ali nije iste grupe ili se to ne vidi u "
                         "tabeli (poslat je ručno).")
    else:
        entry = purs_reports.add({
            "Tip zahteva": kind, "Grupa": group, "kod": kod,
            "PIB": taxpayer.get("PIB", ""), "Naziv": taxpayer.get("Naziv", ""), "red": sent["red"],
            "posao": job_name, "sajt_id": sent["id"],
        }, firma)
        done = purs_reports.watch(entry["id"], sent["stari_link"], site_id=sent["id"], before_ids=sent["pre"],
                                  pib=taxpayer.get("PIB", ""))
        log(f"Request {sent['id'] or entry['id']} sent; its report is checked for in the PURS queue")
    return {"request": entry, "done": done, "sent": sent, "reused": reused, "today": today}


def todays_request(rows: list[dict], kind: str, group: str, log, firma: str | None = None) -> dict | None:
    """Of today's rows of this type in the ePorezi table (newest first), the one to use instead of a new request. An
    analytical one only with the same group: shown in the row, else known from our own record of that ID."""
    for row in rows:
        record = purs_reports.find(row["id"], firma)
        if record and (record.get("Tip zahteva") or kind) != kind:
            continue
        if group:
            same = row["grupa"] if row["grupa"] is not None else (record.get("Grupa") == group if record else None)
            if not same:
                if same is None:
                    log(f"Today's request {row['id']}: its group can't be told (not in the row, not sent from here)")
                continue
        return row
    return None
