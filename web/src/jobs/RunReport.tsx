import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { callApi, Run, RunStatus, TaskStatus } from "../api";
import { Check, CodeBlock } from "../controls";
import { formatDuration, formatTime, StatusBadge } from "./common";
import { ValuePreview } from "./TaskCard";

/** One execution of a task (once per row it ran for), recorded by the runner (runner._begin_step). */
type Step = {
  n: number;
  pocetak: number;
  trajanje: number | null; // seconds; null while it runs
  id: string;
  broj: string; // task number, e.g. "2.2.1"
  naziv: string;
  vrsta: string;
  red: string; // row label, e.g. "3" or "3/2"
  red_opis: string; // a few cells of that row
  status: TaskStatus;
  ulaz: unknown; // params after references were resolved
  rezultat: string;
  detalji: unknown; // shortened value
  greska: string;
  napomena: string;
  zapis?: string; // console output while it ran
  kontekst?: Context; // a "Uslov": what its checks could see (runner._context)
};

/** An earlier task as a "Uslov" saw it: its newest step and (for the first CONTEXT_FULL conditions) its value. */
type ContextTask = {
  broj: string; naziv: string; vrsta: string; status: TaskStatus; red: string; red_opis: string; rezultat: string;
  greska: string; napomena: string; vrednost?: unknown;
};
type Context = {
  zadaci: ContextTask[];
  trenutni_red: Record<string, unknown> | null;
  petlje: { broj: string; naziv: string; prolaz: number; red: unknown }[];
  skraceno: boolean; // too many conditions in this run: values of earlier tasks left out
};

type RunHeader = { status: RunStatus; started_at: number; finished_at: number | null; napomena?: string };
/** A saved report, as listed on the job page (store.step_history). */
export type HistoryItem = RunHeader & { fajl: string; koraci: number; greske?: number };
type Report = { istorija: HistoryItem[]; uzivo: boolean; od: number; run: RunHeader | null; koraci: Step[]; fajl?: string };

const PAGE = 200;
export const LIVE = "uzivo"; // the report of the run in progress

export const reportHref = (jobId: string, report: string) => `#/poslovi/${jobId}/izvestaj/${report}`;

/** The saved reports of a job, newest first (refreshed when a run starts or ends). */
export function useHistory(jobId: string, run: Run | undefined): HistoryItem[] {
  const [history, setHistory] = useState<HistoryItem[]>([]);
  useEffect(() => {
    let cancelled = false;
    callApi<{ istorija: HistoryItem[] }>("jobs", "history", { id: jobId })
      .then((r) => !cancelled && setHistory(r.istorija))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [jobId, run?.started_at, run?.finished_at]);
  return history;
}

/** "Summary" page of one run: timing per task and every step with its row, input, result and console output. */
export default function RunReport(props: { jobId: string; jobName: string; run: Run | undefined; report: string }) {
  const { jobId, run, report } = props;
  const chosen = report === LIVE ? "" : report; // "" = the run in progress (or the newest saved one)
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [header, setHeader] = useState<RunHeader | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [file, setFile] = useState("");
  const [live, setLive] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [taskFilter, setTaskFilter] = useState("");
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [text, setText] = useState("");
  const [shown, setShown] = useState(PAGE);
  const [open, setOpen] = useState<number | null>(null);
  const stepsRef = useRef<Step[]>([]);
  stepsRef.current = steps;

  const running = run?.status === "running";
  const liveRef = useRef(live);
  liveRef.current = live;
  const request = useRef(0);

  async function load() {
    const id = ++request.current;
    const current = stepsRef.current;
    // Live: ask only for the steps from the first unfinished one (or after the last one) on.
    const unfinished = current.findIndex((s) => s.status === "running");
    const od = liveRef.current && !chosen ? (unfinished >= 0 ? unfinished : current.length) : 0;
    try {
      const r = await callApi<Report>("jobs", "steps", { id: jobId, fajl: chosen, od });
      if (id !== request.current) return; // a newer request was made meanwhile
      setHistory(r.istorija);
      setHeader(r.run);
      setLive(r.uzivo);
      setFile(r.fajl ?? "");
      setSteps(r.uzivo && r.od > 0 ? [...stepsRef.current.slice(0, r.od), ...r.koraci] : r.koraci);
      setLoaded(true);
      setError("");
    } catch (e) {
      if (id === request.current) setError((e as Error).message);
    }
  }

  // The live report of a run that has ended becomes that run's saved report.
  useEffect(() => {
    if (report === LIVE && !running && run?.koraci_fajl) location.replace(reportHref(jobId, run.koraci_fajl));
  }, [report, running, run?.koraci_fajl, jobId]);

  // When a run starts or ends, or another report is opened; while a job runs, every 1.5 s.
  useEffect(() => {
    liveRef.current = false; // start over
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, chosen, run?.started_at, run?.finished_at]);
  useEffect(() => {
    if (!running || chosen) return;
    const timer = setInterval(load, 1500);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, chosen]);

  const tasks = useMemo(() => summarize(steps), [steps]);
  const filtered = useMemo(() => {
    const q = text.trim().toLowerCase();
    return steps.filter(
      (s) =>
        (!taskFilter || s.broj === taskFilter) &&
        (!onlyProblems || s.status === "failed" || !!s.napomena) &&
        (!q || [s.red_opis, s.rezultat, s.napomena, s.greska, s.naziv, s.red].some((v) => v?.toLowerCase().includes(q))),
    );
  }, [steps, taskFilter, onlyProblems, text]);

  useEffect(() => setShown(PAGE), [taskFilter, onlyProblems, text, chosen]);

  const failed = steps.filter((s) => s.status === "failed").length;
  const total = steps.reduce((sum, s) => sum + (s.trajanje ?? 0), 0);
  // Neighbouring reports (history is newest first).
  const index = history.findIndex((h) => h.fajl === (chosen || file));
  const newer = index > 0 ? history[index - 1] : undefined;
  const older = index >= 0 ? history[index + 1] : undefined;

  return (
    <div className="card run-report">
      <div className="page-head">
        <a href={`#/poslovi/${jobId}`} className="back">
          ← {props.jobName}
        </a>
        <span className="spacer" />
        {older && (
          <a className="button" href={reportHref(jobId, older.fajl)} title={formatTime(older.started_at)}>
            ‹ Starije
          </a>
        )}
        {newer && (
          <a className="button" href={reportHref(jobId, newer.fajl)} title={formatTime(newer.started_at)}>
            Novije ›
          </a>
        )}
        {file && !live && (
          <>
            <a className="button" href={`/files/results/${file}.csv`} download>
              CSV
            </a>
            <a className="button" href={`/files/results/${file}.json`} download>
              JSON
            </a>
          </>
        )}
      </div>
      <h2 className="report-title">
        Summary{header && <span className="muted"> · {formatTime(header.started_at)}</span>}
        {live && <span className="badge live-badge">uživo</span>}
      </h2>
      {error && <p className="error small">{error}</p>}
      {!header ? (
        <p className="muted">{loaded ? "Ovaj izveštaj ne postoji (čuva se poslednjih 20 pokretanja)." : "Učitavanje…"}</p>
      ) : (
        <>
          <div className="report-facts">
            <StatusBadge status={header.status} />
            <span>
              <span className="muted">Početak</span> {formatTime(header.started_at)}
            </span>
            <span>
              <span className="muted">Kraj</span> {header.finished_at ? formatTime(header.finished_at) : "—"}
            </span>
            <span>
              <span className="muted">Trajanje</span> {formatDuration(header.started_at, header.finished_at)}
            </span>
            <span>
              <span className="muted">Koraka</span> {steps.length}
            </span>
            <span>
              <span className="muted">Vreme u zadacima</span> {seconds(total)}
            </span>
            {failed > 0 && <span className="error">{failed} sa greškom</span>}
          </div>
          {header.napomena && <p className="small warning">{header.napomena}</p>}

          <h3>Po zadacima</h3>
          <div className="table-wrap">
            <table className="report-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Zadatak</th>
                  <th className="num">Izvršeno</th>
                  <th className="num">Uspešno</th>
                  <th className="num">Greške</th>
                  <th className="num">Ukupno</th>
                  <th className="num">Prosek</th>
                  <th className="num">Najduže</th>
                  <th>Napomene</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => (
                  <tr key={t.broj} className="clickable" onClick={() => setTaskFilter(t.broj === taskFilter ? "" : t.broj)}>
                    <td className="mono">{t.broj}</td>
                    <td>
                      {t.naziv}
                      {t.naziv !== t.vrsta && <span className="muted small"> · {t.vrsta}</span>}
                    </td>
                    <td className="num">{t.count}</td>
                    <td className="num">{t.done}</td>
                    <td className={`num ${t.failed ? "error" : ""}`}>{t.failed}</td>
                    <td className="num">{seconds(t.total)}</td>
                    <td className="num">{seconds(t.count ? t.total / t.count : 0)}</td>
                    <td className="num">{seconds(t.max)}</td>
                    <td className="small">{Object.entries(t.notes).map(([n, c]) => `${n} (${c}×)`).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3>Koraci</h3>
          <div className="report-filters">
            <select value={taskFilter} onChange={(e) => setTaskFilter(e.target.value)} aria-label="Zadatak">
              <option value="">Svi zadaci</option>
              {tasks.map((t) => (
                <option key={t.broj} value={t.broj}>
                  #{t.broj} {t.naziv}
                </option>
              ))}
            </select>
            <Check checked={onlyProblems} onChange={setOnlyProblems}>
              Samo greške i napomene
            </Check>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Traži (dokument, vrednost, greška…)" />
            <span className="muted small">
              {filtered.length} od {steps.length}
            </span>
          </div>
          <div className="table-wrap tall">
            <table className="report-table steps">
              <thead>
                <tr>
                  <th className="num">Korak</th>
                  <th>Vreme</th>
                  <th className="num">Trajanje</th>
                  <th>Zadatak</th>
                  <th>Red</th>
                  <th>Status</th>
                  <th>Rezultat</th>
                </tr>
              </thead>
              <tbody>
                {filtered.slice(0, shown).map((s) => (
                  <Fragment key={s.n}>
                    <tr className={`clickable ${s.status === "failed" ? "row-failed" : ""} ${open === s.n ? "is-open" : ""}`} onClick={() => setOpen(open === s.n ? null : s.n)}>
                      <td className="num">{s.n}</td>
                      <td className="mono small">{clock(s.pocetak)}</td>
                      <td className="num">{s.trajanje === null ? "…" : seconds(s.trajanje)}</td>
                      <td>
                        <span className="mono">#{s.broj}</span> {s.naziv}
                      </td>
                      <td className="small">
                        {s.red && <span className="mono">{s.red}</span>} {s.red_opis}
                      </td>
                      <td>
                        <StatusBadge status={s.status} />
                      </td>
                      <td className="small">
                        {s.greska && <div className="error">{s.greska}</div>}
                        {s.napomena && <div className="warning">{s.napomena}</div>}
                        {s.rezultat}
                      </td>
                    </tr>
                    {open === s.n && (
                      <tr className="step-detail">
                        <td colSpan={7}>
                          <StepDetail step={s} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          {filtered.length > shown && (
            <button onClick={() => setShown(shown + PAGE)}>Prikaži još ({filtered.length - shown})</button>
          )}
        </>
      )}
    </div>
  );
}

function StepDetail({ step }: { step: Step }) {
  const [json, setJson] = useState(false);
  const hasValue = step.detalji !== null && step.detalji !== undefined;
  const preview = hasValue && !json ? <ValuePreview value={step.detalji} /> : null;
  return (
    <div className="step-detail-grid">
      <div className="wide">
        <div className="detail-head">
          <strong>Vrednost</strong>
          {hasValue && (
            <button className="link small" onClick={() => setJson(!json)}>
              {json ? "Tabela" : "JSON"}
            </button>
          )}
        </div>
        {!hasValue ? <p className="muted small">Zadatak nije vratio vrednost.</p> : preview ?? <CodeBlock value={step.detalji} />}
      </div>
      <div>
        <strong>Ulaz</strong> <span className="muted small">(podešavanja sa vrednostima iz ranijih zadataka)</span>
        {step.ulaz === null || step.ulaz === undefined ? <p className="muted small">—</p> : <CodeBlock value={step.ulaz} />}
      </div>
      {step.zapis?.trim() && (
        <div>
          <strong>Zapis</strong> <span className="muted small">(ispis programa tokom ovog koraka)</span>
          <CodeBlock value={step.zapis.trim()} />
        </div>
      )}
      {step.kontekst && <ConditionContext context={step.kontekst} />}
    </div>
  );
}

/** What a "Uslov" could see when it was checked: the row it ran for, the row of each loop it is in, and every task
 * that ran before it (newest step: status, row, result, and its value: click a task to see it). */
function ConditionContext({ context }: { context: Context }) {
  const [open, setOpen] = useState<string | null>(null);
  const cells = (row: unknown) =>
    row && typeof row === "object"
      ? Object.entries(row as Record<string, unknown>).map(([k, v]) => (
          <span key={k} className="total">
            {k} <strong>{String(v ?? "")}</strong>
          </span>
        ))
      : null;
  return (
    <div className="wide condition-context">
      <strong>Kontekst provere</strong>{" "}
      <span className="muted small">(šta je uslov video u trenutku provere: trenutni red, petlje i svi raniji zadaci)</span>
      {context.trenutni_red && (
        <div className="totals small">
          <span className="muted">Trenutni red:</span> {cells(context.trenutni_red)}
        </div>
      )}
      {context.petlje.map((l) => (
        <div key={l.broj} className="totals small">
          <span className="muted">
            #{l.broj} {l.naziv}, prolaz {l.prolaz}:
          </span>{" "}
          {cells(l.red)}
        </div>
      ))}
      {context.zadaci.length === 0 ? (
        <p className="muted small">Pre ovog uslova nije izvršen nijedan zadatak.</p>
      ) : (
        <div className="table-wrap">
          <table className="report-table">
            <thead>
              <tr>
                <th>Zadatak</th>
                <th>Red</th>
                <th>Status</th>
                <th>Rezultat</th>
              </tr>
            </thead>
            <tbody>
              {context.zadaci.map((t) => (
                <Fragment key={t.broj}>
                  <tr
                    className={`${t.vrednost !== undefined ? "clickable" : ""} ${open === t.broj ? "is-open" : ""}`}
                    onClick={() => t.vrednost !== undefined && setOpen(open === t.broj ? null : t.broj)}
                  >
                    <td>
                      {t.vrednost !== undefined && <span className="muted">{open === t.broj ? "▾" : "▸"} </span>}
                      <span className="mono">#{t.broj}</span> {t.naziv}
                      {t.naziv !== t.vrsta && <span className="muted small"> · {t.vrsta}</span>}
                    </td>
                    <td className="small">
                      {t.red && <span className="mono">{t.red}</span>} {t.red_opis}
                    </td>
                    <td>
                      <StatusBadge status={t.status} />
                    </td>
                    <td className="small">
                      {t.greska && <div className="error">{t.greska}</div>}
                      {t.napomena && <div className="warning">{t.napomena}</div>}
                      {t.rezultat}
                    </td>
                  </tr>
                  {open === t.broj && (
                    <tr className="step-detail">
                      <td colSpan={4}>
                        <ValuePreview value={t.vrednost} />
                        <CodeBlock value={t.vrednost} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {context.skraceno && (
        <p className="muted small">U ovom pokretanju je bilo mnogo provera: vrednosti ranijih zadataka nisu sačuvane za ovu.</p>
      )}
    </div>
  );
}

type TaskSummary = {
  broj: string; naziv: string; vrsta: string; count: number; done: number; failed: number; total: number; max: number;
  notes: Record<string, number>;
};

function summarize(steps: Step[]): TaskSummary[] {
  const byTask = new Map<string, TaskSummary>();
  for (const s of steps) {
    let t = byTask.get(s.broj);
    if (!t) {
      t = { broj: s.broj, naziv: s.naziv, vrsta: s.vrsta, count: 0, done: 0, failed: 0, total: 0, max: 0, notes: {} };
      byTask.set(s.broj, t);
    }
    t.count++;
    if (s.status === "done") t.done++;
    if (s.status === "failed") t.failed++;
    t.total += s.trajanje ?? 0;
    t.max = Math.max(t.max, s.trajanje ?? 0);
    if (s.napomena) t.notes[s.napomena] = (t.notes[s.napomena] ?? 0) + 1;
  }
  const key = (b: string) => b.split(".").map((x) => x.padStart(4, "0")).join(".");
  return [...byTask.values()].sort((a, b) => (key(a.broj) < key(b.broj) ? -1 : 1));
}

function seconds(s: number): string {
  if (s < 10) return `${s.toFixed(2)} s`;
  if (s < 60) return `${s.toFixed(1)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

function clock(t: number): string {
  return new Date(t * 1000).toLocaleTimeString("sr-Latn", { hour12: false });
}
