import { useEffect, useMemo, useState } from "react";
import { callApi, children, isRef, Job, JobsState, newTask, Task, TaskResult } from "../api";
import { inferKinds, Kind, KindsContext } from "./kinds";
import { formatDuration, formatTime, runBlocker, StatusBadge } from "./common";
import { RunnerPill } from "./JobsList";
import { HistoryItem, LIVE, reportHref, useHistory } from "./RunReport";
import TaskCard, { ChoicesContext, DropEnd, loopColumns, Source, TypeOptions } from "./TaskCard";
import { DragApi, DragContext, dropBlocker, duplicateTask, moveTask as moveInTree, ROOT } from "./tree";

type Draft = Pick<Job, "name" | "description" | "tasks">;

const draftOf = (job: Job): Draft => ({ name: job.name, description: job.description, tasks: job.tasks });

export default function JobPage({ state, jobId }: { state: JobsState; jobId: string }) {
  const job = state.jobs.find((j) => j.id === jobId);
  const run = state.runs[jobId];
  const types = useMemo(() => Object.fromEntries(state.taskTypes.map((t) => [t.id, t])), [state.taskTypes]);
  const [draft, setDraft] = useState<Draft | null>(job ? draftOf(job) : null);
  const [addType, setAddType] = useState(state.taskTypes[0]?.id ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState<string | null>(null); // id of the task being dragged

  const dirty = !!job && !!draft && JSON.stringify(draft) !== JSON.stringify(draftOf(job));

  // Take over changes saved elsewhere (e.g. another tab) unless there are unsaved edits here.
  useEffect(() => {
    if (job && !dirty) setDraft(draftOf(job));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.updated_at]);

  // Warn before leaving the page with unsaved changes.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (!job || !draft) {
    return (
      <div className="card">
        <p>{state.company ? `Firma ${state.company.label} nema ovaj posao.` : "Izaberite firmu: svaka firma ima svoje poslove."}</p>
        <a href="#/poslovi">← Nazad na poslove</a>
      </div>
    );
  }

  const blocker = runBlocker(state.runner.ready, state.runner.running, state.runner.queued, jobId);
  const running = state.runner.running === jobId;
  const results: Record<string, TaskResult> = Object.fromEntries((run?.tasks ?? []).map((r) => [r.id, r]));

  // Kind of each task's columns: known in advance (task type), then what its last run returned; a "Petlja" has the
  // kinds of its data set.
  const kinds: Record<string, Record<string, Kind>> = {};
  const loops: [string, string][] = [];
  const walkKinds = (list: Task[], resultOf: (id: string) => TaskResult | undefined) => {
    for (const t of list) {
      const res = resultOf(t.id);
      const known = Object.fromEntries((types[t.type]?.outputColumns ?? []).map((c) => [c, "text" as Kind]));
      kinds[t.id] = { ...known, ...(types[t.type]?.columnKinds ?? {}), ...inferKinds(res?.value) };
      if (t.type === "loop" && isRef(t.params.izvor)) loops.push([t.id, t.params.izvor.ref]);
      walkKinds(children(t), (id) => res?.subtasks?.find((r) => r.id === id));
    }
  };
  walkKinds(draft?.tasks ?? [], (id) => results[id]);
  for (let pass = 0; pass < 3; pass++) for (const [loop, source] of loops) kinds[loop] = { ...kinds[source], ...kinds[loop] };

  // The page the nearest earlier "Otvori stranicu" task opens, and its known columns.
  function pageBefore(index: number): string | undefined {
    for (let i = index - 1; i >= 0; i--) {
      const t = draft!.tasks[i];
      if (t.type === "open_menu" && typeof t.params.item === "string" && t.params.item) return t.params.item;
    }
    return undefined;
  }
  const columnsOf = (path: string | undefined) => (path && state.pages[path]?.tabele[0]?.kolone) || [];

  // The columns of a task's rows: from its last run, else what is known in advance.
  function columnsOfTask(t: Task, index: number, result: TaskResult | undefined): string[] {
    const value = result?.value as { kolone?: string[] } | null | undefined;
    if (value?.kolone?.length) return value.kolone;
    if (t.type === "search") return columnsOf(pageBefore(index));
    if (t.type === "loop") return loopColumns(t, sourcesFor(index)) ?? [];
    return types[t.type]?.outputColumns ?? [];
  }

  // Earlier tasks (and their subtasks, joined over all rows) this one can take data from.
  function sourcesFor(index: number): Source[] {
    return draft!.tasks.slice(0, index).flatMap((t, i) => {
      const title = t.title || types[t.type]?.title || t.type;
      const own: Source = {
        id: t.id, number: String(i + 1), title, kind: "task",
        columns: columnsOfTask(t, i, results[t.id]), totals: types[t.type]?.totals ?? [],
      };
      // Subtasks at any depth, each joined over all its runs.
      const subs = (list: Task[], prefix: string, parent: TaskResult | undefined): Source[] =>
        list.flatMap((sub, j) => {
          const number = `${prefix}.${j + 1}`;
          const res = parent?.subtasks?.find((r) => r.id === sub.id);
          return [
            {
              id: sub.id, number, kind: "task" as const,
              title: `${sub.title || types[sub.type]?.title || sub.type} (svi redovi)`,
              columns: columnsOfTask(sub, i, res), totals: types[sub.type]?.totals ?? [],
            },
            ...subs(children(sub), number, res),
          ];
        });
      return [own, ...subs(children(t), String(i + 1), results[t.id])];
    });
  }

  function update(patch: Partial<Draft>) {
    setDraft((d) => (d ? { ...d, ...patch } : d));
  }

  function updateTask(index: number, patch: Partial<Task>) {
    update({ tasks: draft!.tasks.map((t, i) => (i === index ? { ...t, ...patch } : t)) });
  }

  function moveTask(index: number, delta: number) {
    const tasks = [...draft!.tasks];
    const [task] = tasks.splice(index, 1);
    tasks.splice(index + delta, 0, task);
    update({ tasks });
  }

  const drag: DragApi = {
    dragging,
    // After the browser has started the drag: changing the page right away can cancel it.
    start: (id) => setTimeout(() => setDragging(id)),
    end: () => setDragging(null),
    blocker: (target) => (dragging && draft ? dropBlocker(draft.tasks, dragging, target, types) : "-"),
    drop: (target) => {
      if (dragging) update({ tasks: moveInTree(draft!.tasks, dragging, target, types) });
      setDragging(null);
    },
    move: (id, target) => {
      const why = draft ? dropBlocker(draft.tasks, id, target, types) : "-";
      if (!why) update({ tasks: moveInTree(draft!.tasks, id, target, types) });
      return why;
    },
  };

  function addTask() {
    const type = types[addType];
    if (!type) return;
    update({ tasks: [...draft!.tasks, newTask(type)] });
  }

  async function act(action: () => Promise<unknown>) {
    setError("");
    setBusy(true);
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Show the job as the server stored it (else it could look changed only because of key order).
  const save = async () => {
    const saved = await callApi<{ job: Job }>("jobs", "save", { job: { ...job, ...draft }, company: state.company?.key });
    setDraft(draftOf(saved.job));
  };

  return (
    <div className="job-page">
      <Summaries jobId={jobId} run={run} />
      <div className="card">
        <div className="page-head">
          <a href="#/poslovi" className="back">
            ← Poslovi
          </a>
          <RunnerPill state={state} />
        </div>
        <label>
          Naziv posla
          <input className="job-title" value={draft.name} onChange={(e) => update({ name: e.target.value })} />
        </label>
        <label>
          Opis
          <textarea
            rows={2}
            value={draft.description}
            placeholder="Šta ovaj posao radi (opciono)"
            onChange={(e) => update({ description: e.target.value })}
          />
        </label>
      </div>

      <div className="card">
        <div className="page-head">
          <h2>Zadaci</h2>
          <span className="muted small">
            Izvršavaju se redom, odozgo nadole. Zadatak sa greškom zaustavlja posao. „Uslov“ bira granu (AKO / INAČE
            AKO / INAČE) čiji se zadaci izvršavaju.
          </span>
        </div>
        {draft.tasks.length === 0 && <p className="muted">Posao još nema zadataka. Dodajte prvi ispod.</p>}
        <KindsContext.Provider value={kinds}>
        <ChoicesContext.Provider value={{ known: state.choices ?? {} }}>
        <DragContext.Provider value={drag}>
          <ol className="tasks">
          {draft.tasks.map((task, i) => (
            <TaskCard
              key={task.id}
              index={i}
              count={draft.tasks.length}
              task={task}
              type={types[task.type]}
              types={state.taskTypes}
              result={results[task.id]}
              number={String(i + 1)}
              ownColumns={columnsOfTask(task, i, results[task.id])}
              sources={sourcesFor(i)}
              pageBefore={pageBefore(i)}
              pageColumns={columnsOf(pageBefore(i))}
              pages={state.pages}
              jumpTargets={draft.tasks.slice(i + 1).map((t, k) => ({
                id: t.id,
                number: String(i + k + 2),
                title: t.title || types[t.type]?.title || t.type,
              }))}
              onChange={(patch) => updateTask(i, patch)}
              onMove={(delta) => moveTask(i, delta)}
              onRemove={() => update({ tasks: draft.tasks.filter((_, j) => j !== i) })}
              onDuplicate={() => update({ tasks: [...draft.tasks.slice(0, i + 1), duplicateTask(task), ...draft.tasks.slice(i + 1)] })}
            />
          ))}
          </ol>
          <DropEnd slot={ROOT} />
        </DragContext.Provider>
        </ChoicesContext.Provider>
        </KindsContext.Provider>
        <div className="add-task">
          <select value={addType} onChange={(e) => setAddType(e.target.value)}>
            <TypeOptions types={state.taskTypes} soon />
          </select>
          <button onClick={addTask}>+ Dodaj zadatak</button>
        </div>
      </div>

      {run && <RunSummary run={run} />}

      <div className="action-bar">
        {error && <span className="error">{error}</span>}
        {dirty && <span className="muted small">Nesačuvane izmene</span>}
        <span className="spacer" />
        <button
          className="danger-text"
          disabled={busy || running}
          onClick={() =>
            confirm(`Obrisati posao „${job.name}“?`) &&
            act(async () => {
              await callApi("jobs", "delete", { id: jobId, company: state.company?.key });
              location.hash = "#/poslovi";
            })
          }
        >
          Obriši posao
        </button>
        <button disabled={!dirty || busy} onClick={() => setDraft(draftOf(job))}>
          Odbaci
        </button>
        <button className={dirty ? "primary" : ""} disabled={!dirty || busy} onClick={() => act(save)}>
          Sačuvaj
        </button>
        {running ? (
          <button onClick={() => act(() => callApi("jobs", "cancel", {}))}>■ Zaustavi</button>
        ) : (
          <button
            className="primary"
            disabled={!!blocker || busy || draft.tasks.length === 0}
            title={blocker || (dirty ? "Sačuvaj i pokreni" : "")}
            onClick={() =>
              act(async () => {
                if (dirty) await save();
                await callApi("jobs", "run", { id: jobId, company: state.company?.key });
              })
            }
          >
            ▶ {dirty ? "Sačuvaj i pokreni" : "Pokreni"}
          </button>
        )}
      </div>
    </div>
  );
}

function RunSummary({ run }: { run: NonNullable<JobsState["runs"][string]> }) {
  const counts = run.tasks.reduce<Record<string, number>>((c, t) => ({ ...c, [t.status]: (c[t.status] ?? 0) + 1 }), {});
  return (
    <div className="card run-summary">
      <div className="page-head">
        <h2>Poslednje pokretanje</h2>
        <StatusBadge status={run.status} />
      </div>
      <p className="muted small">
        Početak {formatTime(run.started_at)} · trajanje {formatDuration(run.started_at, run.finished_at)} ·{" "}
        {run.tasks.length} zadataka
        {counts.done ? ` · ${counts.done} završeno` : ""}
        {counts.not_implemented ? ` · ${counts.not_implemented} nije implementirano` : ""}
        {counts.failed ? ` · ${counts.failed} sa greškom` : ""}
        {counts.skipped ? ` · ${counts.skipped} preskočeno` : ""}
      </p>
      {run.napomena && <p className="small warning">{run.napomena}</p>}
      <p className="muted small">Rezultat svakog zadatka je prikazan ispod njega u listi zadataka.</p>
    </div>
  );
}

/** The job's run reports ("Summary"), newest first; each opens on its own page. */
function Summaries({ jobId, run }: { jobId: string; run: NonNullable<JobsState["runs"][string]> | undefined }) {
  const history = useHistory(jobId, run);
  const [all, setAll] = useState(false);
  const running = run?.status === "running";
  if (!history.length && !running) return null;
  const rows: (HistoryItem & { live?: boolean })[] = [
    ...(running ? [{ fajl: LIVE, status: run.status, started_at: run.started_at, finished_at: null, koraci: run.koraci ?? 0, live: true }] : []),
    ...history,
  ];
  const shown = all ? rows : rows.slice(0, 5);
  return (
    <div className="card summaries">
      <div className="page-head">
        <h2>Summary</h2>
        <span className="muted small">izveštaj svakog pokretanja: koraci, vreme i vrednosti</span>
      </div>
      <div className="table-wrap">
        <table className="report-table">
          <thead>
            <tr>
              <th>Pokretanje</th>
              <th>Status</th>
              <th className="num">Trajanje</th>
              <th className="num">Koraka</th>
              <th className="num">Greške</th>
              <th>Napomena</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((h) => (
              <tr key={h.fajl} className="clickable" onClick={() => (location.hash = reportHref(jobId, h.fajl))}>
                <td>{formatTime(h.started_at)}</td>
                <td>
                  <StatusBadge status={h.status} />
                </td>
                <td className="num">{formatDuration(h.started_at, h.finished_at)}</td>
                <td className="num">{h.koraci}</td>
                <td className={`num ${h.greske ? "error" : ""}`}>{h.live ? "" : (h.greske ?? "")}</td>
                <td className="small">{h.napomena}</td>
                <td className="num">
                  <a href={reportHref(jobId, h.fajl)} onClick={(e) => e.stopPropagation()}>
                    Otvori ›
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 5 && (
        <button className="link-button" onClick={() => setAll(!all)}>
          {all ? "Prikaži manje" : `Prikaži sva (${rows.length})`}
        </button>
      )}
    </div>
  );
}
