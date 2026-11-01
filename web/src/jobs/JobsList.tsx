import { useState } from "react";
import { callApi, Job, JobsState } from "../api";
import { formatTime, runBlocker, StatusBadge } from "./common";

export default function JobsList({ state }: { state: JobsState }) {
  const { jobs, runs, runner, company } = state;
  const [error, setError] = useState("");

  async function create() {
    try {
      const { job } = await callApi<{ job: Job }>("jobs", "save", { job: { name: "Novi posao", tasks: [] }, company: company?.key });
      location.hash = `#/poslovi/${job.id}`;
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function run(id: string) {
    setError("");
    try {
      await callApi("jobs", "run", { id, company: company?.key });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="card">
      <div className="page-head">
        <h2>Poslovi{company && <span className="muted"> · {company.label}</span>}</h2>
        <RunnerPill state={state} />
        <button className="primary" onClick={create} disabled={!company}>
          + Novi posao
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {!company ? (
        <div className="empty">
          <p>Izaberite firmu.</p>
          <p className="muted">Svaka firma ima svoje poslove: prikazaće se kada se firma otvori.</p>
        </div>
      ) : jobs.length === 0 ? (
        <div className="empty">
          <p>Ova firma još nema poslova.</p>
          <p className="muted">
            Posao je niz zadataka koji se izvršavaju jedan za drugim u pretraživaču (npr. otvori stavku menija,
            pretraži vrednost, pročitaj rezultat). Napravite prvi posao dugmetom „+ Novi posao“.
          </p>
        </div>
      ) : (
        <div className="table-wrap tall">
          <table className="jobs-table">
            <thead>
              <tr>
                <th>Naziv</th>
                <th className="num">Zadaci</th>
                <th>Poslednje pokretanje</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => {
                const last = runs[job.id];
                const blocker = runBlocker(runner.ready, runner.running, runner.queued, job.id);
                return (
                  <tr key={job.id} onClick={() => (location.hash = `#/poslovi/${job.id}`)}>
                    <td>
                      <div className="job-name">{job.name}</div>
                      {job.description && <div className="muted small">{job.description}</div>}
                    </td>
                    <td className="num">{job.tasks.length}</td>
                    <td>
                      {last ? (
                        <span className="run-cell">
                          <StatusBadge status={last.status} />
                          <span className="muted small">{formatTime(last.started_at)}</span>
                        </span>
                      ) : (
                        <span className="muted small">nikad</span>
                      )}
                    </td>
                    <td className="actions" onClick={(e) => e.stopPropagation()}>
                      <button disabled={!!blocker || job.tasks.length === 0} title={blocker} onClick={() => run(job.id)}>
                        ▶ Pokreni
                      </button>
                      <a className="button" href={`#/poslovi/${job.id}`}>
                        Otvori
                      </a>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function RunnerPill({ state }: { state: JobsState }) {
  const { runner, jobs } = state;
  const running = runner.running && jobs.find((j) => j.id === runner.running);
  if (!runner.ready) return <span className="pill off">Pretraživač nije spreman</span>;
  if (running) return <span className="pill busy">Izvršava se: {running.name}</span>;
  return <span className="pill on">Pretraživač spreman{runner.status && ` · ${runner.status}`}</span>;
}
