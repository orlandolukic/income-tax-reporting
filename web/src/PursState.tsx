import { Fragment, useEffect, useState } from "react";
import { callApi, PursLogin, PursRequest, PursState } from "./api";
import { formatTime } from "./jobs/common";

type Balance = {
  duguje: number | null;
  potrazuje: number | null;
  naplacena_kamata: number | null;
  osnovni_dug: number | null;
  kamata: number | null;
  ukupan_dug: number | null;
};

type Analytic = {
  zahtev: string;
  sajt_id: string;
  grupa: string;
  stanje_na_dan: string;
  poslato: number;
  pozivi: { poziv_na_broj: string; opstina: string; opis_racuna: string; stavki: number; stanje: Balance | null; slaze: boolean }[];
};

/** One row of the synthetic report under its konto: a Poziv na broj (or the konto's only row, per opština). */
type SyntheticRow = {
  poziv_na_broj: string;
  izvor: string;
  sifra_opstine: string;
  opstina: string;
  datum_stanja: string;
  vrednosti: Record<string, number | null>;
  analitika: { zahtev: string; sajt_id: string; grupa: string; ukupan_dug: number | null; stavki: number }[];
};

type Account = {
  racun: string; // the konto
  opis: string;
  grupa: string;
  vrednosti: Record<string, number | null>;
  redova: number;
  pozivi: SyntheticRow[];
};

/** `/api/purs/stanje` (tim_automation/purs_reports.py `state`). */
type TaxState = {
  sintetika:
    | null
    | {
        zahtev: PursRequest;
        danas?: boolean;
        greska?: string;
        zaglavlje?: { stanje_na_dan?: string; datum_stampanja?: string };
        kolone?: string[];
        racuni?: Account[];
        ukupno?: Record<string, number>;
        ukupno_izvestaj?: Record<string, number | null>;
        provera?: { slaze: boolean; problemi: string[] };
      };
  ceka: PursRequest | null;
  analitika: Record<string, Analytic[]>;
  grupe: Record<string, string>; // račun -> fiscal group of its analytical report (known or a guess)
};

const SYNTHETIC = "Sintetika u PDF formatu";
const ANALYTICAL = "Analitika za fiskalnu grupu u PDF formatu";
const GROUPS = ["AKC", "OST", "PDP", "PDV", "PID", "PNP", "PPAP", "PPFL", "PPSD", "PRO", "SPID"];

const money = (v: number | null | undefined) =>
  v == null ? "" : v.toLocaleString("sr-Latn", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function Amount({ value, balance }: { value: number | null | undefined; balance?: boolean }) {
  if (value == null) return <span className="muted">—</span>;
  if (!balance) return <>{money(value)}</>;
  const tone = value > 0.004 ? "debt" : value < -0.004 ? "credit" : "zero";
  return <span className={`balance b-${tone}`}>{money(value)}</span>;
}

/** A column that is a balance (debt > 0, overpayment < 0): coloured. */
const isBalance = (column: string) => /\bdug\b|saldo|stanje/i.test(column);

/** A konto's own rows in the synthetic report (one per Poziv na broj / opština), with a link to the analytical one. */
function SyntheticRows(props: { account: Account; columns: string[]; showZeros: boolean; onShowZeros: () => void }) {
  const { account, columns, showZeros } = props;
  const zero = (p: SyntheticRow) => columns.every((c) => !p.vrednosti[c]);
  // Only a long list (e.g. konto 4, Objedinjena naplata: 23 rows, mostly 0,00) hides its zero rows.
  const zeros = account.pozivi.length > 5 ? account.pozivi.filter(zero).length : 0;
  const rows = showZeros || !zeros || zeros === account.pozivi.length ? account.pozivi : account.pozivi.filter((p) => !zero(p));
  return (
    <div className="tax-analytic">
      <div className="tax-analytic-head">
        <strong>Sintetika po pozivu na broj</strong>
        <span className="muted small">{account.pozivi.length} redova</span>
        {zeros > 0 && zeros < account.pozivi.length && (
          <button className="link small" onClick={props.onShowZeros}>
            {showZeros ? `Sakrij redove sa nulom (${zeros})` : `Prikaži i redove sa nulom (${zeros})`}
          </button>
        )}
      </div>
      <table className="tax-analytic-table">
        <thead>
          <tr>
            <th>Poziv na broj</th>
            <th>Opština</th>
            <th>Izvor</th>
            <th>Datum stanja</th>
            {columns.map((c) => (
              <th key={c} className="num">
                {c}
              </th>
            ))}
            <th>Analitika</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p, i) => (
            <tr key={`${p.poziv_na_broj}-${i}`}>
              <td className="nowrap">{p.poziv_na_broj || "—"}</td>
              <td className="nowrap">
                {p.sifra_opstine && <span className="muted">{p.sifra_opstine} </span>}
                {p.opstina}
              </td>
              <td>{p.izvor}</td>
              <td className="nowrap">{p.datum_stanja}</td>
              {columns.map((c) => (
                <td key={c} className="num">
                  <Amount value={p.vrednosti[c]} balance={isBalance(c)} />
                </td>
              ))}
              <td className="nowrap">
                {p.analitika.length ? (
                  p.analitika.map((an) => {
                    const same = an.ukupan_dug != null && Math.abs(an.ukupan_dug - (p.vrednosti["Ukupan dug"] ?? 0)) < 0.005;
                    return (
                      <a key={an.zahtev} href={`#/purs/${an.zahtev}/knjizenje`}
                        title={`Analitika ${an.grupa} (ID ${an.sajt_id}): ${an.stavki} stavki, ukupan dug ${money(an.ukupan_dug)}`}>
                        {same ? "✓ " : "≠ "}Knjiženje
                      </a>
                    );
                  })
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** "Stanje kod Poreske uprave": the newest synthetic report's accounts; an account opens its analytical values. */
export function TaxStatePanel({ purs, login }: { purs: PursState | undefined; login: PursLogin | undefined }) {
  const [data, setData] = useState<TaxState | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [groupFor, setGroupFor] = useState<Record<string, string>>({});
  const [existingId, setExistingId] = useState("");
  const [zeros, setZeros] = useState<Record<string, boolean>>({});
  // Reload whenever a request changes (sent, downloaded) for this company.
  const version = (purs?.zahtevi ?? []).map((r) => `${r.id}:${r.status}:${r.fajl}`).join("|") + (purs?.firma ?? "");
  useEffect(() => {
    if (!purs?.firma) return;
    callApi<TaxState>("purs", "stanje", {})
      .then((d) => (setData(d), setError("")))
      .catch((e) => setError(String(e.message ?? e)));
  }, [version, purs?.firma]);

  if (!purs?.firma) return null;
  const busy = login?.stanje === "radi";
  const requesting = busy && login?.akcija === "request";
  const ready = !!login?.spremno;
  const ask = (vrsta: string, grupa = "") =>
    callApi("purs-login", "request", { vrsta, grupa })
      .then(() => setError(""))
      .catch((e) => setError(String(e.message ?? e)));
  const blocker = !ready ? "Moguće kad je firma otvorena i program spreman." : busy ? "Sačekajte da se završi prijava / zahtev." : "";
  const s = data?.sintetika;
  const waiting = data?.ceka;
  const accounts = s?.racuni ?? [];
  const columns = s?.kolone ?? [];
  const useExisting = () =>
    callApi("purs", "postojeci", { sajt_id: existingId, vrsta: SYNTHETIC })
      .then(() => (setExistingId(""), setError("")))
      .catch((e) => setError(String(e.message ?? e)));
  const existingForm = (
    <form
      className="tax-existing"
      onSubmit={(e) => {
        e.preventDefault();
        useExisting();
      }}
      title="Izveštaj koji je već napravljen na ePorezima (npr. ručno): upišite njegov ID iz tabele „Упит стања“. Ništa se ne šalje; ako nije preuzet ovde, preuzima se (ePorezi mora biti prijavljen sa ovom firmom)."
    >
      <span className="muted small">ili postojeći izveštaj, ID</span>
      <input value={existingId} onChange={(e) => setExistingId(e.target.value)} placeholder="npr. 36452606" inputMode="numeric"
        size={11} aria-label="ID postojećeg izveštaja" />
      <button type="submit" disabled={!/^\s*\d+\s*$/.test(existingId) || !!waiting}>
        Koristi
      </button>
    </form>
  );
  const requestButton = (label: string) => (
    <button className="primary" disabled={!!blocker || !!waiting} title={blocker || (waiting ? "Sintetika se već čeka." : "")}
      onClick={() => ask(SYNTHETIC)}>
      {label}
    </button>
  );

  return (
    <section className="tax-state">
      <div className="tax-state-head">
        <h3>Stanje kod Poreske uprave</h3>
        {s && !s.greska && (
          <span className="muted small">
            Sintetika ID {s.zahtev.sajt_id}
            {s.zaglavlje?.stanje_na_dan && ` · stanje na dan ${s.zaglavlje.stanje_na_dan}`}
            {` · preuzeta ${formatTime(s.zahtev.zavrseno ?? s.zahtev.poslato)}`}
          </span>
        )}
        {s?.provera &&
          (s.provera.slaze ? (
            <span className="ok-mark small" title="Zbir svih redova = red „Ukupno“ iz izveštaja">✓ zbir se slaže</span>
          ) : (
            <span className="error small" title={s.provera.problemi.join("\n")}>! {s.provera.problemi.join("; ")}</span>
          ))}
        <span className="spacer" />
        {s && !s.danas && !waiting && requestButton("Zatraži današnju sintetiku")}
        {s && !waiting && existingForm}
      </div>
      {error && <p className="error small">{error}</p>}
      {requesting && (
        <p className="tax-state-note">
          <span className="spinner small" /> {login?.napredak || "Slanje zahteva..."}
        </p>
      )}
      {login?.akcija === "request" && !busy && login.poruka &&
        // the page's last request: its error, or its note while that report is still awaited
        (login.stanje === "greska" || purs.zahtevi.some((r) => r.id === login.zahtev && r.status === "ceka")) && (
          <p className={`tax-state-note ${login.stanje === "greska" ? "error" : "muted"}`}>{login.poruka}</p>
        )}
      {waiting && (
        <p className="tax-state-note">
          <span className="spinner small" /> Sintetika se čeka{waiting.sajt_id ? ` (ID ${waiting.sajt_id})` : ""}: program je
          preuzima čim ePorezi napravi izveštaj.
        </p>
      )}
      {!data ? (
        !error && (
          <p className="muted small">
            <span className="spinner small" /> Učitavanje…
          </p>
        )
      ) : !s ? (
        !waiting && (
          <div className="tax-state-empty">
            <p>Sintetika još nije preuzeta. Zahtev se šalje na ePorezima („Upit stanja“ → „Sintetika u PDF formatu“).</p>
            {requestButton("Zatraži sintetiku")}
            {existingForm}
          </div>
        )
      ) : s.greska || !accounts.length ? (
        <p className="error small">
          Sintetika (ID {s.zahtev.sajt_id}) nije pročitana{s.greska ? `: ${s.greska}` : ": u PDF-u nije prepoznata tabela računa"}.{" "}
          <a href={`#/purs/${s.zahtev.id}/sadrzaj`}>Pogledajte sadržaj PDF-a</a>
        </p>
      ) : (
        <div className="table-wrap tall">
          <table className="turnover-table tax-accounts">
            <thead>
              <tr>
                <th className="purs-toggle-cell" />
                <th>Konto</th>
                <th>Opis</th>
                <th className="num" title="Broj redova (poziva na broj / opština) u sintetici">Pozivi</th>
                {columns.map((c) => (
                  <th key={c} className="num">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => {
                const analytic = data.analitika[a.racun] ?? [];
                const expanded = !!open[a.racun];
                const toggle = () => setOpen((o) => ({ ...o, [a.racun]: !o[a.racun] }));
                const group = groupFor[a.racun] ?? data.grupe[a.racun] ?? "";
                return (
                  <Fragment key={a.racun}>
                    <tr className="expandable" onClick={(e) => !(e.target as HTMLElement).closest("button, a, select") && toggle()}>
                      <td className="purs-toggle-cell">
                        <button className="purs-toggle" aria-expanded={expanded} title="Analitika ovog računa" onClick={toggle}>
                          {expanded ? "▾" : "▸"}
                        </button>
                      </td>
                      <td className="strong nowrap">{a.racun}</td>
                      <td>
                        {a.opis}
                        {a.grupa && <span className="muted small"> · {a.grupa}</span>}
                        {a.redova === 1 && a.pozivi[0] && (
                          <div className="muted small">
                            {[a.pozivi[0].poziv_na_broj && `poziv ${a.pozivi[0].poziv_na_broj}`, a.pozivi[0].opstina,
                              a.pozivi[0].izvor].filter(Boolean).join(" · ")}
                          </div>
                        )}
                      </td>
                      <td className="num">{a.redova > 1 ? a.redova : ""}</td>
                      {columns.map((c) => (
                        <td key={c} className="num">
                          <button className="link tax-value" title="Prikaži analitiku" onClick={toggle}>
                            <Amount value={a.vrednosti[c]} balance={isBalance(c)} />
                          </button>
                        </td>
                      ))}
                    </tr>
                    {expanded && (
                      <tr className="tax-analytic-row">
                        <td />
                        <td colSpan={columns.length + 3}>
                          {a.redova > 1 && (
                            <SyntheticRows
                              account={a}
                              columns={columns}
                              showZeros={!!zeros[a.racun]}
                              onShowZeros={() => setZeros((z) => ({ ...z, [a.racun]: !z[a.racun] }))}
                            />
                          )}
                          {analytic.length === 0 ? (
                            <div className="tax-analytic-missing">
                              <span>Analitika za račun {a.racun} nije preuzeta.</span>
                              <label className="inline">
                                Fiskalna grupa
                                <select value={group} onChange={(e) => setGroupFor((g) => ({ ...g, [a.racun]: e.target.value }))}>
                                  <option value="">—</option>
                                  {GROUPS.map((g) => (
                                    <option key={g}>{g}</option>
                                  ))}
                                </select>
                              </label>
                              <button disabled={!!blocker || !group} title={blocker || (group ? "" : "Izaberite grupu")}
                                onClick={() => ask(ANALYTICAL, group)}>
                                Zatraži analitiku {group}
                              </button>
                              {data.grupe[a.racun] && !groupFor[a.racun] && (
                                <span className="muted small">(grupa je pretpostavka po broju računa; proverite)</span>
                              )}
                            </div>
                          ) : (
                            analytic.map((an) => (
                              <div key={an.zahtev} className="tax-analytic">
                                <div className="tax-analytic-head">
                                  <strong>Analitika {an.grupa}</strong>
                                  <span className="muted small">
                                    ID {an.sajt_id}
                                    {an.stanje_na_dan && ` · stanje na dan ${an.stanje_na_dan}`} · {formatTime(an.poslato)}
                                  </span>
                                  <a href={`#/purs/${an.zahtev}/knjizenje`}>Knjiženje →</a>
                                </div>
                                <table className="tax-analytic-table">
                                  <thead>
                                    <tr>
                                      <th>Poziv na broj</th>
                                      <th>Opština</th>
                                      <th className="num">Stavki</th>
                                      <th className="num">Duguje</th>
                                      <th className="num">Potražuje</th>
                                      <th className="num">Nap. kamata</th>
                                      <th className="num">Osnovni dug</th>
                                      <th className="num">Kamata</th>
                                      <th className="num">Ukupan dug</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {an.pozivi.map((p) => (
                                      <tr key={p.poziv_na_broj}>
                                        <td className="nowrap">
                                          {p.poziv_na_broj}
                                          {!p.slaze && <span className="error" title="Zbir stavki se ne slaže sa „Ukupno“"> !</span>}
                                        </td>
                                        <td className="nowrap">{p.opstina}</td>
                                        <td className="num">{p.stavki}</td>
                                        <td className="num"><Amount value={p.stanje?.duguje} /></td>
                                        <td className="num"><Amount value={p.stanje?.potrazuje} /></td>
                                        <td className="num"><Amount value={p.stanje?.naplacena_kamata} /></td>
                                        <td className="num"><Amount value={p.stanje?.osnovni_dug} /></td>
                                        <td className="num"><Amount value={p.stanje?.kamata} /></td>
                                        <td className="num strong"><Amount value={p.stanje?.ukupan_dug} balance /></td>
                                      </tr>
                                    ))}
                                  </tbody>
                                  {an.pozivi.length > 1 && (
                                    <tfoot>
                                      <tr>
                                        <td colSpan={3}>Ukupno ({an.pozivi.length} poziva na broj)</td>
                                        {(["duguje", "potrazuje", "naplacena_kamata", "osnovni_dug", "kamata", "ukupan_dug"] as const).map((k) => (
                                          <td key={k} className="num">
                                            <Amount
                                              value={Math.round(an.pozivi.reduce((sum, p) => sum + (p.stanje?.[k] ?? 0), 0) * 100) / 100}
                                              balance={k === "ukupan_dug"}
                                            />
                                          </td>
                                        ))}
                                      </tr>
                                    </tfoot>
                                  )}
                                </table>
                              </div>
                            ))
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
            {accounts.length > 1 && (
              <tfoot>
                <tr>
                  <td />
                  <td colSpan={3}>Ukupno</td>
                  {columns.map((c) => (
                    <td key={c} className="num">
                      <Amount value={s.ukupno?.[c]} balance={isBalance(c)} />
                    </td>
                  ))}
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </section>
  );
}
