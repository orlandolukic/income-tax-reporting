import { Fragment, ReactNode, useEffect, useRef, useState } from "react";
import { callApi, PursLogin, PursQueueState, PursRequest, PursState } from "./api";
import { PursQueue } from "./PursQueue";
import { TaxStatePanel } from "./PursState";
import { formatTime } from "./jobs/common";

const STATUS: Record<PursRequest["status"], string> = {
  ceka: "Čeka se",
  gotovo: "Stigao",
  greska: "Greška",
  prekinuto: "Prekinuto",
};

type Group = "sve" | "sintetika" | "analitika";
const GROUPS: [Group, string][] = [
  ["sve", "Sve"],
  ["sintetika", "Sintetika"],
  ["analitika", "Analitika"],
];

/** Which tab a request belongs to: by its type ("Nalog - upit stanja sintetički" is synthetic too), else (sent by
 * hand) by the type shown in its row of the ePorezi table. */
function groupOf(r: PursRequest): Group | "" {
  const text = [r.kod ?? "", r["Tip zahteva"], ...Object.values(r.red ?? {})].join(" ").toLowerCase();
  if (/analiti|аналити|analytical/.test(text)) return "analitika";
  if (/sinteti|синтети|synthetic|nalog-xml/.test(text)) return "sintetika";
  return "";
}

/** Fiscal groups of the analytical report (pages/purs.py BALANCE_GROUPS). */
const FISCAL_GROUPS: Record<string, string> = {
  AKC: "Akcize",
  OST: "Ostalo",
  PDP: "Porez na dobit preduzeća",
  PDV: "Porez na dodatu vrednost",
  PID: "Objedinjena naplata poreza i doprinosa",
  PNP: "Porez na nasleđe i poklon",
  PPAP: "Porez na prenos apsolutnih prava",
  PPFL: "Porez na prihod fizičkih lica",
  PPSD: "Porez na prihode od samostalne delatnosti",
  PRO: "Porez na registrovano oružje",
  SPID: "Računi poreza i doprinosa pre objedinjene naplate",
};

/** The analytical report's group code (PDP, PDV, ...): from the request, else from its row on ePorezi. */
function fiscalGroup(r: PursRequest): string {
  const code = (r.Grupa ?? "").split(" – ")[0].trim() || (r.kod?.startsWith("analitika-") ? r.kod.slice(10) : "");
  if (code) return code;
  if (groupOf(r) !== "analitika") return "";
  const found = Object.values(r.red ?? {}).join(" ").match(new RegExp(`\\b(${Object.keys(FISCAL_GROUPS).join("|")})\\b`));
  return found ? found[1] : "";
}

/** For searching: lower case, no diacritics (đ = dj). */
const fold = (text: string) =>
  text.toLowerCase().replace(/đ/g, "dj").normalize("NFD").replace(/[\u0300-\u036f]/g, "");

type Period = "sve" | "danas" | "7" | "30";
type SortKey = "id" | "poslato" | "grupa" | "status";

function matches(r: PursRequest, query: string): boolean {
  if (!query) return true;
  const code = fiscalGroup(r);
  const text = fold(
    [r.sajt_id, r["Tip zahteva"], r.Grupa, code, FISCAL_GROUPS[code], r.Naziv, r.PIB, r.posao, STATUS[r.status], r.greska,
      r.fajl, formatTime(r.poslato), ...Object.values(r.red ?? {})]
      .filter(Boolean)
      .join(" "),
  );
  return fold(query).split(/\s+/).every((word) => text.includes(word));
}

/** Short names of the request types for the table (the full one on hover). */
const SHORT_TYPES: Record<string, string> = {
  "Sintetika u PDF formatu": "Sintetika (PDF)",
  "Analitika za fiskalnu grupu u PDF formatu": "Analitika (PDF)",
  "Nalog - upit stanja sintetički": "Nalog – sintetički (XML)",
};

const fileUrl = (r: PursRequest) => `/files/purs/${encodeURIComponent(r.fajl)}`;

function sizeText(bytes: number | undefined): string {
  if (!bytes) return "";
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** "Prijava na ePorezi" without a job: log in (SmartBox + PIN) and choose the taxpayer, e.g. before "Proveri sada". */
function LoginPanel({ login }: { login: PursLogin | undefined }) {
  const [pin, setPin] = useState("");
  const [provider, setProvider] = useState<string | null>(null);
  const [reader, setReader] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [pib, setPib] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  if (!login) return null;
  const busy = login.stanje === "radi";
  const call = (action: string, body: object = {}) =>
    callApi("purs-login", action, body).then(() => setError(""));
  const fail = (e: Error) => setError(String(e.message ?? e));
  const changed = !!pin || provider !== null || reader !== null || email !== null;
  const saveSettings = () =>
    call("settings", { izdavalac: provider ?? login.izdavalac, citac: reader ?? login.citac, email: email ?? login.email, pin }).then(() => {
      setEmail(null);
      setPin("");
      setProvider(null);
      setReader(null);
    });
  const start = (action: "login" | "taxpayer") =>
    (changed ? saveSettings() : Promise.resolve()).then(() => call(action, { pib })).catch(fail);
  const noPin = !login.pin && !pin;
  let status: ReactNode;
  if (busy) {
    status = (
      <span className="purs-status s-ceka">
        <span className="spinner small" />
        {login.napredak || "Prijava..."}
      </span>
    );
  } else if (login.stanje === "gotovo" && login.obveznik) {
    status = (
      <span className="purs-status s-gotovo">
        Prijavljeni · {login.obveznik.Naziv} (PIB {login.obveznik.PIB})
      </span>
    );
  } else if (login.stanje === "greska") {
    status = <span className="purs-status s-greska">Prijava nije uspela</span>;
  } else {
    status = <span className="muted small">Niste prijavljeni (posle pokretanja pretraživača treba ponovo).</span>;
  }
  return (
    <section className="purs-login">
      <div className="purs-login-head">
        <h3>Prijava na ePorezi</h3>
        {status}
      </div>
      {(error || (login.poruka && login.akcija !== "request")) && (
        <p className="error small purs-message">{error || login.poruka}</p>
      )}
      <div className="purs-login-actions">
        <label className="inline">
          PIB
          <input
            value={pib}
            onChange={(e) => setPib(e.target.value)}
            placeholder={login.pib_firme || "PIB obveznika"}
            title="Prazno = PIB firme otvorene u TiM ERP-u"
            size={14}
          />
        </label>
        <button
          className="primary"
          disabled={noPin}
          title={
            noPin
              ? "Upišite PIN (Podešavanja prijave)"
              : "SmartBox, izdavalac sertifikata, PIN, pa izbor poreskog obveznika (kao zadaci „Prijava na ePorezi“ i „Odabir poreskog obveznika“). SmartBox mora biti pokrenut i kartica u čitaču."
          }
          onClick={() => start("login")}
        >
          Prijavi se i izaberi obveznika
        </button>
        <button
          disabled={!pib.trim() && !login.pib_firme}
          title={!pib.trim() && !login.pib_firme ? "Upišite PIB (nijedna firma nije otvorena)" : "Samo izbor poreskog obveznika (već ste prijavljeni)"}
          onClick={() => start("taxpayer")}
        >
          Samo izaberi obveznika
        </button>
        {busy && (
          <button className="small-button" onClick={() => call("cancel").catch(fail)}>
            Prekini
          </button>
        )}
        <button type="button" className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "▾" : "▸"} Podešavanja prijave
        </button>
      </div>
      {busy && <p className="muted small purs-message">Zakazano u redu za ePorezi (gore): radi se kad dođe na red.</p>}
      {open && (
        <div className="purs-login-settings">
          <label className="inline secret-field">
            PIN kartice
            <input
              type="password"
              autoComplete="new-password"
              value={pin}
              onChange={(e) => setPin(e.target.value)}
              placeholder={login.pin ? "novi, za promenu" : "nije upisan"}
              size={16}
            />
            {login.pin && !pin && <span className="badge">{login.pin === "stranica" ? "sačuvan" : `iz: ${login.pin}`}</span>}
            {login.pin === "stranica" && (
              <button type="button" className="link" onClick={() => call("forget_pin").catch(fail)}>
                Obriši
              </button>
            )}
          </label>
          <label className="inline">
            Izdavalac sertifikata
            <input value={provider ?? login.izdavalac} onChange={(e) => setProvider(e.target.value)} size={30} />
          </label>
          <label className="inline">
            Čitač kartice
            <input value={reader ?? login.citac} onChange={(e) => setReader(e.target.value)} placeholder="jedini" size={14} />
          </label>
          <label className="inline" title="Za analitiku traženu sa ove stranice (sajt je traži); sintetika se uvek traži sa „1“">
            E-pošta za analitiku
            <input type="email" value={email ?? login.email} onChange={(e) => setEmail(e.target.value)}
              placeholder="1" size={24} />
          </label>
          <button disabled={!changed} onClick={() => saveSettings().catch(fail)}>
            Sačuvaj
          </button>
          <p className="muted small">
            PIN se čuva u Windows Credential Manager-u i unosi se jednom po prijavi (pogrešan PIN unet više puta zaključava
            karticu). Bez PIN-a sa ove stranice koristi se PIN zadatka „Prijava na ePorezi“ iz nekog posla.
          </p>
        </div>
      )}
    </section>
  );
}

/** ePorezi "Upit stanja" requests: waiting in the background, then the downloaded report. */
export function PursPage({ state, login, queue }: { state: PursState | undefined; login?: PursLogin; queue?: PursQueueState }) {
  const [error, setError] = useState("");
  const [group, setGroup] = useState<Group>("sve");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<PursRequest["status"] | "">("");
  const [fiscal, setFiscal] = useState("");
  const [period, setPeriod] = useState<Period>("sve");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "poslato", desc: true });
  const all = state?.zahtevi ?? [];
  const inTab = group === "sve" ? all : all.filter((r) => groupOf(r) === group);
  const count = (g: Group) => (g === "sve" ? all.length : all.filter((r) => groupOf(r) === g).length);
  const showFiscal = group !== "sintetika";
  const fiscalCodes = [...new Set(inTab.map(fiscalGroup).filter(Boolean))].sort();
  const since =
    period === "sve" ? 0 : period === "danas" ? new Date().setHours(0, 0, 0, 0) / 1000 : Date.now() / 1000 - Number(period) * 86400;
  const requests = inTab
    .filter(
      (r) =>
        (!status || r.status === status) &&
        (!fiscal || !showFiscal || fiscalGroup(r) === fiscal) &&
        r.poslato >= since &&
        matches(r, query.trim()),
    )
    .sort((a, b) => {
      const value = (r: PursRequest): string | number =>
        sort.key === "id" ? Number(r.sajt_id) || 0
          : sort.key === "grupa" ? fiscalGroup(r) || "~"
            : sort.key === "status" ? STATUS[r.status]
              : r.poslato;
      const [x, y] = [value(a), value(b)];
      const order = x < y ? -1 : x > y ? 1 : b.poslato - a.poslato;
      return sort.desc ? -order : order;
    });
  const filtered = !!(query.trim() || status || (fiscal && showFiscal) || period !== "sve");
  const clear = () => {
    setQuery("");
    setStatus("");
    setFiscal("");
    setPeriod("sve");
  };
  const header = (key: SortKey, label: string) => (
    <th
      className="sortable"
      aria-sort={sort.key === key ? (sort.desc ? "descending" : "ascending") : "none"}
      onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key === "poslato" || key === "id" }))}
      title="Sortiraj"
    >
      {label}
      <span className="sort-mark">{sort.key === key ? (sort.desc ? " ▾" : " ▴") : ""}</span>
    </th>
  );
  const columns = showFiscal ? 8 : 7;
  const toggle = (id: string) => setOpen((o) => ({ ...o, [id]: !o[id] }));
  const call = (action: string, id: string) =>
    callApi("purs", action, { id })
      .then(() => setError(""))
      .catch((e) => setError(String(e.message ?? e)));
  return (
    <div className="card purs-page">
      <h2>PURS – izveštaji sa ePoreza{state?.firma ? ` · ${state.firma}` : ""}</h2>
      <p className="muted small">
        Zahtevi poslati zadatkom „Upit stanja“ dok je bila otvorena ova firma (svaka firma ima svoje). Program čeka izveštaj
        u redu za ePorezi (proverava tabelu na ePorezima svakih 5 s, naizmenično sa drugim obveznicima) i preuzima ga čim
        se pojavi link „Извештај“.
      </p>
      <PursQueue state={queue} />
      <LoginPanel login={login} />
      <TaxStatePanel purs={state} login={login} />
      {error && <p className="error small">{error}</p>}
      {!state?.firma ? (
        <p className="muted">Izaberite firmu: ovde se vide zahtevi otvorene firme.</p>
      ) : all.length === 0 ? (
        <p className="muted">Ova firma još nema zahteva.</p>
      ) : (
        <>
        <div className="segmented purs-tabs" role="tablist" aria-label="Vrsta izveštaja">
          {GROUPS.map(([value, label]) => (
            <button
              key={value}
              role="tab"
              aria-selected={group === value}
              className={group === value ? "on" : ""}
              onClick={() => setGroup(value)}
            >
              {label} <span className="count">{count(value)}</span>
            </button>
          ))}
        </div>
        <div className="purs-filters">
          <input
            type="search"
            className="purs-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Pretraga: ID, tip, grupa, obveznik, posao, poruka…"
            aria-label="Pretraga zahteva"
          />
          <label className="inline">
            Status
            <select value={status} onChange={(e) => setStatus(e.target.value as PursRequest["status"] | "")}>
              <option value="">Svi</option>
              {Object.entries(STATUS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {showFiscal && fiscalCodes.length > 0 && (
            <label className="inline">
              Grupa
              <select value={fiscal} onChange={(e) => setFiscal(e.target.value)}>
                <option value="">Sve</option>
                {fiscalCodes.map((code) => (
                  <option key={code} value={code}>
                    {code} – {FISCAL_GROUPS[code] ?? code}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="inline">
            Poslato
            <select value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
              <option value="sve">Bilo kad</option>
              <option value="danas">Danas</option>
              <option value="7">Poslednjih 7 dana</option>
              <option value="30">Poslednjih 30 dana</option>
            </select>
          </label>
          {filtered && (
            <button type="button" className="link" onClick={clear}>
              Očisti filtere
            </button>
          )}
          <span className="muted small purs-shown">
            {filtered ? `${requests.length} od ${inTab.length}` : `${inTab.length} zahteva`}
          </span>
        </div>
        {requests.length === 0 ? (
          <p className="muted">{filtered ? "Nijedan zahtev ne odgovara filterima." : "Nema zahteva ove vrste."}</p>
        ) : (
        <div className="table-wrap tall">
          <table className="turnover-table purs-table">
            <thead>
              <tr>
                <th className="purs-toggle-cell" />
                {header("id", "ID zahteva")}
                {header("poslato", "Poslato")}
                <th>Tip zahteva</th>
                {showFiscal && header("grupa", "Grupa")}
                {header("status", "Status")}
                <th>Izveštaj</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {requests.map((r) => {
                const row = r.red ? Object.entries(r.red).filter(([k, v]) => k && v) : [];
                const details = !!r.greska || row.length > 0 || !!r.Naziv || !!r.PIB || !!r.ponovo_trazen;
                const expanded = details && !!open[r.id];
                return (
                <Fragment key={r.id}>
                <tr
                  className={`${expanded ? "has-details" : ""} ${details ? "expandable" : ""}`}
                  onClick={(e) => {
                    if (details && !(e.target as HTMLElement).closest("button, a")) toggle(r.id);
                  }}
                >
                  <td className="purs-toggle-cell">
                    {details && (
                      <button
                        className={`purs-toggle ${r.greska ? "has-error" : ""}`}
                        aria-expanded={expanded}
                        title={expanded ? "Sakrij detalje" : r.greska ? "Prikaži detalje (greška)" : "Prikaži detalje"}
                        onClick={() => toggle(r.id)}
                      >
                        {expanded ? "▾" : "▸"}
                        {r.greska && !expanded && <span className="purs-flag">!</span>}
                      </button>
                    )}
                  </td>
                  <td className="strong nowrap">{r.sajt_id || "—"}</td>
                  <td className="nowrap">{formatTime(r.poslato)}</td>
                  <td>
                    {r["Tip zahteva"] ? (
                      <span title={r["Tip zahteva"]}>{SHORT_TYPES[r["Tip zahteva"]] ?? r["Tip zahteva"]}</span>
                    ) : (
                      <span className="muted">(poslat ručno)</span>
                    )}
                  </td>
                  {showFiscal && (
                    <td className="nowrap">
                      {fiscalGroup(r) ? (
                        <span className="purs-group" title={FISCAL_GROUPS[fiscalGroup(r)] ?? r.Grupa}>
                          {fiscalGroup(r)}
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  )}
                  <td>
                    <span className={`purs-status s-${r.status}`}>
                      {r.status === "ceka" && <span className="spinner small" />}
                      {STATUS[r.status]}
                    </span>
                    {r.status === "ceka" && (r.status_tekst || r.provera) && (
                      <div className="muted small">
                        {r.status_tekst ||
                          `${r.provera_broj}. provera u ${new Date((r.provera ?? 0) * 1000).toLocaleTimeString("sr-Latn")}`}
                      </div>
                    )}
                  </td>
                  <td className="nowrap">
                    {r.fajl ? (
                      <>
                        <a href={fileUrl(r)} target="_blank" rel="noreferrer">
                          Otvori
                        </a>
                        <span className="muted small"> {sizeText(r.velicina)}</span>
                        {/\.pdf$/i.test(r.fajl) &&
                          (groupOf(r) === "analitika" ? (
                            <a
                              className="purs-book-link"
                              href={`#/purs/${r.id}/knjizenje`}
                              title="Izveštaj rastavljen po pozivima na broj: stavke, zbirovi, stanje duga"
                            >
                              Knjiženje
                            </a>
                          ) : (
                            <a className="purs-book-link" href={`#/purs/${r.id}/sadrzaj`} title="Tekst i tabele iz PDF-a">
                              Sadržaj
                            </a>
                          ))}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>
                    <div className="purs-actions">
                    {r.status === "ceka" ? (
                      <button
                        className="small-button"
                        title="Program prestaje da proverava ovaj zahtev (izveštaj ostaje na ePorezima)"
                        onClick={() => call("stop", r.id)}
                      >
                        Prekini čekanje
                      </button>
                    ) : (
                      <>
                        {r.status !== "gotovo" && r.sajt_id && (
                          <button
                            className="small-button"
                            title="Pronađi zahtev po ID-ju u tabeli „Упит стања“ i preuzmi izveštaj ako je stigao; ako nije, nastavlja da čeka. Na ePorezima treba da ste prijavljeni i da je izabran isti poreski obveznik (posle ponovnog pokretanja programa: zadaci „Prijava na ePorezi“ i „Odabir poreskog obveznika“)."
                            onClick={() => call("check", r.id)}
                          >
                            Proveri sada
                          </button>
                        )}
                        <button className="icon" title="Obriši zahtev i fajl" aria-label="Obriši" onClick={() => call("delete", r.id)}>
                          ✕
                        </button>
                      </>
                    )}
                    </div>
                  </td>
                </tr>
                {expanded && (
                  <tr className="purs-details">
                    <td />
                    <td colSpan={columns - 1}>
                      {r.greska && <div className="error">{r.greska}</div>}
                      {(r.ponovo_trazen || r.napomena) && (
                        <div>
                          {r.napomena}
                          {r.ponovo_trazen &&
                            ` Ponovo tražen ${formatTime(r.ponovo_trazen)}: ePorezi pravi jedan izveštaj ovog tipa dnevno, pa je korišćen ovaj (bez ponovnog preuzimanja).`}
                        </div>
                      )}
                      {(r.Naziv || r.PIB) && (
                        <div>
                          Poreski obveznik: {r.Naziv || "—"}
                          {r.PIB ? ` (PIB ${r.PIB})` : ""}
                          {r.Grupa ? ` · Grupa: ${r.Grupa}` : ""}
                          {r.posao ? ` · Posao: ${r.posao}` : ""}
                        </div>
                      )}
                      {row.length > 0 && (
                        <div className="muted" title="Red ovog zahteva u tabeli „Упит стања“ na ePorezima">
                          Na ePorezima: {row.map(([k, v]) => `${k}: ${v}`).join(" · ")}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
                </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        )}
        </>
      )}
    </div>
  );
}

/** A notice in the corner when a report has arrived (or waiting for it failed), on any page. */
export function PursNotices({ state }: { state: PursState | undefined }) {
  const seen = useRef<Record<string, string> | null>(null);
  const [notices, setNotices] = useState<PursRequest[]>([]);

  useEffect(() => {
    const requests = state?.zahtevi ?? [];
    const now = Object.fromEntries(requests.map((r) => [r.id, r.status]));
    if (seen.current) {
      const changed = requests.filter((r) => seen.current![r.id] === "ceka" && (r.status === "gotovo" || r.status === "greska"));
      if (changed.length) setNotices((n) => [...changed, ...n.filter((x) => !changed.some((c) => c.id === x.id))]);
    }
    if (state) seen.current = now;
  }, [state]);

  if (!notices.length) return null;
  const close = (id: string) => setNotices((n) => n.filter((x) => x.id !== id));
  return (
    <div className="notices" role="status">
      {notices.map((r) => (
        <div key={r.id} className={`notice ${r.status === "greska" ? "notice-error" : ""}`}>
          <div>
            <strong>
              {r.status === "gotovo" ? "PURS izveštaj je stigao" : "PURS izveštaj nije preuzet"}
              {r.sajt_id ? ` (ID ${r.sajt_id})` : ""}
            </strong>
            <div className="small">
              {r["Tip zahteva"]}
              {r.Grupa ? ` · ${r.Grupa}` : ""}
              {r.Naziv ? ` · ${r.Naziv}` : ""}
            </div>
            {r.greska && <div className="small">{r.greska}</div>}
            <div className="notice-actions">
              {r.fajl && (
                <a href={fileUrl(r)} target="_blank" rel="noreferrer" onClick={() => close(r.id)}>
                  Otvori
                </a>
              )}
              <a href="#/purs" onClick={() => close(r.id)}>
                Svi izveštaji
              </a>
            </div>
          </div>
          <button className="icon" aria-label="Zatvori" onClick={() => close(r.id)}>
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
