import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { SaveState } from "@/hooks/use-cell-autosave";

type Props = { status: SaveState; pendingCount: number; onRetry: () => void };

/** Autosave indicator: Saving… / All changes saved / error with retry. */
export function SaveStatus({ status, pendingCount, onRetry }: Props) {
  return (
    <div role="status" aria-live="polite" className="flex min-h-9 items-center gap-2 text-sm">
      {status.state === "saving" && (
        <span className="text-muted-foreground flex items-center gap-1.5">
          <Loader2 className="size-4 animate-spin" />
          Saving…
        </span>
      )}
      {status.state === "saved" && (
        <span
          className="text-muted-foreground flex items-center gap-1.5"
          title={`Saved at ${status.savedAt.toLocaleTimeString()}`}
        >
          <CheckCircle2 className="size-4" />
          All changes saved
        </span>
      )}
      {status.state === "error" && (
        <>
          <span className="text-destructive flex items-center gap-1.5">
            <AlertCircle className="size-4" />
            {status.message}
            {pendingCount > 0 &&
              ` ${pendingCount} unsaved change${pendingCount === 1 ? "" : "s"} kept${status.retrying ? ", retrying…" : "."}`}
          </span>
          {pendingCount > 0 && (
            <Button variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          )}
        </>
      )}
    </div>
  );
}
