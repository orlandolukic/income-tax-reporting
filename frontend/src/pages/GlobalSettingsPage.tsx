import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Save } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { Main } from "@/components/layout/Main";
import { Pb1Comments } from "@/components/Pb1Table";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Pb1Commit, Pb1Row } from "@/hooks/use-pb1";
import { getLogger } from "@/logger";

const logger = getLogger("globalSettings");

/** The PB-1 comments: rows as on the PB-1 page (line number, description, comment). */
type CommentsData = { sheet: string; comment_column: string; rows: Pb1Row[] };
type Value = number | string | null;
type Status = { kind: "saving" } | { kind: "saved" } | { kind: "error"; text: string } | null;

const URL = "/api/settings/pb1-comments";

/** The server refused the value (invalid, unknown row): it is dropped, not retried. */
class Refused extends Error {}

/** The row list with one comment's value replaced. */
function withValue(data: CommentsData, row: number, value: Value): CommentsData {
  const column = data.comment_column;
  return {
    ...data,
    rows: data.rows.map((r) => (r.row === row ? { ...r, cells: { ...r.cells, [column]: { ...r.cells[column], value } } } : r)),
  };
}

/**
 * Global Settings: settings for the whole system, the same for every year and company. For now
 * the PB-1 comments (Poreski bilans): edited here only, shown read-only on every company's PB-1
 * page. Each change is saved at once; one that could not be saved (no connection, server error)
 * stays shown and is sent again by "Save changes", which also waits for the saves under way.
 * A value the server refuses (e.g. text for a rate) goes back to the saved one.
 */
export default function GlobalSettingsPage() {
  const { markSessionExpired } = useAuth();
  const [data, setData] = useState<CommentsData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>(null);
  const [flushing, setFlushing] = useState(false);
  // Unsaved changes (row -> value) and the value saved on the server before them.
  const pending = useRef(new Map<number, Value>());
  const saved = useRef(new Map<number, Value>());
  const inFlight = useRef(new Set<Promise<void>>());
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(URL);
        if (res.status === 401) {
          markSessionExpired();
          return;
        }
        if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Greška na serveru (HTTP ${res.status}).`);
        const body = (await res.json()) as CommentsData;
        if (!cancelled) setData(body);
      } catch (err) {
        logger.error("Loading the PB-1 comments failed", err);
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "Komentari nisu mogli da se učitaju.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [markSessionExpired]);

  /** Sends one row's pending value; resolves when done (failures are kept as pending). */
  const send = useCallback(
    (row: number): Promise<void> => {
      const value = pending.current.get(row);
      if (value === undefined) return Promise.resolve();
      const task = (async () => {
        try {
          const res = await fetch(`${URL}/${row}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ value }),
          });
          if (res.status === 401) {
            markSessionExpired();
            throw new Error("Sesija je istekla; izmena nije sačuvana.");
          }
          const detail = async () => (await res.json().catch(() => null))?.detail;
          if (res.status >= 400 && res.status < 500) throw new Refused((await detail()) ?? "Vrednost nije prihvaćena.");
          if (!res.ok) throw new Error((await detail()) ?? `Greška na serveru (HTTP ${res.status}).`);
          const result = (await res.json()) as { value: Value };
          if (pending.current.get(row) === value) {
            pending.current.delete(row);
            saved.current.set(row, result.value);
            setData((d) => (d ? withValue(d, row, result.value) : d));
          }
          logger.info(`PB-1 comment of row ${row} saved`);
        } catch (err) {
          logger.error(`Saving the PB-1 comment of row ${row} failed`, err);
          const text = err instanceof Error ? err.message : "Izmena nije sačuvana.";
          if (err instanceof Refused && pending.current.get(row) === value) {
            pending.current.delete(row);
            const back = saved.current.get(row) ?? null;
            setData((d) => (d ? withValue(d, row, back) : d));
          }
          setStatus({
            kind: "error",
            text: err instanceof Refused ? text : `${text} Kliknite „Save changes” da pokušate ponovo.`,
          });
        } finally {
          setPendingCount(pending.current.size);
        }
      })();
      inFlight.current.add(task);
      task.finally(() => inFlight.current.delete(task));
      return task;
    },
    [markSessionExpired],
  );

  const onCommit: Pb1Commit = useCallback(
    (row, column, entered) => {
      if (!data) return;
      // Only spaces or "-" is no comment: it is removed, never stored.
      const value = typeof entered === "string" && ["", "-"].includes(entered.trim()) ? null : entered;
      if (!saved.current.has(row)) {
        const shown = data.rows.find((r) => r.row === row)?.cells[column]?.value;
        saved.current.set(row, typeof shown === "number" || typeof shown === "string" ? shown : null);
      }
      pending.current.set(row, value);
      setPendingCount(pending.current.size);
      setData((d) => (d ? withValue(d, row, value) : d));
      setStatus({ kind: "saving" });
      void send(row).then(() => {
        if (pending.current.size === 0 && inFlight.current.size === 0) setStatus((s) => (s?.kind === "error" ? s : { kind: "saved" }));
      });
    },
    [data, send],
  );

  /** Waits for the saves under way, then sends every change not saved yet. */
  const saveAll = async () => {
    setFlushing(true);
    setStatus({ kind: "saving" });
    try {
      await Promise.all([...inFlight.current]);
      await Promise.all([...pending.current.keys()].map((row) => send(row)));
      if (pending.current.size === 0) setStatus({ kind: "saved" });
    } finally {
      setFlushing(false);
    }
  };

  return (
    <Main>
      <div className="mb-4">
        <h1 className="text-2xl font-bold tracking-tight">Global Settings</h1>
        <p className="text-muted-foreground">Podešavanja koja važe za ceo sistem: za sve firme i sve godine.</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>PB-1 comments</CardTitle>
          <CardDescription>
            Komentari uz redove Poreskog bilansa (pravila za sekcije obrasca). Isti su za sve firme i sve godine i menjaju
            se samo ovde; stope su brojevi i ulaze u formule. Kliknite na komentar da ga izmenite.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {status?.kind === "error" && (
            <Alert variant="destructive">
              <AlertDescription>{status.text}</AlertDescription>
            </Alert>
          )}
          {loadError ? (
            <Alert variant="destructive">
              <AlertDescription>{loadError}</AlertDescription>
            </Alert>
          ) : !data ? (
            <p className="text-muted-foreground flex items-center gap-2 text-sm">
              <Loader2 className="size-4 animate-spin" /> Učitavanje…
            </p>
          ) : (
            <>
              {/* Right above the comments, next to what it saves. */}
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  variant="outline"
                  size="sm"
                  className="border-success/40 bg-success/10 text-success hover:bg-success/20 hover:text-success"
                  disabled={flushing}
                  onClick={saveAll}
                >
                  {flushing ? <Loader2 className="animate-spin" /> : <Save />}
                  Save changes
                </Button>
                <span className="text-muted-foreground text-sm" aria-live="polite">
                  {status?.kind === "saving"
                    ? "Čuvanje…"
                    : pendingCount > 0
                      ? `Nesačuvanih izmena: ${pendingCount}`
                      : status?.kind === "saved"
                        ? "Sve izmene su sačuvane."
                        : ""}
                </span>
              </div>
              <Pb1Comments data={data} onCommit={onCommit} className="max-h-[calc(100svh-22rem)]" />
            </>
          )}
        </CardContent>
      </Card>
    </Main>
  );
}
