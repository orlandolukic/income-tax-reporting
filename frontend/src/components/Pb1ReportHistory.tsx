import { useEffect, useState } from "react";
import { CheckCheck, CopyPlus, History, Loader2, LockOpen, Send, Undo2 } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { getLogger } from "@/logger";

const logger = getLogger("pb1History");

/** One step of the company's PB-1 reports (GET .../pb1-report/history, newest first). */
type ReportEvent = { event: string; at: string; by: string };

const EVENTS: Record<string, { label: string; icon: typeof History; tone: string }> = {
  preliminary_done: { label: "Preliminary report marked as done", icon: CheckCheck, tone: "text-chart-3 bg-chart-3/10 border-chart-3/40" },
  gfi_done: { label: "GFI marked as done", icon: CheckCheck, tone: "text-chart-3 bg-chart-3/10 border-chart-3/40" },
  gfi_reopened: { label: "GFI reopened", icon: Undo2, tone: "text-chart-1 bg-chart-1/10 border-chart-1/40" },
  final_created: { label: "Final report created from preliminary", icon: CopyPlus, tone: "text-muted-foreground bg-muted border-border" },
  final_done: { label: "Final report marked as done", icon: CheckCheck, tone: "text-chart-3 bg-chart-3/10 border-chart-3/40" },
  final_unlocked: { label: "Final report unlocked", icon: LockOpen, tone: "text-chart-1 bg-chart-1/10 border-chart-1/40" },
  submitted: { label: "Report submitted", icon: Send, tone: "text-success bg-success/10 border-success/40" },
  submission_withdrawn: { label: "Submission withdrawn", icon: Undo2, tone: "text-destructive bg-destructive/10 border-destructive/40" },
};

const pad = (n: number) => String(n).padStart(2, "0");

/** Date and time as written in Serbia: 17.11.2026. 14:32 */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}. ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * "History" button: a side panel with the consecutive steps of the company's PB-1 reports
 * (done, created, unlocked, submitted, withdrawn), each with its date, time and user, newest first.
 */
export function Pb1ReportHistory({ year, row, version }: { year: number; row: number; version: unknown }) {
  const [open, setOpen] = useState(false);
  const [events, setEvents] = useState<ReportEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setError(null);
    fetch(`/api/reporting-years/${year}/companies/${row}/pb1-report/history`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((list: ReportEvent[]) => setEvents(list))
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        logger.error(`Failed to load the PB-1 report history (${year}, row ${row})`, err);
        setError("Istorija nije mogla da se učita.");
      });
    return () => controller.abort();
    // `version`: reload after a step, while the panel is open.
  }, [open, year, row, version]);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <History />
        History
      </Button>
      <SheetContent className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Report history</SheetTitle>
          <SheetDescription>Koraci preliminarnog i konačnog izveštaja, sa datumom, vremenom i korisnikom.</SheetDescription>
        </SheetHeader>
        <div className="overflow-y-auto px-4 pb-6">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {!error && events === null && (
            <p className="text-muted-foreground flex items-center gap-2 text-sm">
              <Loader2 className="size-4 animate-spin" />
              Učitavanje…
            </p>
          )}
          {events?.length === 0 && <p className="text-muted-foreground text-sm">Još nema nijednog koraka.</p>}
          {events && events.length > 0 && (
            // A vertical timeline: a line through the steps' icons, newest at the top.
            <ol className="relative grid gap-5 before:absolute before:inset-y-2 before:left-[0.9375rem] before:w-px before:bg-border">
              {events.map((e, i) => {
                const info = EVENTS[e.event] ?? { label: e.event, icon: History, tone: "text-muted-foreground bg-muted border-border" };
                const Icon = info.icon;
                return (
                  <li key={`${e.at}-${i}`} className="relative flex gap-3">
                    <span className={cn("z-10 flex size-8 shrink-0 items-center justify-center rounded-full border", info.tone)}>
                      <Icon className="size-4" />
                    </span>
                    <div className="grid gap-0.5 pt-1">
                      <span className={cn("text-sm font-medium", i === 0 && "text-foreground")}>{info.label}</span>
                      <span className="text-muted-foreground text-xs tabular-nums">
                        {formatDateTime(e.at)} · {e.by}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
