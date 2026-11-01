import { useState } from "react";
import { callApi, ReportResult, ReportsState, ReportTypeInfo } from "../api";
import { formatDuration, formatTime } from "../jobs/common";
import { SettingsButton, settingsSummary } from "./ReportSettings";
import TurnoverView, { TurnoverValue, formatRsd } from "./TurnoverView";

const STATUS: Record<ReportResult["status"], string> = {
  running: "U izradi",
  done: "Završen",
  failed: "Greška",
  cancelled: "Zaustavljen",
};

export function ReportStatus({ status }: { status: ReportResult["status"] }) {
  return (
    <span className={`status-badge s-${status}`}>
      {status === "running" && <span className="spinner small" />}
      {STATUS[status]}
    </span>
  );
}

/** Why a report can't be started right now, or "" if it can. */
function runBlocker(state: ReportsState, jobsBusy: boolean): string {
  if (!state.runner.ready)
    return "Pretraživač nije spreman: prijavite se i izaberite firmu.";
  if (state.runner.running || state.runner.queued.length)
    return "Izveštaj se već izrađuje.";
  if (jobsBusy) return "Sačekajte da se posao završi.";
  return "";
}

async function start(
  state: ReportsState,
  id: string,
  setError: (e: string) => void,
) {
  setError("");
  try {
    await callApi("reports", "run", {
      report: id,
      company: state.company?.key,
    });
  } catch (e) {
    setError((e as Error).message);
  }
}

/** Have the program make the PDF / Excel copy of a result (freshly each time) and open it: the PDF in a new
 * tab (opened right away, so the popup blocker allows it), the Excel file as a download. */
async function openExport(
  report: string,
  id: string,
  format: "pdf" | "xlsx",
  setError: (e: string) => void,
) {
  setError("");
  const tab = format === "pdf" ? window.open("", "_blank") : null;
  tab?.document.write(
    "<p style='font:15px system-ui;color:#6b7280;padding:24px'>Pravljenje PDF-a…</p>",
  );
  try {
    const { fajl } = await callApi<{ fajl: string }>("reports", "export", {
      report,
      id,
      format,
    });
    const url = `/files/izvestaji/${encodeURIComponent(fajl)}`;
    if (tab) {
      tab.location.href = url;
    } else {
      const link = document.createElement("a");
      link.href = url;
      link.download = fajl;
      link.click();
    }
  } catch (e) {
    tab?.close();
    setError((e as Error).message);
  }
}

/** "#/izvestaji": the reports there are, with the last result of each. */
export function ReportsList({
  state,
  jobsBusy,
}: {
  state: ReportsState;
  jobsBusy: boolean;
}) {
  const [error, setError] = useState("");
  const blocker = runBlocker(state, jobsBusy);
  return (
    <div className="card">
      <div className="page-head">
        <h2>
          Izveštaji
          {state.company && (
            <span className="muted"> · {state.company.label}</span>
          )}
        </h2>
      </div>
      {error && <p className="error">{error}</p>}
      {!state.company && (
        <div className="empty">
          <p>Izaberite firmu.</p>
          <p className="muted">
            Izveštaji se prave za firmu koja je otvorena u pretraživaču.
          </p>
        </div>
      )}
      <div className="report-list">
        {state.types.map((type) => {
          const current =
            state.current?.report === type.id ? state.current : null;
          const last = current ?? state.history[type.id]?.[0];
          return (
            <div
              key={type.id}
              className="report-item"
              onClick={() => (location.hash = `#/izvestaji/${type.id}`)}
            >
              <div className="report-item-main">
                <div className="job-name">{type.title}</div>
                <div className="muted small">{type.description}</div>
                {last && <LastResult type={type} result={last} />}
              </div>
              <div
                className="report-item-actions"
                onClick={(e) => e.stopPropagation()}
              >
                <SettingsButton
                  state={state}
                  type={type}
                  disabled={current ? "Izveštaj se upravo izrađuje." : ""}
                />
                <button
                  className="primary"
                  disabled={!!blocker || !state.company}
                  title={blocker}
                  onClick={async () => {
                    await start(state, type.id, setError);
                    location.hash = `#/izvestaji/${type.id}`;
                  }}
                >
                  ▶ Napravi
                </button>
                <a className="button" href={`#/izvestaji/${type.id}`}>
                  Otvori
                </a>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function LastResult({
  type,
  result,
}: {
  type: ReportTypeInfo;
  result: ReportResult;
}) {
  const value = result.value as TurnoverValue | null;
  return (
    <div className="report-last small">
      <ReportStatus status={result.status} />
      <span className="muted">{formatTime(result.started_at)}</span>
      {type.id === "promet_12_meseci" &&
        value?.ukupno &&
        result.status !== "running" && (
          <span className={value.prekoracen ? "error" : ""}>
            Promet {formatRsd(value.ukupno.promet)} RSD (
            {value.procenat.toLocaleString("sr-Latn")} % limita)
          </span>
        )}
      {result.status === "running" && (
        <span className="muted">{result.progress}</span>
      )}
    </div>
  );
}

/** "#/izvestaji/<report>[/<result id>]": one report, its latest (or chosen) result and older ones. */
export function ReportPage({
  state,
  reportId,
  resultId,
  jobsBusy,
}: {
  state: ReportsState;
  reportId: string;
  resultId?: string;
  jobsBusy: boolean;
}) {
  const [error, setError] = useState("");
  const type = state.types.find((t) => t.id === reportId);
  if (!type) {
    return (
      <div className="card">
        <a href="#/izvestaji" className="back">
          ‹ Izveštaji
        </a>
        <p className="error">Nepoznat izveštaj.</p>
      </div>
    );
  }
  const history = state.history[reportId] ?? [];
  const current = state.current?.report === reportId ? state.current : null;
  const shown =
    (resultId && history.find((r) => r.id === resultId)) ||
    current ||
    history[0] ||
    null;
  const blocker = runBlocker(state, jobsBusy);

  return (
    <>
      <div className="card">
        <div className="page-head">
          <a href="#/izvestaji" className="back">
            ‹ Izveštaji
          </a>
          <h2>{type.title}</h2>
          <span className="head-actions">
            <SettingsButton
              state={state}
              type={type}
              disabled={current ? "Izveštaj se upravo izrađuje." : ""}
            />
            {current ? (
              <button onClick={() => callApi("reports", "cancel", {})}>
                ■ Zaustavi
              </button>
            ) : (
              <button
                className="primary"
                disabled={!!blocker || !state.company}
                title={blocker}
                onClick={() => {
                  if (resultId) location.hash = `#/izvestaji/${reportId}`;
                  start(state, reportId, setError);
                }}
              >
                ▶ Napravi izveštaj
              </button>
            )}
          </span>
        </div>
        <p className="muted">{type.description}</p>
        {state.company && type.settings.length > 0 && (
          <p className="settings-line small">
            <span className="muted">Podešavanja:</span>{" "}
            {settingsSummary(type, state.settings[type.id])}
          </p>
        )}
        {!shown && (
          <ul className="report-notes muted small">
            {type.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
        {error && <p className="error">{error}</p>}
      </div>

      {shown && (
        <div className="card">
          <div className="report-meta">
            <ReportStatus status={shown.status} />
            <span className="muted small">
              {formatTime(shown.started_at)} ·{" "}
              {formatDuration(shown.started_at, shown.finished_at)}
              {shown.firma && ` · ${shown.firma}`}
            </span>
            {shown.status === "running" && (
              <span className="progress-text">{shown.progress}</span>
            )}
            <span className="spacer" />
            {shown.status !== "running" && shown.value != null && (
              <>
                <button
                  onClick={() =>
                    openExport(reportId, shown.id, "pdf", setError)
                  }
                >
                  📄 PDF
                </button>
                <button
                  onClick={() =>
                    openExport(reportId, shown.id, "xlsx", setError)
                  }
                >
                  📊 Excel
                </button>
              </>
            )}
            {shown.fajl && (
              <a
                className="button"
                href={`/files/izvestaji/${encodeURIComponent(shown.fajl)}`}
                download
              >
                ⤓ CSV
              </a>
            )}
          </div>
          {shown.podesavanja && (
            <p className="muted small">
              Napravljen sa: {settingsSummary(type, shown.podesavanja)}
            </p>
          )}
          {shown.error && <p className="error">{shown.error}</p>}
          {reportId === "promet_12_meseci" && shown.value != null && (
            <TurnoverView
              value={shown.value as TurnoverValue}
              running={shown.status === "running"}
            />
          )}
        </div>
      )}

      {history.length > 0 && (
        <div className="card">
          <h3 className="report-history-title">Ranije izrađeni</h3>
          <div className="table-wrap">
            <table className="jobs-table">
              <thead>
                <tr>
                  <th>Vreme</th>
                  <th>Status</th>
                  <th>Rezultat</th>
                </tr>
              </thead>
              <tbody>
                {history.map((r) => {
                  const v = r.value as TurnoverValue | null;
                  return (
                    <tr
                      key={r.id}
                      className={shown?.id === r.id ? "selected" : ""}
                      onClick={() =>
                        (location.hash = `#/izvestaji/${reportId}/${r.id}`)
                      }
                    >
                      <td>{formatTime(r.started_at)}</td>
                      <td>
                        <ReportStatus status={r.status} />
                      </td>
                      <td className="small">
                        {reportId === "promet_12_meseci" && v?.ukupno
                          ? `${formatRsd(v.ukupno.promet)} RSD · ${v.ukupno.meseci} / ${v.meseci.length} meseci`
                          : r.error}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
