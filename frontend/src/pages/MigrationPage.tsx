import { companies } from "@/lib/plural";
import { useCallback, useEffect, useRef, useState } from "react";
import { CalendarPlus, Loader2, Trash2, Users } from "lucide-react";
import { useNavigate } from "react-router";
import { useAuth } from "@/auth/AuthContext";
import { CompanySelectDialog } from "@/components/CompanySelectDialog";
import { Main } from "@/components/layout/Main";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useReportingYear } from "@/context/ReportingYearProvider";
import { getLogger } from "@/logger";

const logger = getLogger("migration");

type YearInfo = {
  year: number;
  origin: "workbook" | "constructed";
  based_on_year?: number | null;
  source: string;
  companies: number;
  pb1?: string | null; // the year's PB-1 form (workbook, or constructed with the year)
  deletable?: boolean; // the latest year, constructed here: it can be deleted
};
type MigrationStatus = { years: YearInfo[]; next_year: number | null; source_year: number | null };
type SelectionResult = { year: number; companies: number; added: number; restored: number; removed: number };
type DeleteResult = { year: number; companies: number; pb1_values: number };

// The dialog is open for: building the next year, or changing a constructed year's companies.
type DialogState = { mode: "construct" | "edit"; year: number } | null;

async function send(url: string, method: "POST" | "PUT", companyIds: number[], onUnauthorized: () => void) {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ company_ids: companyIds }),
  });
  if (res.status === 401) {
    onUnauthorized();
    throw new Error("Sesija je istekla.");
  }
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Greška na serveru (HTTP ${res.status}).`);
  return (await res.json()) as SelectionResult;
}

/**
 * Migracija: builds the next reporting year from the latest one (company details carried over,
 * status columns 0) with the companies chosen in a dialog; the year then appears in the
 * Reporting year selector. The companies of a constructed year can be changed later.
 */
export default function MigrationPage() {
  const { markSessionExpired } = useAuth();
  const { reloadYears, setSelectedYear } = useReportingYear();
  const navigate = useNavigate();
  const [status, setStatus] = useState<MigrationStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [message, setMessage] = useState<string | null>(null);
  // The year whose deletion is being confirmed.
  const [toDelete, setToDelete] = useState<YearInfo | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // Not a dependency of `load` (it is a new function on every render).
  const expiredRef = useRef(markSessionExpired);
  expiredRef.current = markSessionExpired;

  const load = useCallback(() => {
    setError(null);
    fetch("/api/migration")
      .then(async (res) => {
        if (res.status === 401) {
          expiredRef.current();
          throw new Error("Sesija je istekla.");
        }
        if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Greška na serveru (HTTP ${res.status}).`);
        return res.json();
      })
      .then((data: MigrationStatus) => setStatus(data))
      .catch((err: Error) => {
        logger.error("Failed to load the migration status", err);
        setError(err.message);
      });
  }, []);

  useEffect(load, [load]);

  const onConfirm = async (companyIds: number[]) => {
    if (!dialog) return;
    const result =
      dialog.mode === "construct"
        ? await send(`/api/migration/years/${dialog.year}`, "POST", companyIds, markSessionExpired)
        : await send(`/api/migration/years/${dialog.year}/companies`, "PUT", companyIds, markSessionExpired);
    logger.info(`Migracija ${dialog.mode} ${dialog.year}`, result);
    setMessage(
      dialog.mode === "construct"
        ? `Godina ${result.year} je konstruisana: ${companies(result.companies)}.`
        : `Firme za ${result.year} su izmenjene: ${companies(result.companies)} (dodato ${result.added}, vraćeno ${result.restored}, sklonjeno ${result.removed}).`,
    );
    reloadYears();
    load();
  };

  const deleteYear = async () => {
    if (!toDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const res = await fetch(`/api/migration/years/${toDelete.year}`, { method: "DELETE" });
      if (res.status === 401) {
        markSessionExpired();
        throw new Error("Sesija je istekla.");
      }
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Greška na serveru (HTTP ${res.status}).`);
      const result = (await res.json()) as DeleteResult;
      logger.warning(`Year ${result.year} deleted`, result);
      setMessage(`Godina ${result.year} je obrisana (${companies(result.companies)}, ${result.pb1_values} PB-1 vrednosti).`);
      setToDelete(null);
      reloadYears();
      load();
    } catch (err) {
      logger.error("Failed to delete the year", err);
      setDeleteError((err as Error).message);
    } finally {
      setDeleting(false);
    }
  };

  const openYear = (year: number) => {
    setSelectedYear(year);
    navigate("/");
  };

  const next = status?.next_year;
  return (
    <Main>
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Migracija</h1>
        <p className="text-muted-foreground">
          Sledeća godina se pravi iz poslednje: prenose se naziv, PIB, referent i kancelarija firme, a statusne kolone
          počinju od 0. Pravi se i PB-1 obrazac (sva tri taba, kao u prethodnoj godini, sa nulama).
        </p>
      </div>

      <div className="mt-6 grid gap-4">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {!status && !error && (
          <div className="text-muted-foreground flex items-center gap-2 text-sm">
            <Loader2 className="size-4 animate-spin" />
            Učitavanje…
          </div>
        )}
        {message && (
          <Alert>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}

        {status && next && (
          <Card>
            <CardHeader>
              <CardTitle>Sledeća godina: {next}</CardTitle>
              <CardDescription>
                Pravi se iz {status.source_year}. Izaberite firme koje će {next} prikazivati.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button onClick={() => setDialog({ mode: "construct", year: next })}>
                <CalendarPlus />
                Napravi {next}…
              </Button>
            </CardContent>
          </Card>
        )}

        {status && (
          <Card>
            <CardHeader>
              <CardTitle>Godine</CardTitle>
              <CardDescription>Uvezene godine i godine napravljene ovde.</CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="divide-y rounded-md border">
                {status.years.map((y) => (
                  <li key={y.year} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold tabular-nums">{y.year}</span>
                      <Badge variant={y.origin === "constructed" ? "secondary" : "outline"}>
                        {y.origin === "constructed" ? `napravljena iz ${y.based_on_year}` : "uvezena"}
                      </Badge>
                      <span className="text-muted-foreground text-sm">{companies(y.companies)}</span>
                      <span className="text-muted-foreground text-sm">· {y.pb1 ? "PB-1 obrazac" : "bez PB-1 obrasca"}</span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {y.origin === "constructed" && (
                        <Button variant="outline" size="sm" onClick={() => setDialog({ mode: "edit", year: y.year })}>
                          <Users />
                          Izmeni firme…
                        </Button>
                      )}
                      <Button variant="outline" size="sm" onClick={() => openYear(y.year)}>
                        Otvori
                      </Button>
                      {y.deletable && (
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => {
                            setDeleteError(null);
                            setToDelete(y);
                          }}
                        >
                          <Trash2 />
                          Obriši…
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
      </div>

      <AlertDialog open={toDelete !== null} onOpenChange={(open) => !open && !deleting && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Da li stvarno želite da obrišete {toDelete?.year}?</AlertDialogTitle>
            <AlertDialogDescription>
              Godina {toDelete?.year} (konstruisana iz {toDelete?.based_on_year}) briše se u potpunosti: {toDelete?.companies}{" "}
              firmi sa svim vrednostima, njen PB-1 obrazac sa svim unetim iznosima i komentarima i istorija izmena te
              godine. Ostale godine ostaju nepromenjene. Brisanje se ne može vratiti.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError && (
            <Alert variant="destructive">
              <AlertDescription>{deleteError}</AlertDescription>
            </Alert>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Otkaži</AlertDialogCancel>
            <Button variant="destructive" onClick={deleteYear} disabled={deleting}>
              {deleting ? <Loader2 className="animate-spin" /> : <Trash2 />}
              Obriši {toDelete?.year}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {dialog && (
        <CompanySelectDialog
          open
          year={dialog.year}
          title={dialog.mode === "construct" ? `Firme za ${dialog.year}` : `Firme u ${dialog.year}`}
          description={
            dialog.mode === "construct"
              ? `Štiklirane firme se prenose iz ${status?.source_year} u ${dialog.year} (naziv, PIB, referent, kancelarija; statusi 0).`
              : `Štiklirane firme se prikazuju u ${dialog.year}. Sklonjena firma zadržava svoje podatke ako se vrati.`
          }
          confirmLabel={dialog.mode === "construct" ? `Napravi ${dialog.year}` : "Sačuvaj izbor"}
          onOpenChange={(open) => !open && setDialog(null)}
          onConfirm={onConfirm}
          onUnauthorized={markSessionExpired}
        />
      )}
    </Main>
  );
}
