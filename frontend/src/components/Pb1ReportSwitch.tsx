import { useState, type ReactNode } from "react";
import { CheckCheck, CopyPlus, Loader2, Lock, LockOpen, Send, Undo2 } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Pb1ReportHistory, formatDateTime } from "@/components/Pb1ReportHistory";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { Pb1Report } from "@/hooks/use-pb1";
import { cn } from "@/lib/utils";
import { getLogger } from "@/logger";

const logger = getLogger("pb1Report");

/*
 * The company's two PB-1 reports (user, 2026-11-17): Preliminary and Final, separate reports
 * with their own values and calculations. The preliminary report is marked as done (then locked,
 * still viewable, and Home "Preliminarni" becomes 1); only then the final report can be opened,
 * and it is created from the preliminary one by a button (a full copy in the database). The
 * final report is marked as done too (locked, Home "PB-1, PB-2" = 1) and can be unlocked again
 * for changes (Home "PB-1, PB-2" = 0). A final report marked as done is submitted ("Mark as
 * submitted": Home "PB-1, PB-2 Predat" = 1, with date and time; no unlocking while submitted)
 * and the submission can be withdrawn (Predat = 0). Every step is in the History panel.
 */

const OPTIONS: { key: Pb1Report; label: string }[] = [
  { key: "preliminary", label: "Preliminary" },
  { key: "final", label: "Final" },
];

type ReportAction =
  | "preliminary-done"
  | "gfi-done"
  | "gfi-reopen"
  | "final"
  | "final-done"
  | "final-unlock"
  | "submitted"
  | "submission-withdrawn";

/** The confirmation of each action that needs one (question and explanation in Serbian). */
const CONFIRM: Partial<Record<ReportAction, { title: string; text: string; label: string }>> = {
  "preliminary-done": {
    title: "Označiti preliminarni izveštaj kao gotov?",
    text: "Preliminarni izveštaj se zaključava: posle se može samo gledati. Na Home se kolona Preliminarni za ovu firmu postavlja na 1, a zatim se prelazi na konačni izveštaj.",
    label: "Mark as done",
  },
  "gfi-done": {
    title: "Označiti GFI kao gotov?",
    text: "Godišnji finansijski izveštaj je završen i konačni PB-1 izveštaj može da se napravi na njemu. Na Home se kolona GFI uradjen za ovu firmu postavlja na 1.",
    label: "Mark GFI as done",
  },
  "gfi-reopen": {
    title: "Ponovo otvoriti GFI?",
    text: "GFI više nije označen kao gotov i konačni izveštaj ne može da se napravi dok se GFI ponovo ne označi. Na Home se kolona GFI uradjen za ovu firmu vraća na 0.",
    label: "Reopen GFI",
  },
  "final-done": {
    title: "Označiti konačni izveštaj kao gotov?",
    text: "Konačni izveštaj se zaključava: može se gledati i štampati, ali ne i menjati, dok se ne otključa. Na Home se kolona PB-1, PB-2 za ovu firmu postavlja na 1.",
    label: "Mark as done",
  },
  "final-unlock": {
    title: "Otključati konačni izveštaj?",
    text: "Konačni izveštaj ponovo može da se menja. Na Home se kolona PB-1, PB-2 za ovu firmu vraća na 0, dok se izveštaj ponovo ne označi kao gotov.",
    label: "Unlock",
  },
  submitted: {
    title: "Označiti izveštaj kao predat?",
    text: "Upisuju se datum i vreme predaje. Na Home se kolona PB-1, PB-2 Predat za ovu firmu postavlja na 1. Dok je izveštaj predat, konačni izveštaj ne može da se otključa.",
    label: "Mark as submitted",
  },
  "submission-withdrawn": {
    title: "Povući predaju izveštaja?",
    text: "Pažnja: ovo je samo za ispravku posle predaje (npr. izmenjena prijava). Na Home se kolona PB-1, PB-2 Predat vraća na 0, a konačni izveštaj posle toga može da se otključa. Predaja i povlačenje ostaju u istoriji.",
    label: "Withdraw submission",
  },
};

/** Calls one of the report actions; returns an error message (Serbian) or null. */
async function post(year: number, row: number, action: ReportAction): Promise<string | null> {
  try {
    const res = await fetch(`/api/reporting-years/${year}/companies/${row}/pb1-report/${action}`, { method: "POST" });
    if (res.ok) return null;
    const body = await res.json().catch(() => null);
    return body?.detail ?? `Greška na serveru (HTTP ${res.status}).`;
  } catch (err) {
    logger.error(`PB-1 report action ${action} failed`, err);
    return "Nema veze sa serverom. Pokušajte ponovo.";
  }
}

/**
 * Styled switch between the two reports, "Mark as done" on the preliminary one, and on the
 * final one "Mark as done" / "Unlock".
 */
export function Pb1ReportSwitch({
  year,
  row,
  report,
  preliminaryDone,
  finalCreated,
  finalDone,
  submittedAt,
  flush,
  onSelect,
  onChanged,
  actions,
}: {
  year: number;
  row: number;
  report: Pb1Report;
  preliminaryDone: boolean;
  finalCreated: boolean;
  finalDone: boolean;
  submittedAt?: string; // the report is submitted (date and time)
  flush: () => Promise<boolean>;
  onSelect: (report: Pb1Report) => void;
  onChanged: () => void; // the report's state changed: reload it
  // Further actions in the same line, after the report steps (Save changes, Generate PDF report).
  actions?: ReactNode;
}) {
  const [confirming, setConfirming] = useState<ReportAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: ReportAction) => {
    setBusy(true);
    setError(null);
    // Locking a report: send its last changes first.
    const saved = action === "final-unlock" || (await flush());
    const failed = saved ? await post(year, row, action) : "Neke izmene još nisu snimljene. Pokušajte ponovo.";
    setBusy(false);
    setConfirming(null);
    if (failed) {
      setError(failed);
      return;
    }
    logger.info(`PB-1 report action ${action} (${year}, row ${row})`);
    if (action === "preliminary-done") onSelect("final");
    else onChanged();
  };
  const confirm = confirming ? CONFIRM[confirming] : undefined;
  const TINTS = {
    "chart-3": "border-chart-3/40 bg-chart-3/10 text-chart-3 hover:bg-chart-3/20 hover:text-chart-3",
    "chart-1": "border-chart-1/40 bg-chart-1/10 text-chart-1 hover:bg-chart-1/20 hover:text-chart-1",
    success: "border-success/40 bg-success/10 text-success hover:bg-success/20 hover:text-success",
    destructive: "border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive",
  };
  const tinted = (tint: keyof typeof TINTS) => TINTS[tint];
  const submitted = Boolean(submittedAt);

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <div
          role="radiogroup"
          aria-label="Report"
          className="bg-muted relative inline-grid grid-cols-2 rounded-full border p-1 shadow-inner"
        >
          {/* The sliding thumb under the chosen report. */}
          <span
            aria-hidden
            className={cn(
              "bg-background absolute inset-y-1 left-1 w-[calc(50%-0.25rem)] rounded-full border shadow-sm transition-transform duration-200",
              report === "final" && "translate-x-full",
            )}
          />
          {OPTIONS.map((option) => {
            const disabled = option.key === "final" && !preliminaryDone;
            const active = option.key === report;
            return (
              <button
                key={option.key}
                type="button"
                role="radio"
                aria-checked={active}
                disabled={disabled}
                title={disabled ? "Konačni izveštaj se otvara kada se preliminarni označi kao gotov." : undefined}
                onClick={() => !active && onSelect(option.key)}
                className={cn(
                  "relative z-10 inline-flex min-w-28 items-center justify-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-medium transition-colors",
                  active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                  disabled && "hover:text-muted-foreground cursor-not-allowed opacity-50",
                )}
              >
                {((option.key === "preliminary" && preliminaryDone) || (option.key === "final" && finalDone)) && (
                  <Lock className="size-3.5" />
                )}
                {option.label}
              </button>
            );
          })}
        </div>

        {((report === "preliminary" && !preliminaryDone) || (report === "final" && finalCreated && !finalDone)) && (
          <Button
            variant="outline"
            size="sm"
            className={tinted("chart-3")}
            disabled={busy}
            onClick={() => setConfirming(report === "preliminary" ? "preliminary-done" : "final-done")}
          >
            {busy ? <Loader2 className="animate-spin" /> : <CheckCheck />}
            Mark as done
          </Button>
        )}
        {report === "final" && finalDone && !submitted && (
          <>
            <Button
              variant="outline"
              size="sm"
              className={tinted("success")}
              disabled={busy}
              onClick={() => setConfirming("submitted")}
            >
              {busy ? <Loader2 className="animate-spin" /> : <Send />}
              Mark as submitted
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={tinted("chart-1")}
              disabled={busy}
              onClick={() => setConfirming("final-unlock")}
            >
              {busy ? <Loader2 className="animate-spin" /> : <LockOpen />}
              Unlock
            </Button>
          </>
        )}
        {submitted && submittedAt && (
          <>
            <Badge variant="outline" className="border-success/40 bg-success/10 text-success gap-1.5 py-1">
              <Send className="size-3.5" />
              Submitted · {formatDateTime(submittedAt)}
            </Badge>
            {report === "final" && (
              <Button
                variant="outline"
                size="sm"
                className={tinted("destructive")}
                disabled={busy}
                onClick={() => setConfirming("submission-withdrawn")}
              >
                {busy ? <Loader2 className="animate-spin" /> : <Undo2 />}
                Withdraw submission
              </Button>
            )}
          </>
        )}
        {report === "preliminary" && preliminaryDone && (
          <span className="text-muted-foreground text-sm">Preliminarni izveštaj je gotov i zaključan.</span>
        )}
        {report === "final" && finalDone && !submitted && (
          <span className="text-muted-foreground text-sm">Konačni izveštaj je gotov i zaključan.</span>
        )}
        {actions && (
          <>
            <Separator orientation="vertical" className="mx-12 data-[orientation=vertical]:h-6" />
            {actions}
          </>
        )}
        <div className="ms-auto">
          <Pb1ReportHistory year={year} row={row} version={`${preliminaryDone}${finalCreated}${finalDone}${submittedAt}`} />
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <AlertDialog open={confirming !== null} onOpenChange={(open) => !busy && !open && setConfirming(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirm?.title}</AlertDialogTitle>
            <AlertDialogDescription>{confirm?.text}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy}
              onClick={(e) => {
                e.preventDefault();
                if (confirming) void run(confirming);
              }}
            >
              {busy && <Loader2 className="animate-spin" />}
              {confirm?.label}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

/**
 * The final report before it exists: first GFI (the annual financial statements) is marked as
 * done (Home "GFI uradjen" = 1; can be reopened until the final report exists), then the final
 * report is created from the preliminary one on it (user, 2026-11-17).
 */
export function Pb1CreateFinal({
  year,
  row,
  gfiDone,
  onChanged,
}: {
  year: number;
  row: number;
  gfiDone: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<ReportAction | null>(null);
  const [confirming, setConfirming] = useState<ReportAction | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: ReportAction) => {
    setBusy(action);
    setError(null);
    const failed = await post(year, row, action);
    setBusy(null);
    setConfirming(null);
    if (failed) {
      setError(failed);
      return;
    }
    logger.info(`PB-1 report action ${action} (${year}, row ${row})`);
    onChanged();
  };
  const confirm = confirming ? CONFIRM[confirming] : undefined;

  return (
    <Card className="items-center gap-5 px-6 py-10 text-center">
      <CopyPlus className="text-muted-foreground size-8" />
      <div className="grid max-w-md gap-1">
        <h2 className="text-lg font-semibold">Final report</h2>
        <p className="text-muted-foreground text-sm">
          Konačni izveštaj još nije napravljen. Pravi se od preliminarnog kada je GFI gotov: svi iznosi se kopiraju, a
          posle se dva izveštaja menjaju i računaju posebno.
        </p>
      </div>
      {/* The two steps, in order. */}
      <ol className="grid w-full max-w-md gap-3 text-start">
        <li className="flex items-center justify-between gap-3 rounded-md border px-4 py-3">
          <div className="grid gap-0.5">
            <span className="text-sm font-medium">1. GFI</span>
            <span className={cn("text-xs", gfiDone ? "text-success" : "text-muted-foreground")}>
              {gfiDone ? "GFI je gotov." : "GFI još nije označen kao gotov."}
            </span>
          </div>
          {gfiDone ? (
            <Button variant="outline" size="sm" disabled={busy !== null} onClick={() => setConfirming("gfi-reopen")}>
              {busy === "gfi-reopen" ? <Loader2 className="animate-spin" /> : <Undo2 />}
              Reopen GFI
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              className="border-chart-3/40 bg-chart-3/10 text-chart-3 hover:bg-chart-3/20 hover:text-chart-3"
              disabled={busy !== null}
              onClick={() => setConfirming("gfi-done")}
            >
              {busy === "gfi-done" ? <Loader2 className="animate-spin" /> : <CheckCheck />}
              Mark GFI as done
            </Button>
          )}
        </li>
        <li className="flex items-center justify-between gap-3 rounded-md border px-4 py-3">
          <div className="grid gap-0.5">
            <span className="text-sm font-medium">2. Final report</span>
            <span className="text-muted-foreground text-xs">
              {gfiDone ? "Može da se napravi." : "Pravi se tek kada je GFI gotov."}
            </span>
          </div>
          <Button size="sm" disabled={!gfiDone || busy !== null} onClick={() => void run("final")}>
            {busy === "final" ? <Loader2 className="animate-spin" /> : <CopyPlus />}
            Create from preliminary
          </Button>
        </li>
      </ol>
      {error && (
        <Alert variant="destructive" className="max-w-md text-start">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <AlertDialog open={confirming !== null} onOpenChange={(open) => busy === null && !open && setConfirming(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirm?.title}</AlertDialogTitle>
            <AlertDialogDescription>{confirm?.text}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy !== null}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy !== null}
              onClick={(e) => {
                e.preventDefault();
                if (confirming) void run(confirming);
              }}
            >
              {busy !== null && <Loader2 className="animate-spin" />}
              {confirm?.label}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
