import { RunStatus, TaskStatus } from "../api";

const LABELS: Record<TaskStatus | RunStatus, string> = {
  pending: "Čeka",
  running: "U toku",
  done: "Završeno",
  failed: "Greška",
  not_implemented: "Nije implementirano",
  skipped: "Preskočeno",
  cancelled: "Zaustavljeno",
  stopped: "Prekinuto",
};

export function StatusBadge({ status }: { status: TaskStatus | RunStatus }) {
  return (
    <span className={`status-badge s-${status}`}>
      {status === "running" && <span className="spinner small" />}
      {LABELS[status]}
    </span>
  );
}

export function formatTime(seconds: number | null | undefined): string {
  if (!seconds) return "";
  return new Date(seconds * 1000).toLocaleString("sr-Latn", { dateStyle: "short", timeStyle: "medium" });
}

export function formatDuration(start: number | null, end: number | null): string {
  if (!start) return "";
  const s = ((end ?? Date.now() / 1000) - start);
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

/** Why a job can't be started right now, or "" if it can. */
export function runBlocker(ready: boolean, running: string | null, queued: string[], jobId: string): string {
  if (!ready) return "Pretraživač nije spreman: prijavite se i izaberite firmu.";
  if (running === jobId || queued.includes(jobId)) return "Posao je već pokrenut.";
  return "";
}
