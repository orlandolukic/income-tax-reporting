import { createContext, useCallback, useContext, useMemo, useRef, type ReactNode } from "react";
import { useAuth } from "@/auth/AuthContext";
import { useCellAutosave, type PendingEdit, type SaveResult } from "@/hooks/use-cell-autosave";

export type AutosaveListener = {
  onSaved: (edit: PendingEdit, result: SaveResult) => void;
  onRejected: (edit: PendingEdit) => void;
};

type AutosaveContextValue = ReturnType<typeof useCellAutosave> & {
  /** Get save results for the table a page shows. Returns the unsubscribe function. */
  subscribe: (listener: AutosaveListener) => () => void;
};

const AutosaveContext = createContext<AutosaveContextValue | null>(null);

/**
 * One autosave queue for all logged-in pages (Home, Edit Company Data). Changes keep
 * being sent while the user moves between pages, and unsaved changes are kept in
 * localStorage across reloads, logout and session expiry.
 */
export function CellAutosaveProvider({ children }: { children: ReactNode }) {
  const { markSessionExpired } = useAuth();
  const listenersRef = useRef(new Set<AutosaveListener>());
  const autosave = useCellAutosave({
    onSaved: (edit, result) => listenersRef.current.forEach((l) => l.onSaved(edit, result)),
    onRejected: (edit) => listenersRef.current.forEach((l) => l.onRejected(edit)),
    onUnauthorized: markSessionExpired,
  });
  const subscribe = useCallback((listener: AutosaveListener) => {
    listenersRef.current.add(listener);
    return () => {
      listenersRef.current.delete(listener);
    };
  }, []);

  const { status, pendingCount, enqueue, retry, flush, pendingFor, pendingPb1 } = autosave;
  const value = useMemo(
    () => ({ status, pendingCount, enqueue, retry, flush, pendingFor, pendingPb1, subscribe }),
    [status, pendingCount, enqueue, retry, flush, pendingFor, pendingPb1, subscribe],
  );
  return <AutosaveContext.Provider value={value}>{children}</AutosaveContext.Provider>;
}

export function useAutosave() {
  const context = useContext(AutosaveContext);
  if (!context) throw new Error("useAutosave must be used inside CellAutosaveProvider");
  return context;
}
