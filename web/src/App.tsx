import { useEffect, useMemo, useRef, useState } from "react";
import { answer, Session, useServer } from "./api";
import Home from "./Home";
import CompanyPicker from "./CompanyPicker";
import Done from "./Done";
import JobPage from "./jobs/JobPage";
import JobsList from "./jobs/JobsList";
import RunReport from "./jobs/RunReport";
import LiveView from "./LiveView";
import LoginForm from "./LoginForm";
import Ready from "./Ready";
import RunProgress from "./RunProgress";
import { PursNotices, PursPage } from "./PursPage";
import { AnalyticsPage, ContentPage } from "./PursReport";
import { ReportPage, ReportsList } from "./reports/ReportsPage";
import WaitPanel from "./WaitPanel";

export default function App() {
  const { status, prompt, log, shared, connected } = useServer();
  const [logOpen, toggleLog] = useRememberedToggle("logOpen");
  const [liveOpen, toggleLive] = useRememberedToggle("liveOpen");
  const [progressCollapsed, toggleProgress] = useRememberedToggle("progressCollapsed");
  const route = useHashRoute(); // "" | "poslovi" | "poslovi/<job id>" | "izvestaji" | "izvestaji/<report>"
  const [section, jobId, sub, report] = route.split("/");
  // Prompts the program is blocked on (the "ready" one just waits for the user to finish).
  const needsAnswer = !!prompt && prompt.kind !== "ready";
  const session = shared.session;
  // "Promena firme" and "Odjava" answer the "ready" prompt, so they only work while it is open and idle.
  const readyId = prompt?.kind === "ready" ? prompt.id : null;
  const jobBusy = !!shared.jobs?.runner.running || (shared.jobs?.runner.queued.length ?? 0) > 0;
  const reportBusy = !!shared.reports?.runner.running || (shared.reports?.runner.queued.length ?? 0) > 0;
  const pursWaiting = shared.purs?.zahtevi.filter((r) => r.status === "ceka").length ?? 0;
  const switchBlocker = !readyId
    ? "Moguće kad je firma otvorena i program spreman."
    : jobBusy
      ? "Sačekajte da se posao završi."
      : reportBusy
        ? "Sačekajte da se izveštaj završi."
        : "";

  // Flag the tab when the program needs an answer, since the automated browser may cover this window.
  useEffect(() => {
    document.title = needsAnswer && prompt?.kind !== "done" ? "● Potrebna akcija — TiM ERP" : "TiM ERP automatizacija";
  }, [needsAnswer, prompt]);

  return (
    <div className={`app ${logOpen ? "log-open" : ""} ${section === "purs" ? "wide" : ""}`}>
      <header className="top">
        <div className="top-row">
          <h1>TiM ERP</h1>
          <nav>
            <a href="#/" className={section === "" ? "on" : ""}>
              Početna{needsAnswer && section !== "" && <span className="dot" aria-label="čeka odgovor" />}
            </a>
            <a href="#/poslovi" className={section === "poslovi" ? "on" : ""}>
              Poslovi
            </a>
            <a href="#/izvestaji" className={section === "izvestaji" ? "on" : ""}>
              Izveštaji
            </a>
            <a href="#/purs" className={section === "purs" ? "on" : ""} title="Izveštaji sa ePoreza (Upit stanja)">
              PURS
              {shared.purs_red?.trenutno && (
                <span className="spinner small nav-spinner" title={`ePorezi: ${shared.purs_red.trenutno.naziv}`} />
              )}
              {pursWaiting > 0 && (
                <span className="nav-count" title="Izveštaji koji se čekaju">
                  {pursWaiting}
                </span>
              )}
            </a>
          </nav>
          <span className="spacer" />
          {session?.user && (
            <span className="user">
              <span className="user-icon" aria-hidden="true">👤</span>
              <span className="user-name">{session.user}</span>
              <button
                className="small-button"
                disabled={!!switchBlocker}
                title={switchBlocker || "Odjava sa TiM ERP-a (sačuvana lozinka se briše)"}
                onClick={() => {
                  if (readyId && confirm("Odjaviti se? Sačuvana lozinka se briše, pa ćete je uneti ponovo.")) answer(readyId, "logout");
                }}
              >
                Odjava
              </button>
            </span>
          )}
        </div>
        <div className="top-row second">
          <CompanyInfo session={session} />
          {session?.user && (
            <button
              className="small-button"
              disabled={!!switchBlocker}
              title={switchBlocker || "Ponovo se prijavi i izaberi drugu firmu"}
              onClick={() => readyId && answer(readyId, "company")}
            >
              Promena firme
            </button>
          )}
          <span className={`status ${connected ? "" : "offline"}`}>
            {connected ? status || "Pokretanje..." : "Program nije pokrenut (python main.py)"}
          </span>
          <button className="live-toggle" onClick={toggleLive} aria-pressed={liveOpen}>
            ◉ Uživo
          </button>
        </div>
      </header>
      {section === "purs" ? (
        <main>
          {jobId && sub === "knjizenje" ? (
            <AnalyticsPage key={jobId} id={jobId} />
          ) : jobId && sub === "sadrzaj" ? (
            <ContentPage key={jobId} id={jobId} />
          ) : (
            <PursPage state={shared.purs} login={shared.purs_prijava} queue={shared.purs_red} />
          )}
        </main>
      ) : section === "izvestaji" ? (
        <main>
          {needsAnswer && (
            <a className="banner" href="#/">
              Program čeka vaš odgovor na početnoj strani →
            </a>
          )}
          {!shared.reports ? (
            <div className="card working">
              <span className="spinner" /> Učitavanje izveštaja…
            </div>
          ) : jobId ? (
            <ReportPage key={jobId} state={shared.reports} reportId={jobId} resultId={sub} jobsBusy={jobBusy} />
          ) : (
            <ReportsList state={shared.reports} jobsBusy={jobBusy} />
          )}
        </main>
      ) : section === "poslovi" ? (
        <main>
          {needsAnswer && (
            <a className="banner" href="#/">
              Program čeka vaš odgovor na početnoj strani →
            </a>
          )}
          {!shared.jobs ? (
            <div className="card working">
              <span className="spinner" /> Učitavanje poslova…
            </div>
          ) : jobId && sub === "izvestaj" && report ? (
            <RunReport
              key={`${jobId}/${report}`}
              jobId={jobId}
              jobName={shared.jobs.jobs.find((j) => j.id === jobId)?.name ?? "Posao"}
              run={shared.jobs.runs[jobId]}
              report={report}
            />
          ) : jobId ? (
            <JobPage key={jobId} state={shared.jobs} jobId={jobId} />
          ) : (
            <JobsList state={shared.jobs} />
          )}
        </main>
      ) : (
        <main>
          {prompt?.kind === "login" && <LoginForm key={prompt.id} prompt={prompt} />}
          {prompt?.kind === "wait" && <WaitPanel key={prompt.id} prompt={prompt} />}
          {prompt?.kind === "company" && <CompanyPicker key={prompt.id} prompt={prompt} />}
          {prompt?.kind === "ready" && <Ready key={prompt.id} prompt={prompt} />}
          {prompt?.kind === "done" && <Done key={prompt.id} prompt={prompt} />}
          {!prompt && connected && (
            <div className="card working">
              <span className="spinner" /> {status || "Radim..."}
            </div>
          )}
          {(!prompt || prompt.kind === "ready" || prompt.kind === "wait") && (
            <Home shared={shared} prompt={prompt} connected={connected} />
          )}
        </main>
      )}
      {liveOpen && <LiveView onClose={toggleLive} />}
      <PursNotices state={shared.purs} />
      <RunProgress jobs={shared.jobs} log={log} collapsed={progressCollapsed} onToggle={toggleProgress} />
      <button className="log-toggle" onClick={toggleLog} aria-expanded={logOpen} aria-controls="log-panel">
        {logOpen ? "Sakrij log ▾" : "Log ▴"}
      </button>
      <LogPanel text={log} open={logOpen} onClose={toggleLog} />
    </div>
  );
}

/** The open company in the header: name, PIB, year (or what the site shows if chosen in the browser). */
function CompanyInfo({ session }: { session: Session | undefined }) {
  const c = session?.company;
  if (!session?.user) return <span className="company muted">Niste prijavljeni</span>;
  if (!c) return <span className="company muted">Firma nije izabrana</span>;
  const name = c.name || c.naSajtu || "Firma izabrana u pretraživaču";
  return (
    <span className="company" title={c.naSajtu ? `Na sajtu: ${c.naSajtu}` : undefined}>
      <span className="muted">Firma:</span> <strong>{name}</strong>
      {c.pib && <span className="muted"> · PIB {c.pib}</span>}
      {c.year && <span className="muted"> · godina {c.year}</span>}
      {c.active === false && <span className="badge inactive-badge">neaktivna</span>}
    </span>
  );
}

/** The part of the URL after "#/", e.g. "poslovi/ab12cd34". */
function useHashRoute(): string {
  const read = () => location.hash.replace(/^#\/?/, "");
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

/** An on/off state the page remembers between visits. */
function useRememberedToggle(key: string): [boolean, () => void] {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem(key) === "1";
    } catch {
      return false;
    }
  });
  function toggle() {
    setOn((value) => {
      try {
        localStorage.setItem(key, value ? "0" : "1");
      } catch {
        // storage unavailable: the toggle still works for this visit
      }
      return !value;
    });
  }
  return [on, toggle];
}

// The server puts "YYYY-MM-DD HH:MM:SS" in front of every log line.
const TIMESTAMP = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+/;

/** Console log in an overlay panel that slides up from the bottom of the window. */
function LogPanel({ text, open, onClose }: { text: string; open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLPreElement>(null);
  const lines = useMemo(() => text.replace(/\n$/, "").split("\n"), [text]);

  // Always show the newest output.
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [text, open]);

  return (
    <aside id="log-panel" className={`log-panel ${open ? "open" : ""}`} aria-hidden={!open} inert={!open}>
      <div className="log-head">
        <h2>Log</h2>
        <button onClick={onClose} aria-label="Zatvori log">✕</button>
      </div>
      <pre ref={ref}>
        {lines.map((line, i) => {
          const time = TIMESTAMP.exec(line)?.[0];
          return (
            <div key={i} className="log-line">
              {time && <span className="log-time">{time.trimEnd()}</span>}
              {time ? line.slice(time.length) : line}
            </div>
          );
        })}
      </pre>
    </aside>
  );
}
