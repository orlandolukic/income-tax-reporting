import { useEffect, useMemo, useState } from "react";
import { Loader2, Trash2 } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
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
import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { companies as companiesText } from "@/lib/plural";
import { matches } from "@/lib/search";
import { cn } from "@/lib/utils";
import { getLogger } from "@/logger";

const logger = getLogger("deleteCompanies");

type YearCompany = {
  row: number;
  name: string;
  pib?: string | null;
  referent?: string | null;
  office?: string | null;
  blocked?: string | null; // why it can't be deleted (it holds data), else empty
};

/**
 * "Obriši firme" on Edit Company Data (user, 2026-11-25): a popup with the year's companies, one
 * or more are checked and deleted permanently from that year, after a confirmation. Only
 * companies without data entered in the app (PB-1 amounts, report steps, edit history, a status
 * set) can be checked; the others show why. POST /api/reporting-years/{year}/companies/delete.
 */
export function DeleteCompaniesDialog({ year, onDeleted }: { year: number; onDeleted: () => void }) {
  const { markSessionExpired } = useAuth();
  const [open, setOpen] = useState(false);
  const [list, setList] = useState<YearCompany[] | null>(null);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [query, setQuery] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setList(null);
    setChosen(new Set());
    setQuery("");
    setError(null);
    fetch(`/api/reporting-years/${year}/companies/registry`, { signal: controller.signal })
      .then(async (res) => {
        if (res.status === 401) {
          markSessionExpired();
          throw new Error("Sesija je istekla.");
        }
        if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Greška na serveru (HTTP ${res.status}).`);
        return res.json();
      })
      .then((rows: YearCompany[]) => setList(rows))
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        logger.error("Loading the companies failed", err);
        setError(err.message);
      });
    return () => controller.abort();
  }, [open, year, markSessionExpired]);

  const shown = useMemo(
    () =>
      (list ?? []).map((c, index) => ({ ...c, position: index + 1 })).filter((c) =>
        query.trim() ? matches(query, [c.name, c.pib, c.referent, c.office]) : true,
      ),
    [list, query],
  );
  const toggle = (row: number) =>
    setChosen((prev) => {
      const next = new Set(prev);
      if (next.has(row)) next.delete(row);
      else next.add(row);
      return next;
    });
  const chosenNames = (list ?? []).filter((c) => chosen.has(c.row)).map((c) => c.name);

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/reporting-years/${year}/companies/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows: [...chosen] }),
      });
      if (res.status === 401) {
        markSessionExpired();
        return;
      }
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.detail ?? `Greška na serveru (HTTP ${res.status}).`);
      logger.info(`${body.deleted} companies deleted from ${year}`);
      setConfirming(false);
      setOpen(false);
      onDeleted();
    } catch (err) {
      logger.error("Deleting companies failed", err);
      setConfirming(false);
      setError(err instanceof Error ? err.message : "Firme nisu obrisane.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && setOpen(next)}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive">
          <Trash2 />
          Obriši firme…
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Brisanje firmi iz {year}.</DialogTitle>
          <DialogDescription>
            Izaberite jednu ili više firmi. Brišu se trajno iz ove godine. Firme sa unetim podacima ne mogu da se obrišu.
          </DialogDescription>
        </DialogHeader>
        <Input placeholder="Pretraga firmi" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Pretraga firmi" />
        <div className="max-h-[50svh] overflow-y-auto rounded-md border">
          {list === null && !error && (
            <p className="text-muted-foreground flex items-center gap-2 p-4 text-sm">
              <Loader2 className="size-4 animate-spin" /> Učitavanje…
            </p>
          )}
          {list !== null && shown.length === 0 && (
            <p className="text-muted-foreground p-4 text-sm">Nijedna firma ne odgovara pretrazi.</p>
          )}
          {shown.map((c) => {
            const blocked = Boolean(c.blocked);
            const details = [c.pib && `PIB ${c.pib}`, c.referent, c.office].filter(Boolean).join(" · ");
            return (
              <label
                key={c.row}
                className={cn(
                  "flex items-start gap-3 border-b px-3 py-2 last:border-b-0",
                  blocked ? "cursor-not-allowed opacity-60" : "hover:bg-accent cursor-pointer",
                )}
              >
                <Checkbox
                  className="mt-0.5"
                  checked={chosen.has(c.row)}
                  disabled={blocked}
                  onCheckedChange={() => toggle(c.row)}
                />
                <span className="text-muted-foreground w-8 shrink-0 text-end text-xs tabular-nums">{c.position}</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium break-words">{c.name}</span>
                  {details && <span className="text-muted-foreground block text-xs break-words">{details}</span>}
                  {blocked && <span className="text-destructive block text-xs">Ne može da se obriše: {c.blocked}.</span>}
                </span>
              </label>
            );
          })}
        </div>
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <DialogFooter className="items-center">
          <span className="text-muted-foreground me-auto text-sm">Izabrano: {companiesText(chosen.size)}</span>
          <Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>
            Otkaži
          </Button>
          <Button variant="destructive" disabled={busy || chosen.size === 0} onClick={() => setConfirming(true)}>
            <Trash2 />
            Obriši
          </Button>
        </DialogFooter>
      </DialogContent>

      <AlertDialog open={confirming} onOpenChange={(next) => !busy && setConfirming(next)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Trajno obrisati {companiesText(chosen.size)}?</AlertDialogTitle>
            <AlertDialogDescription>
              Iz {year}. se trajno brišu: {chosenNames.slice(0, 8).join(", ")}
              {chosenNames.length > 8 ? ` i još ${chosenNames.length - 8}` : ""}. Ovo ne može da se vrati.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Otkaži</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy}
              className={buttonVariants({ variant: "destructive" })}
              onClick={(e) => {
                e.preventDefault();
                void remove();
              }}
            >
              {busy && <Loader2 className="animate-spin" />}
              Obriši trajno
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Dialog>
  );
}
