import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { SaveState } from "@/hooks/use-cell-autosave";

type Props = { status: SaveState; pendingCount: number; onRetry: () => void };

/** "1 nesačuvana izmena je zadržana", "3 nesačuvane izmene su zadržane", "5 nesačuvanih izmena je zadržano". */
function unsavedKept(n: number): string {
  const tens = n % 100;
  if (n % 10 === 1 && tens !== 11) return `${n} nesačuvana izmena je zadržana`;
  if (n % 10 >= 2 && n % 10 <= 4 && (tens < 12 || tens > 14)) return `${n} nesačuvane izmene su zadržane`;
  return `${n} nesačuvanih izmena je zadržano`;
}

/** Autosave indicator: Saving… / All changes saved / error with retry. */
export function SaveStatus({ status, pendingCount, onRetry }: Props) {
  return (
    <div role="status" aria-live="polite" className="flex min-h-9 items-center gap-2 text-sm">
      {status.state === "saving" && (
        <span className="text-muted-foreground flex items-center gap-1.5">
          <Loader2 className="size-4 animate-spin" />
          Čuvanje…
        </span>
      )}
      {status.state === "saved" && (
        <span
          className="text-muted-foreground flex items-center gap-1.5"
          title={`Sačuvano u ${status.savedAt.toLocaleTimeString()}`}
        >
          <CheckCircle2 className="size-4" />
          Sve izmene su sačuvane
        </span>
      )}
      {status.state === "error" && (
        <>
          <span className="text-destructive flex items-center gap-1.5">
            <AlertCircle className="size-4" />
            {status.message}
            {pendingCount > 0 &&
              ` ${unsavedKept(pendingCount)}${status.retrying ? ", novi pokušaj…" : "."}`}
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
