import { Fragment, useEffect, useMemo, useState } from "react";
import { callApi, PursRequest } from "./api";

/** One entry of an analytical report (tim_automation/purs_analytics.py). */
type Entry = {
  datum: string;
  opis: string;
  dokument: string;
  dokument_dodatak: string;
  period: string;
  vrsta: string;
  strana: number;
  duguje: number | null;
  potrazuje: number | null;
  kamata: number | null;
  nap_kamata: number | null;
  osn_dug: number | null;
  kamata_stanje: number | null;
};

type Totals = { duguje: number | null; potrazuje: number | null; kamata: number | null; nap_kamata: number | null };

type State = {
  duguje: number | null;
  potrazuje: number | null;
  naplacena_kamata: number | null;
  osnovni_dug: number | null;
  kamata: number | null;
  ukupan_dug: number | null;
};

type Poziv = {
  racun: string;
  poziv_na_broj: string;
  izvor: string;
  opstina: string;
  opis_racuna: string;
  stavke: Entry[];
  ukupno: Totals | null;
  zbir_stavki: Totals;
  stanje: State | null;
  strane: number[];
  provera: { slaze: boolean; problemi: string[] };
};

type Analytics = {
  zaglavlje: { stanje_na_dan?: string; datum_stampanja?: string; pib?: string; naziv?: string; sediste?: string; status?: string };
  pozivi: Poziv[];
  ukupno: State;
  upozorenja: string[];
  broj_strana: number;
  broj_stavki: number;
};

const money = (v: number | null | undefined, empty = "") =>
  v == null ? empty : v.toLocaleString("sr-Latn", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fold = (text: string) =>
  text.toLowerCase().replace(/đ/g, "dj").normalize("NFD").replace(/[̀-ͯ]/g, "");

const fileUrl = (r: PursRequest) => `/files/purs/${encodeURIComponent(r.fajl)}`;

/** Debt (positive) / overpayment (negative) with its colour. */
function Balance({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="muted">—</span>;
  const tone = value > 0.004 ? "debt" : value < -0.004 ? "credit" : "zero";
  return (
    <span className={`balance b-${tone}`} title={tone === "debt" ? "Dug" : tone === "credit" ? "Preplata" : "Izmireno"}>
      {money(value)}
    </span>
  );
}

function csv(report: Analytics): string {
  const num = (v: number | null) => (v == null ? "" : v.toFixed(2).replace(".", ","));
  const q = (t: string) => `"${t.replace(/"/g, '""')}"`;
  const lines = [
    ["Račun", "Poziv na broj", "Opština", "Datum", "Vrsta", "Opis", "Dokument", "Period", "Duguje", "Potražuje", "Kamata",
      "Nap. kamata", "Osn. dug (stanje)", "Kamata (stanje)"].join(";"),
  ];
  for (const p of report.pozivi)
    for (const e of p.stavke)
      lines.push(
        [q(p.racun), q(p.poziv_na_broj), q(p.opstina), e.datum, q(e.vrsta), q(e.opis), q(e.dokument), q(e.period),
          num(e.duguje), num(e.potrazuje), num(e.kamata), num(e.nap_kamata), num(e.osn_dug), num(e.kamata_stanje)].join(";"),
      );
  return "﻿" + lines.join("\r\n");
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function useReport<T>(action: string, id: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setData(null);
    setError("");
    callApi<T>("purs", action, { id })
      .then(setData)
      .catch((e) => setError(String(e.message ?? e)));
  }, [action, id]);
  return { data, error };
}

function Head({ request, title, children }: { request: PursRequest | undefined; title: string; children?: React.ReactNode }) {
  return (
    <div className="purs-report-head">
      <a href="#/purs" className="back-link">
        ‹ PURS
      </a>
      <h2>
        {title}
        {request?.Grupa ? ` · ${request.Grupa}` : ""}
      </h2>
      <div className="purs-report-meta muted small">
        {request?.sajt_id && <span>ID zahteva {request.sajt_id}</span>}
        {children}
      </div>
    </div>
  );
}

/** "Knjiženje": an analytical report taken apart: every Poziv na broj with its entries, totals and balance. */
export function AnalyticsPage({ id }: { id: string }) {
  const { data, error } = useReport<{ zahtev: PursRequest; izvestaj: Analytics }>("analitika", id);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const report = data?.izvestaj;
  const kinds = useMemo(
    () => [...new Set(report?.pozivi.flatMap((p) => p.stavke.map((e) => e.vrsta)) ?? [])].sort(),
    [report],
  );
  if (error)
    return (
      <div className="card">
        <Head request={undefined} title="Knjiženje" />
        <p className="error">{error}</p>
      </div>
    );
  if (!data || !report)
    return (
      <div className="card working">
        <span className="spinner" /> Čitanje PDF izveštaja…
      </div>
    );
  const z = report.zaglavlje;
  const words = fold(query.trim()).split(/\s+/).filter(Boolean);
  const visible = (p: Poziv, e: Entry) => {
    if (kind && e.vrsta !== kind) return false;
    if (!words.length) return true;
    const text = fold([p.poziv_na_broj, e.datum, e.vrsta, e.opis, e.dokument, e.period, money(e.duguje), money(e.potrazuje)].join(" "));
    return words.every((w) => text.includes(w));
  };
  const filtered = !!(words.length || kind);
  const total = report.ukupno;
  return (
    <div className="card purs-report">
      <Head request={data.zahtev} title="Knjiženje">
        {z.stanje_na_dan && <span>Stanje na dan {z.stanje_na_dan}</span>}
        {z.datum_stampanja && <span>Štampano {z.datum_stampanja}</span>}
        <span>
          {report.broj_strana} str. · {report.pozivi.length} poziva na broj · {report.broj_stavki} stavki
        </span>
      </Head>
      <div className="purs-report-taxpayer">
        <strong>{z.naziv}</strong>
        <span className="muted">
          {z.pib && ` · PIB ${z.pib}`}
          {z.sediste && ` · ${z.sediste}`}
          {z.status && ` · ${z.status}`}
        </span>
        <span className="spacer" />
        <a className="button" href={fileUrl(data.zahtev)} target="_blank" rel="noreferrer">
          📄 PDF
        </a>
        <button onClick={() => download(`knjizenje-${data.zahtev.sajt_id || id}.csv`, csv(report))}>CSV</button>
      </div>

      {report.upozorenja.length === 0 ? (
        <p className="purs-check ok">✓ Zbir stavki svakog poziva na broj se slaže sa redom „Ukupno“ iz izveštaja.</p>
      ) : (
        <div className="purs-check bad">
          <strong>Proverite:</strong>
          <ul>
            {report.upozorenja.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="home-tiles">
        <div className="home-tile">
          <div className="home-tile-label">Duguje</div>
          <div className="home-tile-value">{money(total.duguje)}</div>
        </div>
        <div className="home-tile">
          <div className="home-tile-label">Potražuje</div>
          <div className="home-tile-value">{money(total.potrazuje)}</div>
        </div>
        <div className="home-tile">
          <div className="home-tile-label">Naplaćena kamata</div>
          <div className="home-tile-value">{money(total.naplacena_kamata)}</div>
        </div>
        <div className="home-tile">
          <div className="home-tile-label">{(total.ukupan_dug ?? 0) < 0 ? "Ukupno: preplata" : "Ukupan dug"}</div>
          <div className="home-tile-value">
            <Balance value={total.ukupan_dug} />
          </div>
          <div className="home-tile-note">
            osnovni dug {money(total.osnovni_dug)} · kamata {money(total.kamata)}
          </div>
        </div>
      </div>

      <h3>Pozivi na broj</h3>
      <div className="table-wrap tall">
        <table className="turnover-table purs-calls">
          <thead>
            <tr>
              <th>Račun \ Poziv na broj</th>
              <th>Opština</th>
              <th className="num">Stavki</th>
              <th className="num">Duguje</th>
              <th className="num">Potražuje</th>
              <th className="num">Nap. kamata</th>
              <th className="num">Osnovni dug</th>
              <th className="num">Kamata</th>
              <th className="num">Ukupan dug</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {report.pozivi.map((p) => (
              <tr key={p.poziv_na_broj}>
                <td className="nowrap">
                  <a href={`#poziv-${p.poziv_na_broj}`} onClick={(e) => {
                    e.preventDefault();
                    setClosed((c) => ({ ...c, [p.poziv_na_broj]: false }));
                    setTimeout(() => document.getElementById(`poziv-${p.poziv_na_broj}`)?.scrollIntoView({ behavior: "smooth" }), 0);
                  }}>
                    {p.racun} \ <strong>{p.poziv_na_broj}</strong>
                  </a>
                  <div className="muted small">{p.opis_racuna}</div>
                </td>
                <td className="nowrap">{p.opstina}</td>
                <td className="num">{p.stavke.length}</td>
                <td className="num">{money(p.stanje?.duguje)}</td>
                <td className="num">{money(p.stanje?.potrazuje)}</td>
                <td className="num">{money(p.stanje?.naplacena_kamata)}</td>
                <td className="num">{money(p.stanje?.osnovni_dug)}</td>
                <td className="num">{money(p.stanje?.kamata)}</td>
                <td className="num strong">
                  <Balance value={p.stanje?.ukupan_dug} />
                </td>
                <td title={p.provera.slaze ? "Zbir stavki se slaže" : p.provera.problemi.join("\n")}>
                  {p.provera.slaze ? <span className="ok-mark">✓</span> : <span className="error">!</span>}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={2}>Ukupno</td>
              <td className="num">{report.broj_stavki}</td>
              <td className="num">{money(total.duguje)}</td>
              <td className="num">{money(total.potrazuje)}</td>
              <td className="num">{money(total.naplacena_kamata)}</td>
              <td className="num">{money(total.osnovni_dug)}</td>
              <td className="num">{money(total.kamata)}</td>
              <td className="num strong">
                <Balance value={total.ukupan_dug} />
              </td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>

      <div className="purs-filters">
        <input
          type="search"
          className="purs-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Pretraga stavki: datum, opis, dokument, iznos…"
          aria-label="Pretraga stavki"
        />
        <label className="inline">
          Vrsta
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Sve</option>
            {kinds.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </label>
        {filtered && (
          <button type="button" className="link" onClick={() => (setQuery(""), setKind(""))}>
            Očisti filtere
          </button>
        )}
      </div>

      {report.pozivi.map((p) => {
        const rows = p.stavke.filter((e) => visible(p, e));
        if (filtered && !rows.length) return null;
        const open = !closed[p.poziv_na_broj];
        return (
          <section key={p.poziv_na_broj} id={`poziv-${p.poziv_na_broj}`} className="purs-call">
            <button
              className="purs-call-head"
              aria-expanded={open}
              onClick={() => setClosed((c) => ({ ...c, [p.poziv_na_broj]: open }))}
            >
              <span className="purs-call-arrow">{open ? "▾" : "▸"}</span>
              <span>
                <span className="muted">Poziv na broj</span> <strong>{p.poziv_na_broj}</strong>
                <span className="muted small">
                  {" "}
                  · račun {p.racun} · {p.opis_racuna} · {p.opstina}
                  {p.izvor && ` · izvor ${p.izvor}`}
                  {p.strane.length > 1 && ` · strane ${p.strane.join(", ")}`}
                </span>
              </span>
              <span className="spacer" />
              <span className="small">
                {filtered ? `${rows.length} od ${p.stavke.length}` : `${p.stavke.length}`} stavki · ukupan dug{" "}
                <Balance value={p.stanje?.ukupan_dug} />
              </span>
            </button>
            {open && (
              <div className="table-wrap tall">
                <table className="turnover-table purs-entries">
                  <thead>
                    <tr>
                      <th>Datum</th>
                      <th>Vrsta</th>
                      <th>Opis</th>
                      <th>Dokument</th>
                      <th className="num">Duguje</th>
                      <th className="num">Potražuje</th>
                      <th className="num">Kamata</th>
                      <th className="num">Nap. kamata</th>
                      <th className="num" title="Trenutno stanje posle ove stavke: osnovni dug">
                        Stanje: osn. dug
                      </th>
                      <th className="num" title="Trenutno stanje posle ove stavke: kamata">
                        Stanje: kamata
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((e, i) => (
                      <tr key={i}>
                        <td className="nowrap">{e.datum}</td>
                        <td>
                          <span className={`purs-kind k-${fold(e.vrsta).replace(/\s+/g, "-")}`}>{e.vrsta}</span>
                        </td>
                        <td>{e.opis || <span className="muted">—</span>}</td>
                        <td>
                          {e.dokument}
                          {e.period && <div className="muted small">{e.period}</div>}
                          {!e.period && e.dokument_dodatak && <div className="muted small">{e.dokument_dodatak}</div>}
                        </td>
                        <td className="num">{money(e.duguje)}</td>
                        <td className="num">{money(e.potrazuje)}</td>
                        <td className="num">{money(e.kamata)}</td>
                        <td className="num">{money(e.nap_kamata)}</td>
                        <td className="num">{money(e.osn_dug)}</td>
                        <td className="num">{money(e.kamata_stanje)}</td>
                      </tr>
                    ))}
                  </tbody>
                  {!filtered && (
                    <tfoot>
                      <tr>
                        <td colSpan={4}>
                          Ukupno{" "}
                          {p.provera.slaze ? (
                            <span className="ok-mark" title="Zbir stavki = red „Ukupno“ iz izveštaja">✓</span>
                          ) : (
                            <span className="error" title={p.provera.problemi.join("\n")}>
                              ! {p.provera.problemi.join("; ")}
                            </span>
                          )}
                        </td>
                        <td className="num">{money(p.ukupno?.duguje)}</td>
                        <td className="num">{money(p.ukupno?.potrazuje)}</td>
                        <td className="num">{money(p.ukupno?.kamata)}</td>
                        <td className="num">{money(p.ukupno?.nap_kamata)}</td>
                        <td className="num">{money(p.stanje?.osnovni_dug)}</td>
                        <td className="num">{money(p.stanje?.kamata)}</td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}

/** Any other PDF (e.g. a synthetic report, whose layout is not known yet): its text and tables per page. */
export function ContentPage({ id }: { id: string }) {
  const { data, error } = useReport<{
    zahtev: PursRequest;
    sadrzaj: { broj_strana: number; strane: string[]; tabele: { strana: number; kolone: string[]; redovi: Record<string, string>[] }[] };
  }>("sadrzaj", id);
  if (error)
    return (
      <div className="card">
        <Head request={undefined} title="Sadržaj izveštaja" />
        <p className="error">{error}</p>
      </div>
    );
  if (!data)
    return (
      <div className="card working">
        <span className="spinner" /> Čitanje PDF izveštaja…
      </div>
    );
  const s = data.sadrzaj;
  return (
    <div className="card purs-report">
      <Head request={data.zahtev} title={data.zahtev["Tip zahteva"] || "Sadržaj izveštaja"}>
        <span>{s.broj_strana} str.</span>
        <a href={fileUrl(data.zahtev)} target="_blank" rel="noreferrer">
          📄 PDF
        </a>
      </Head>
      <p className="muted small">
        Raspored ovog izveštaja još nije poznat, pa je prikazan sav tekst i tabele koje se u PDF-u prepoznaju.
      </p>
      {s.strane.map((text, i) => (
        <Fragment key={i}>
          <h3>Strana {i + 1}</h3>
          {s.tabele
            .filter((t) => t.strana === i + 1)
            .map((t, j) => (
              <div className="table-wrap tall" key={j}>
                <table className="turnover-table">
                  <thead>
                    <tr>
                      {t.kolone.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {t.redovi.map((r, k) => (
                      <tr key={k}>
                        {t.kolone.map((c) => (
                          <td key={c}>{r[c]}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          <pre className="purs-text">{text}</pre>
        </Fragment>
      ))}
    </div>
  );
}
