import { useCallback, useEffect, useRef, useState } from "react";
import type { PendingValue, TableStats } from "@/hooks/use-company-table";
import { getLogger } from "@/logger";

const logger = getLogger("autosave");

// Unsaved changes survive reloads, logout and session expiry in this browser,
// and are sent as soon as the user is logged in again.
const STORAGE_KEY = "pending-cell-edits";
const RETRY_DELAY_MS = 10_000;

/** A PB-1 form field: amount of one company, or a template field shared by every company. */
export type Pb1Target = { company: number; tab: string; shared: boolean };
/** A GFI cell edit, or (with `pb1`) a PB-1 field edit; `row` is the Excel row. */
export type PendingEdit = PendingValue & { year: number; pb1?: Pb1Target };
export type SaveResult = {
  row: number;
  column: string;
  value: number | string | null;
  edited: boolean;
  /** Recomputed formula columns of the same row (GFI ZA RAD, PB-1,PB-2 za rad). */
  formulas?: Record<string, number | string | null>;
  /** Recomputed table statistics (totals under the Home table). */
  stats?: TableStats;
  /** PB-1: the tab's computed cells (workbook formulas) after the change. */
  computed?: { row: number; column: string; value: number | null }[];
  /** PB-1: tax loss after the change (the Poreski bilans tax base is negative). */
  loss?: { base: number } | null;
};
export type SaveState =
  | { state: "idle" }
  | { state: "saving" }
  | { state: "saved"; savedAt: Date }
  | { state: "error"; message: string; retrying: boolean };

type Callbacks = {
  onSaved: (edit: PendingEdit, result: SaveResult) => void;
  /** The server refused the change permanently (read-only or invalid); it was dropped. */
  onRejected: (edit: PendingEdit) => void;
  onUnauthorized: () => void;
};

const keyOf = (e: PendingEdit) =>
  e.pb1
    ? `${e.year}:pb1:${e.pb1.tab}:${e.pb1.shared ? "all" : e.pb1.company}:${e.column}${e.row}`
    : `${e.year}:${e.column}${e.row}`;

const urlOf = (e: PendingEdit) =>
  e.pb1
    ? `/api/reporting-years/${e.year}/companies/${e.pb1.company}/pb1/${e.pb1.tab}/cells/${e.column}/${e.row}`
    : `/api/reporting-years/${e.year}/cells/${e.column}/${e.row}`;

function loadQueue(): PendingEdit[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function storeQueue(queue: PendingEdit[]) {
  try {
    if (queue.length) localStorage.setItem(STORAGE_KEY, JSON.stringify(queue));
    else localStorage.removeItem(STORAGE_KEY);
  } catch (err) {
    logger.warning("Unable to persist unsaved changes", err);
  }
}

/**
 * Sends cell edits to the server one at a time, in order, with retry.
 * Use it through CellAutosaveProvider: one queue for the whole app, so pages never
 * send or store the queue concurrently.
 */
export function useCellAutosave(callbacks: Callbacks) {
  const queueRef = useRef<PendingEdit[]>(loadQueue());
  const busyRef = useRef(false);
  const retryTimerRef = useRef<number | undefined>(undefined);
  const callbacksRef = useRef(callbacks);
  callbacksRef.current = callbacks;
  const [pendingCount, setPendingCount] = useState(queueRef.current.length);
  const [status, setStatus] = useState<SaveState>({ state: "idle" });

  const updateQueue = (queue: PendingEdit[]) => {
    queueRef.current = queue;
    storeQueue(queue);
    setPendingCount(queue.length);
  };

  const process = useCallback(async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    window.clearTimeout(retryTimerRef.current);
    const scheduleRetry = (message: string) => {
      setStatus({ state: "error", message, retrying: true });
      retryTimerRef.current = window.setTimeout(() => void process(), RETRY_DELAY_MS);
    };

    try {
      while (queueRef.current.length > 0) {
        // The head item is never replaced while it is being sent (see enqueue).
        const edit = queueRef.current[0];
        setStatus({ state: "saving" });
        let res: Response;
        try {
          res = await fetch(urlOf(edit), {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ value: edit.value }),
          });
        } catch (err) {
          logger.error("Save failed: network error", err);
          scheduleRetry("Can't reach the server.");
          return;
        }

        if (res.status === 401) {
          logger.warning("Save paused: session expired; changes kept locally");
          setStatus({ state: "error", message: "Session expired.", retrying: false });
          callbacksRef.current.onUnauthorized();
          return;
        }
        if (res.status === 404 || res.status === 409 || res.status === 422) {
          logger.error(`Save rejected (HTTP ${res.status}) for ${keyOf(edit)}`);
          updateQueue(queueRef.current.slice(1));
          callbacksRef.current.onRejected(edit);
          setStatus({ state: "error", message: "A change was rejected and has been reverted.", retrying: false });
          continue;
        }
        if (!res.ok) {
          logger.error(`Save failed: HTTP ${res.status}`);
          scheduleRetry("Saving failed.");
          return;
        }

        const result: SaveResult = await res.json();
        const rest = queueRef.current.slice(1);
        updateQueue(rest);
        // Skip the result if a newer value for the same cell is already queued.
        if (!rest.some((e) => keyOf(e) === keyOf(edit))) callbacksRef.current.onSaved(edit, result);
        logger.debug(`Saved ${keyOf(edit)}`);
      }
      setStatus((s) => (s.state === "error" ? s : { state: "saved", savedAt: new Date() }));
    } finally {
      busyRef.current = false;
    }
  }, []);

  const enqueue = useCallback(
    (edit: PendingEdit) => {
      // Replace a queued value for the same cell, except the one currently being sent.
      const head = busyRef.current ? queueRef.current.slice(0, 1) : [];
      const rest = queueRef.current.slice(head.length).filter((e) => keyOf(e) !== keyOf(edit));
      updateQueue([...head, ...rest, edit]);
      void process();
    },
    [process],
  );

  const retry = useCallback(() => void process(), [process]);

  /**
   * Sends every unsaved change now and waits until the queue is empty. Resolves true when all
   * changes are saved, false when some are still unsaved (offline, server error, session expired).
   */
  const flush = useCallback(async (): Promise<boolean> => {
    // Let an editor that is closing (blur) put its change in the queue first.
    await new Promise((resolve) => setTimeout(resolve, 0));
    for (let attempt = 0; attempt < 600; attempt++) {
      if (queueRef.current.length === 0 && !busyRef.current) return true;
      if (!busyRef.current) {
        await process();
        return queueRef.current.length === 0;
      }
      await new Promise((resolve) => setTimeout(resolve, 50)); // a save is in progress
    }
    return queueRef.current.length === 0;
  }, [process]);

  // GFI cell edits of a year (PB-1 edits have their own list below).
  const pendingFor = useCallback(
    (year: number) => queueRef.current.filter((e) => e.year === year && !e.pb1),
    [],
  );

  // PB-1 edits shown on one company's form tab: its amounts and the shared template fields.
  const pendingPb1 = useCallback(
    (year: number, company: number, tab: string) =>
      queueRef.current.filter(
        (e) => e.year === year && e.pb1?.tab === tab && (e.pb1.shared || e.pb1.company === company),
      ),
    [],
  );

  // Send changes left over from a previous page load or session.
  useEffect(() => {
    if (queueRef.current.length > 0) {
      logger.info(`Resuming ${queueRef.current.length} unsaved change(s)`);
      void process();
    }
    return () => window.clearTimeout(retryTimerRef.current);
  }, [process]);

  return { status, pendingCount, enqueue, retry, flush, pendingFor, pendingPb1 };
}
