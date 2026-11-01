import { useCallback, useEffect, useRef, useState } from "react";
import type { PendingValue } from "@/hooks/use-company-table";
import { getLogger } from "@/logger";

const logger = getLogger("autosave");

// Unsaved changes survive reloads, logout and session expiry in this browser,
// and are sent as soon as the user is logged in again.
const STORAGE_KEY = "pending-cell-edits";
const RETRY_DELAY_MS = 10_000;

export type PendingEdit = PendingValue & { year: number };
export type SaveResult = { row: number; column: string; value: number | null; edited: boolean };
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

const keyOf = (e: PendingEdit) => `${e.year}:${e.column}${e.row}`;

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

/** Sends cell edits to the server one at a time, in order, with retry. */
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
          res = await fetch(`/api/reporting-years/${edit.year}/cells/${edit.column}/${edit.row}`, {
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

  const pendingFor = useCallback(
    (year: number) => queueRef.current.filter((e) => e.year === year),
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

  return { status, pendingCount, enqueue, retry, pendingFor };
}
