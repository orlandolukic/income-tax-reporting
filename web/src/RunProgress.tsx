import { useEffect, useState } from "react";
import { callApi, JobsState, Run, TaskResult } from "./api";
import { formatDuration, StatusBadge } from "./jobs/common";

/** One level of the path to the task being computed: "#2 Pretraga — red 3 / 4". */
type Step = { number: string; title: string; entry: TaskResult };

const FINISHED_SHOWN_MS = 15000;

/** Floating panel (bottom right) with the job being run: overall progress bar, the path to the task the
 * program is working on (with row counters), its progress text, elapsed time and the newest log line. */
export default function RunProgress(props: {
  jobs: JobsState | undefined;
  log: string;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const { jobs } = props;
  const runningId = jobs?.runner.running ?? null;
  const run = runningId ? jobs?.runs[runningId] : undefined;
  const [finished, setFinished] = useState<{ id: string; at: number } | null>(null);
  const [lastRunning, setLastRunning] = useState<string | null>(null);
  const [, tick] = useState(0);

  // Remember the job that just finished, to show its result for a while.
  useEffect(() => {
    if (runningId) setLastRunning(runningId);
    else if (lastRunning) {
      setFinished({ id: lastRunning, at: Date.now() });
      setLastRunning(null);
    }
  }, [runningId, lastRunning]);

  // Elapsed time and the auto-hide of the finished state.
  useEffect(() => {
    if (!runningId && !finished) return;
    const timer = setInterval(() => {
      tick((n) => n + 1);
      if (finished && Date.now() - finished.at > FINISHED_SHOWN_MS) setFinished(null);
    }, 1000);
    return () => clearInterval(timer);
  }, [runningId, finished]);

  if (!jobs) return null;
  const queued = jobs.runner.queued.length;
  const shownId = runningId ?? finished?.id ?? (queued ? jobs.runner.queued[0] : null);
  if (!shownId) return null;
  const job = jobs.jobs.find((j) => j.id === shownId);
  const name = job?.name || "Posao";
  const shownRun = run ?? (finished ? jobs.runs[finished.id] : undefined);
  const typeTitle = (type: string) => jobs.taskTypes.find((t) => t.id === type)?.title ?? type;

  const path = run ? activePath(run, typeTitle) : [];
  const percent = run ? Math.round(progressOf(run, path) * 100) : shownRun ? 100 : 0;
  const leaf = path[path.length - 1];
  const logLine = lastLine(props.log);
  const isDone = !run && !!shownRun;
  const label = run ? (leaf ? `#${leaf.number} ${leaf.title}` : "Pokretanje…") : isDone ? "Završeno" : "Pokreće se…";

  if (props.collapsed) {
    return (
      <button className={`run-pill ${isDone ? `done s-${shownRun?.status}` : ""}`} onClick={props.onToggle} title="Prikaži napredak">
        {run ? <span className="spinner small" /> : null}
        <span className="run-pill-text">
          {name}: {label}
        </span>
        {run && <span className="run-pill-pct">{percent}%</span>}
        <span className="run-pill-bar" style={{ width: `${percent}%` }} />
      </button>
    );
  }

  return (
    <section className="run-progress" aria-live="polite" aria-label="Napredak posla">
      <div className="run-head">
        {run ? <span className="spinner small" /> : shownRun && <StatusBadge status={shownRun.status} />}
        <a className="run-name" href={`#/poslovi/${shownId}`} title="Otvori posao">
          {name}
        </a>
        <span className="muted small">
          {shownRun ? formatDuration(shownRun.started_at, shownRun.finished_at) : ""}
        </span>
        <span className="spacer" />
        {run && (
          <button className="small-button" onClick={() => callApi("jobs", "cancel", {})} title="Zaustavi posao posle trenutnog koraka">
            ■ Zaustavi
          </button>
        )}
        <button className="icon" onClick={props.onToggle} aria-label="Skupi" title="Skupi">
          ▾
        </button>
        {isDone && (
          <button className="icon" onClick={() => setFinished(null)} aria-label="Zatvori" title="Zatvori">
            ✕
          </button>
        )}
      </div>

      <div className="run-bar" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${percent}%` }} className={isDone ? `s-${shownRun?.status}` : ""} />
      </div>
      <div className="run-meta small muted">
        {run ? (
          <>
            {percent}% · zadatak {topIndex(run, path) + 1} od {run.tasks.length}
            {queued > 0 && ` · na redu još ${queued}`}
          </>
        ) : isDone ? (
          <>{summary(shownRun!)}</>
        ) : (
          "Pokreće se…"
        )}
      </div>

      {run && path.length > 0 && (
        <ol className="run-path">
          {path.map((step, i) => {
            const rows = step.entry.red_napredak;
            const last = i === path.length - 1;
            return (
              <li key={step.entry.id} className={last ? "current" : ""} style={{ paddingLeft: i * 12 }}>
                <span className="task-no">{step.number}</span>
                <span className="run-step-title">{step.title}</span>
                {rows && (
                  <span className="muted small">
                    {" "}
                    — red {rows[0]} / {rows[1]}
                  </span>
                )}
                {last && step.entry.progress && <div className="run-step-progress small">{step.entry.progress}</div>}
              </li>
            );
          })}
        </ol>
      )}
      {isDone && shownRun?.napomena && <p className="small warning run-note">{shownRun.napomena}</p>}
      {logLine && (
        <div className="run-log small" title={logLine}>
          {logLine}
        </div>
      )}
    </section>
  );
}

/** The chain of result entries from the top-level task down to the one being computed. */
function activePath(run: Run, typeTitle: (type: string) => string): Step[] {
  const target = run.aktivno?.id;
  const find = (entries: TaskResult[], prefix: string): Step[] | null => {
    for (let i = 0; i < entries.length; i++) {
      const e = entries[i];
      const step: Step = { number: `${prefix}${i + 1}`, title: e.title || typeTitle(e.type), entry: e };
      if (e.id === target) return [step];
      const below = find(e.subtasks ?? [], `${step.number}.`);
      if (below) return [step, ...below];
    }
    return null;
  };
  if (target) return find(run.tasks, "") ?? [];
  // Before the first task is marked: the first running top-level task.
  const i = run.tasks.findIndex((t) => t.status === "running");
  return i >= 0 ? [{ number: String(i + 1), title: run.tasks[i].title || typeTitle(run.tasks[i].type), entry: run.tasks[i] }] : [];
}

function topIndex(run: Run, path: Step[]): number {
  const id = path[0]?.entry.id;
  const i = run.tasks.findIndex((t) => t.id === id);
  return i >= 0 ? i : run.tasks.filter((t) => t.status !== "pending").length;
}

/** 0..1: finished top-level tasks, plus how far the current one is (its rows, then its subtasks' rows,
 * then e.g. "Pročitano 1200 / 4260 redova" of the task being computed). */
function progressOf(run: Run, path: Step[]): number {
  const total = run.tasks.length || 1;
  const fraction = (level: number): number => {
    const step = path[level];
    if (!step) return 0;
    const rows = step.entry.red_napredak;
    if (rows && rows[1] > 0) return Math.min(1, (rows[0] - 1 + fraction(level + 1)) / rows[1]);
    if (level === path.length - 1) {
      const m = /(\d+)\s*\/\s*(\d+)/.exec(step.entry.progress?.replace(/^Red [\d/]+:\s*/, "") ?? "");
      return m && +m[2] > 0 ? Math.min(1, +m[1] / +m[2]) : 0;
    }
    return fraction(level + 1);
  };
  return Math.min(1, (topIndex(run, path) + fraction(0)) / total);
}

function summary(run: Run): string {
  const counts: Record<string, number> = {};
  for (const t of run.tasks) counts[t.status] = (counts[t.status] ?? 0) + 1;
  const parts = [`${run.tasks.length} zadataka`];
  if (counts.done) parts.push(`${counts.done} završeno`);
  if (counts.failed) parts.push(`${counts.failed} sa greškom`);
  if (counts.skipped) parts.push(`${counts.skipped} preskočeno`);
  return parts.join(" · ");
}

const TIMESTAMP = /^\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2})\s+/;

function lastLine(log: string): string {
  const lines = log.replace(/\n+$/, "").split("\n");
  for (let i = lines.length - 1; i >= 0 && i >= lines.length - 20; i--) {
    const line = lines[i].trim();
    if (line && !line.startsWith("Traceback") && !line.startsWith("File ")) {
      const m = TIMESTAMP.exec(lines[i]);
      return m ? `${m[1]}  ${lines[i].slice(m[0].length).trim()}` : line;
    }
  }
  return "";
}
