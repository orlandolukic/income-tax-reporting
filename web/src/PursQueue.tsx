import { useEffect, useMemo, useState } from "react";
import { callApi, PursQueueItem, PursQueueState } from "./api";

/** What an item is: label and its fixed series slot (colours in style.css, --q-*). */
const KINDS: Record<PursQueueItem["vrsta"], string> = {
  prijava: "Prijava",
  obveznik: "Obveznik",
  zahtev: "Upit stanja",
  provera: "Provera izveštaja",
  sesija: "Provera prijave",
};
const KIND_ORDER = Object.keys(KINDS) as PursQueueItem["vrsta"][];

const STATUS: Record<PursQueueItem["status"], string> = {
  zakazano: "Zakazano",
  radi: "Radi",
  gotovo: "Gotovo",
  greska: "Greška",
  otkazano: "Otkazano",
};

const TIMELINE_MINUTES = 10;

const clock = (t: number) => new Date(t * 1000).toLocaleTimeString("sr-Latn");

function duration(seconds: number): string {
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
  const m = Math.floor(seconds / 60);
  return `${m} min ${Math.round(seconds % 60)} s`;
}

/** The server's clock now (the page may run on another PC). */
function useServerNow(state: PursQueueState | undefined): number {
  const offset = useMemo(() => (state ? state.sada * 1000 - Date.now() : 0), [state]);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return (now + offset) / 1000;
}

function KindChip({ kind }: { kind: PursQueueItem["vrsta"] }) {
  return <span className={`q-kind q-${kind}`}>{KINDS[kind]}</span>;
}

/** The last minutes of the queue: one lane per kind of item, a bar per item from its start to its end. */
function Timeline({ items, now }: { items: PursQueueItem[]; now: number }) {
  const [hover, setHover] = useState<{ item: PursQueueItem; x: number; lane: number } | null>(null);
  const from = now - TIMELINE_MINUTES * 60;
  const pos = (t: number) => Math.max(0, Math.min(100, ((t - from) / (now - from)) * 100));
  const shown = items.filter((i) => i.pocetak && (i.kraj ?? now) >= from);
  const lanes = KIND_ORDER.filter((k) => shown.some((i) => i.vrsta === k));
  const ticks = Array.from({ length: TIMELINE_MINUTES / 2 + 1 }, (_, n) => now - n * 120);
  if (!lanes.length) {
    return <p className="muted small q-empty">U poslednjih {TIMELINE_MINUTES} minuta ništa nije rađeno na ePorezima.</p>;
  }
  return (
    <div className="q-timeline" onMouseLeave={() => setHover(null)}>
      {lanes.map((kind, lane) => (
        <div className="q-lane" key={kind}>
          <span className="q-lane-label">{KINDS[kind]}</span>
          <div className="q-lane-track">
            {shown
              .filter((i) => i.vrsta === kind)
              .map((i) => {
                const left = pos(i.pocetak!);
                const width = Math.max(0.6, pos(i.kraj ?? now) - left);
                return (
                  <span
                    key={i.id}
                    className={`q-bar q-${i.vrsta} ${i.status === "radi" ? "running" : ""} ${i.status === "greska" ? "failed" : ""}`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                    onMouseEnter={() => setHover({ item: i, x: left + width / 2, lane })}
                    aria-label={`${i.naziv}, ${STATUS[i.status]}`}
                  />
                );
              })}
          </div>
        </div>
      ))}
      <div className="q-axis">
        <span className="q-lane-label" />
        <div className="q-lane-track">
          {ticks.map((t, n) => (
            <span key={n} className="q-tick" style={{ left: `${pos(t)}%` }}>
              {n === 0 ? "sada" : `−${n * 2} min`}
            </span>
          ))}
        </div>
      </div>
      {hover && (
        <div
          className="q-tooltip"
          style={{ left: `calc(var(--q-label) + (100% - var(--q-label)) * ${hover.x / 100})`, top: `${hover.lane * 26}px` }}
        >
          <strong>{hover.item.naziv}</strong>
          <span>
            {STATUS[hover.item.status]} · {duration((hover.item.kraj ?? now) - hover.item.pocetak!)}
          </span>
          <span className="muted">{hover.item.izvor}</span>
          {hover.item.poruka && <span>{hover.item.poruka}</span>}
        </div>
      )}
    </div>
  );
}

/** "Red za ePorezi": the one ePorezi session of the program and what is scheduled on it. */
export function PursQueue({ state }: { state: PursQueueState | undefined }) {
  const now = useServerNow(state);
  const [error, setError] = useState("");
  const [allHistory, setAllHistory] = useState(false);
  if (!state) return null;
  const call = (action: string, body: object = {}) =>
    callApi("purs-red", action, body)
      .then(() => setError(""))
      .catch((e) => setError(String(e.message ?? e)));
  const { trenutno: current, red: queue, istorija: history, sesija: session } = state;
  const login =
    !session.pregledac ? ["neutral", "Pretraživač za ePorezi nije pokrenut"]
      : session.prijavljen ? ["ok", "Prijavljen"]
        : session.prijavljen === false ? ["fail", "Nije prijavljen"]
          : ["neutral", "Ne zna se"];
  const timelineItems = current ? [current, ...history] : history;
  const historyShown = allHistory ? history : history.slice(0, 8);
  return (
    <section className="purs-queue">
      <div className="purs-login-head">
        <h3>Red za ePorezi</h3>
        <span className={`q-pill q-pill-${login[0]}`}>{login[1]}</span>
        {session.obveznik && (
          <span className="q-pill q-pill-neutral" title="Obveznik izabran u sesiji ePoreza sada">
            Obveznik: {session.obveznik.Naziv} ({session.obveznik.PIB})
          </span>
        )}
        <span className="spacer" />
        <button className="small-button" disabled={!session.pregledac} onClick={() => call("session")}
          title="Zakaži proveru da li je ePorezi još prijavljen">
          Proveri prijavu
        </button>
      </div>
      <p className="muted small">
        ePorezi ima jednu prijavu za ceo program (svoj pretraživač). Sve što ga koristi (stranica PURS, PURS zadaci poslova,
        provere izveštaja) čeka ovde na red i radi se jedno po jedno. Provere izveštaja idu u krug po obveznicima: jedna
        provera, pa sledeći obveznik.
      </p>
      {error && <p className="error small">{error}</p>}

      <div className="q-pipeline" aria-label="Red">
        <div className={`q-card q-now ${current ? "" : "idle"}`}>
          <span className="q-card-head">Sada</span>
          {current ? (
            <>
              <KindChip kind={current.vrsta} />
              <strong className="q-title">{current.naziv}</strong>
              <span className="muted small">
                {current.izvor} · {duration(Math.max(0, now - (current.pocetak ?? now)))}
              </span>
              {(current.napredak || current.poruka) && (
                <span className="small q-progress">
                  <span className="spinner small" /> {current.poruka || current.napredak}
                </span>
              )}
              <button className="small-button" onClick={() => call("cancel", { id: current.id })}>
                Prekini
              </button>
            </>
          ) : (
            <span className="muted small">Ništa se ne radi.</span>
          )}
        </div>
        {queue.map((item, n) => (
          <div className="q-card" key={item.id}>
            <span className="q-card-head">{n + 1}. na redu</span>
            <KindChip kind={item.vrsta} />
            <strong className="q-title">{item.naziv}</strong>
            <span className="muted small">
              {item.izvor}
              {item.firma ? ` · ${item.firma}` : ""} · čeka {duration(Math.max(0, now - item.dodato))}
            </span>
            {item.opis && <span className="muted small">{item.opis}</span>}
            <button className="small-button" onClick={() => call("cancel", { id: item.id })} title="Izbaci iz reda">
              Otkaži
            </button>
          </div>
        ))}
        {!queue.length && current && <div className="q-card idle muted small">Ništa nije zakazano posle ovoga.</div>}
      </div>

      {state.obveznici.length > 0 && (
        <div className="q-taxpayers">
          <h4>Čekaju se izveštaji · provera na svakih {state.poll} s po obvezniku, u krug</h4>
          <ul>
            {state.obveznici.map((t) => {
              const checking = current?.vrsta === "provera" && current.pib === t.pib;
              const queued = queue.findIndex((i) => i.vrsta === "provera" && i.pib === t.pib);
              const next = t.poslednja ? t.poslednja + state.poll - now : 0;
              return (
                <li key={t.pib || "-"}>
                  <span className="q-kind q-provera">{t.naziv || t.pib || "izabrani obveznik"}</span>
                  <span className="small">{t.pib && t.naziv ? `PIB ${t.pib} · ` : ""}zahtevi: {t.zahtevi.join(", ")}</span>
                  <span className="muted small">
                    {checking
                      ? "proverava se sada"
                      : queued >= 0
                        ? `u redu (${queued + 1}.)`
                        : next > 0
                          ? `sledeća provera za ${Math.ceil(next)} s`
                          : session.prijavljen === false
                            ? "čeka prijavu na ePorezi"
                            : "uskoro"}
                    {t.poslednja ? ` · poslednja ${clock(t.poslednja)}` : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <h4>Poslednjih {TIMELINE_MINUTES} minuta</h4>
      <Timeline items={timelineItems} now={now} />

      {history.length > 0 && (
        <>
          <h4>Urađeno</h4>
          <table className="q-history">
            <thead>
              <tr>
                <th>Početak</th>
                <th>Vrsta</th>
                <th>Šta</th>
                <th>Ko je zakazao</th>
                <th>Čekalo</th>
                <th>Trajalo</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {historyShown.map((i) => (
                <tr key={i.id}>
                  <td>{i.pocetak ? clock(i.pocetak) : "—"}</td>
                  <td>
                    <KindChip kind={i.vrsta} />
                  </td>
                  <td>
                    {i.naziv}
                    {i.poruka && <div className={`small ${i.status === "greska" ? "error" : "muted"}`}>{i.poruka}</div>}
                  </td>
                  <td className="small">{i.izvor}{i.firma ? ` · ${i.firma}` : ""}</td>
                  <td className="small">{i.pocetak ? duration(i.pocetak - i.dodato) : "—"}</td>
                  <td className="small">{i.pocetak && i.kraj ? duration(i.kraj - i.pocetak) : "—"}</td>
                  <td>
                    <span className={`q-status q-status-${i.status}`}>{STATUS[i.status]}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {history.length > 8 && (
            <button type="button" className="link" onClick={() => setAllHistory(!allHistory)}>
              {allHistory ? "Prikaži manje" : `Prikaži sve (${history.length})`}
            </button>
          )}
        </>
      )}
    </section>
  );
}
