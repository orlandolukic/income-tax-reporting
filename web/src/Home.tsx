import { useEffect, useState } from "react";
import { callApi, HomeCheck, HomeStats, Prompt, Shared } from "./api";
import { formatDuration, formatTime, StatusBadge } from "./jobs/common";

type Tone = "ok" | "fail" | "warn" | "run" | "neutral";

function Light({ tone, busy, children }: { tone: Tone; busy?: boolean; children: React.ReactNode }) {
  return (
    <span className={`home-light t-${tone}`}>
      {busy ? <span className="spinner small" /> : <span className="dot-mark" aria-hidden="true" />}
      {children}
    </span>
  );
}

const clock = (t: number | null | undefined) => (t ? new Date(t * 1000).toLocaleTimeString("sr-Latn") : "");

function seconds(s: number | null | undefined): string {
  if (s == null) return "—";
  return formatDuration(1, 1 + s);
}

/** "Početna": is TiM ERP ready, is ePorezi logged in, and the open company's numbers. */
export default function Home({ shared, prompt, connected }: { shared: Shared; prompt: Prompt | null; connected: boolean }) {
  const [stats, setStats] = useState<HomeStats | null>(null);
  const [error, setError] = useState("");
  const checks = shared.pocetna;
  const jobs = shared.jobs;
  const running = jobs?.runner.running ?? null;
  const company = jobs?.company?.key ?? shared.session?.company?.name ?? shared.session?.company?.naSajtu ?? "";

  const check = (what: "all" | "tim" | "purs", force = false) =>
    callApi("pocetna", "check", { what, force })
      .then(() => setError(""))
      .catch((e) => setError(String(e.message ?? e)));

  useEffect(() => {
    if (connected) check("all");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected]);

  useEffect(() => {
    if (!connected) return;
    callApi<HomeStats>("pocetna", "stats", { dana: 7 })
      .then(setStats)
      .catch(() => setStats(null));
  }, [connected, running, company]);

  return (
    <div className="home">
      {error && <p className="error small">{error}</p>}
      <div className="home-status">
        <TimCard shared={shared} prompt={prompt} connected={connected} check={checks?.tim} onCheck={() => check("tim", true)} />
        <PursCard check={checks?.purs} connected={connected} onCheck={() => check("purs", true)} />
      </div>
      {company && <Statistics shared={shared} stats={stats} />}
    </div>
  );
}

function TimCard(props: {
  shared: Shared;
  prompt: Prompt | null;
  connected: boolean;
  check: HomeCheck | undefined;
  onCheck: () => void;
}) {
  const { shared, prompt, connected, check } = props;
  const jobs = shared.jobs;
  const reports = shared.reports;
  const ready = prompt?.kind === "ready";
  const runningJob = jobs?.runner.running ? jobs.jobs.find((j) => j.id === jobs.runner.running)?.name ?? "posao" : "";
  const runningReport = reports?.runner.running ? reports.types.find((t) => t.id === reports.runner.running)?.title ?? "izveštaj" : "";
  let light: React.ReactNode;
  if (!connected) light = <Light tone="fail">Program nije pokrenut</Light>;
  else if (prompt?.kind === "login") light = <Light tone="warn">Čeka prijavu</Light>;
  else if (prompt?.kind === "company") light = <Light tone="warn">Čeka izbor firme</Light>;
  else if (prompt?.kind === "done") light = <Light tone="neutral">Završeno</Light>;
  else if (!ready) light = <Light tone="run" busy>Priprema (prijava / otvaranje firme)</Light>;
  else if (runningJob) light = <Light tone="run" busy>Posao u toku: {runningJob}</Light>;
  else if (runningReport) light = <Light tone="run" busy>Izveštaj u toku: {runningReport}</Light>;
  else if (check?.stanje === "provera") light = <Light tone="run" busy>Provera...</Light>;
  else if (check?.stanje === "odjavljen") light = <Light tone="fail">Sesija je istekla</Light>;
  else if (check?.stanje === "greska") light = <Light tone="fail">Greška</Light>;
  else if (check?.stanje === "nepoznato") light = <Light tone="warn">Nije na glavnoj strani</Light>;
  else light = <Light tone="ok">Spreman</Light>;
  const company = shared.session?.company;
  return (
    <section className="card home-card">
      <div className="home-card-head">
        <h2>TiM ERP</h2>
        <button className="small-button" disabled={!ready || !!runningJob || !!runningReport} onClick={props.onCheck}
          title="Pogledaj u pretraživaču da li je glavni meni TiM ERP-a prikazan (između poslova)">
          Proveri
        </button>
      </div>
      <div className="home-light-row">{light}</div>
      <dl className="home-facts">
        {shared.session?.user && (
          <>
            <dt>Korisnik</dt>
            <dd>{shared.session.user}</dd>
          </>
        )}
        {company && (
          <>
            <dt>Firma</dt>
            <dd>
              {company.name || company.naSajtu}
              {company.pib ? ` · PIB ${company.pib}` : ""}
              {company.year ? ` · ${company.year}` : ""}
            </dd>
          </>
        )}
        {ready && check?.poruka && (
          <>
            <dt>Provera</dt>
            <dd>
              {check.poruka}
              {check.provereno && <span className="muted"> ({clock(check.provereno)})</span>}
            </dd>
          </>
        )}
      </dl>
    </section>
  );
}

function PursCard({ check, connected, onCheck }: { check: HomeCheck | undefined; connected: boolean; onCheck: () => void }) {
  let light: React.ReactNode;
  if (!connected) light = <Light tone="neutral">Nepoznato</Light>;
  else if (check?.stanje === "provera") light = <Light tone="run" busy>Provera...</Light>;
  else if (check?.stanje === "ok") light = <Light tone="ok">Prijavljen</Light>;
  else if (check?.stanje === "odjavljen") light = <Light tone="fail">Nije prijavljen</Light>;
  else if (check?.stanje === "nepoznato") light = <Light tone="warn">Nije provereno</Light>;
  else light = <Light tone="neutral">Nije provereno</Light>;
  return (
    <section className="card home-card">
      <div className="home-card-head">
        <h2>PURS ePorezi</h2>
        <button className="small-button" disabled={!connected || check?.stanje === "provera"} onClick={onCheck}
          title="Otvori ePorezi u skrivenoj kartici i pogledaj da li je sesija prijavljena">
          Proveri
        </button>
      </div>
      <div className="home-light-row">{light}</div>
      <dl className="home-facts">
        {check?.obveznik && (
          <>
            <dt>Obveznik</dt>
            <dd>
              {check.obveznik.Naziv} · PIB {check.obveznik.PIB}
            </dd>
          </>
        )}
        {check?.poruka && !check.obveznik && (
          <>
            <dt>Provera</dt>
            <dd>{check.poruka}</dd>
          </>
        )}
        {check?.provereno && (
          <>
            <dt>Provereno</dt>
            <dd>{clock(check.provereno)}</dd>
          </>
        )}
      </dl>
      {check?.stanje === "odjavljen" && (
        <a className="button" href="#/purs">
          Prijava na stranici PURS →
        </a>
      )}
    </section>
  );
}

function Tile({ label, value, note, tone }: { label: string; value: React.ReactNode; note?: React.ReactNode; tone?: Tone }) {
  return (
    <div className={`home-tile ${tone ? `t-${tone}` : ""}`}>
      <div className="home-tile-label">{label}</div>
      <div className="home-tile-value">{value}</div>
      {note && <div className="home-tile-note">{note}</div>}
    </div>
  );
}

function Statistics({ shared, stats }: { shared: Shared; stats: HomeStats | null }) {
  const purs = shared.purs?.zahtevi ?? [];
  const reportResults = Object.values(shared.reports?.history ?? {}).flat();
  const lastReport = reportResults.reduce<number>((m, r) => Math.max(m, r.started_at ?? 0), 0);
  const s = stats?.po_statusu ?? {};
  const failed = (s.failed ?? 0) + (s.stopped ?? 0);
  return (
    <section className="card home-stats">
      <h2>
        Statistika{" "}
        <span className="muted small">
          · {shared.jobs?.company?.label ?? shared.session?.company?.name} · poslednjih {stats?.dana ?? 7} dana
        </span>
      </h2>
      <div className="home-tiles">
        <Tile label="Poslovi" value={stats?.poslova ?? shared.jobs?.jobs.length ?? 0} />
        <Tile label="Pokretanja" value={stats?.pokretanja ?? "—"} note={stats ? `danas ${stats.danas}` : undefined} />
        <Tile label="Uspešno" value={s.done ?? 0} tone={(s.done ?? 0) > 0 ? "ok" : undefined} />
        <Tile label="Sa greškom" value={failed} tone={failed > 0 ? "fail" : undefined}
          note={s.cancelled ? `zaustavljeno ${s.cancelled}` : undefined} />
        <Tile label="Prosečno trajanje" value={seconds(stats?.prosek)} note={stats ? `${stats.koraka} koraka ukupno` : undefined} />
        <Tile label="Izveštaji" value={reportResults.length} note={lastReport ? `poslednji ${formatTime(lastReport)}` : undefined} />
        <Tile
          label="PURS zahtevi"
          value={purs.length}
          note={`čeka ${purs.filter((r) => r.status === "ceka").length} · stiglo ${purs.filter((r) => r.status === "gotovo").length} · greška ${purs.filter((r) => r.status === "greska").length}`}
        />
      </div>
      {stats && stats.poslednja.length > 0 && (
        <>
          <h3>Poslednja pokretanja</h3>
          <table className="home-runs">
            <tbody>
              {stats.poslednja.map((r) => (
                <tr key={r.fajl || `${r.id}-${r.pocetak}`}>
                  <td>
                    <a href={`#/poslovi/${r.id}/izvestaj/${r.fajl}`}>{r.posao}</a>
                  </td>
                  <td className="nowrap">{formatTime(r.pocetak)}</td>
                  <td className="nowrap muted">{formatDuration(r.pocetak, r.kraj)}</td>
                  <td>
                    <StatusBadge status={r.status} />
                    {r.greske > 0 && <span className="muted small"> {r.greske} greš.</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
