import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { getLogger } from "@/logger";

const logger = getLogger("companySelect");

export type RegistryCompany = {
  company_id: number;
  name: string;
  pib?: string | null;
  referent?: string | null;
  office?: string | null;
  years: number[];
  selected: boolean;
};

/**
 * The company registry with a checkbox per company: which companies a year shows. Loads the
 * registry for `year` (the companies of that year, or the proposal for a year not built yet)
 * and hands the selected ids to `onConfirm`.
 */
export function CompanySelectDialog({
  open,
  year,
  title,
  description,
  confirmLabel,
  onOpenChange,
  onConfirm,
  onUnauthorized,
}: {
  open: boolean;
  year: number;
  title: string;
  description: string;
  confirmLabel: string;
  onOpenChange: (open: boolean) => void;
  onConfirm: (companyIds: number[]) => Promise<void>;
  onUnauthorized: () => void;
}) {
  const [companies, setCompanies] = useState<RegistryCompany[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setCompanies(null);
    setError(null);
    setQuery("");
    fetch(`/api/migration/years/${year}/companies`, { signal: controller.signal })
      .then(async (res) => {
        if (res.status === 401) {
          onUnauthorized();
          throw new Error("Sesija je istekla.");
        }
        if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Greška na serveru (HTTP ${res.status}).`);
        return res.json();
      })
      .then((list: RegistryCompany[]) => {
        setCompanies(list);
        setSelected(new Set(list.filter((c) => c.selected).map((c) => c.company_id)));
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        logger.error("Failed to load the company registry", err);
        setError(err.message);
      });
    return () => controller.abort();
    // onUnauthorized is not a dependency: it must not reload the list.
  }, [open, year]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!companies) return [];
    if (!q) return companies;
    return companies.filter((c) =>
      [c.name, c.pib, c.referent, c.office].some((v) => v && v.toLowerCase().includes(q)),
    );
  }, [companies, query]);

  const toggle = (id: number, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const setAll = (on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      for (const c of shown) {
        if (on) next.add(c.company_id);
        else next.delete(c.company_id);
      }
      return next;
    });

  const confirm = async () => {
    setSaving(true);
    setError(null);
    try {
      await onConfirm([...selected]);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Greška.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search: name, PIB, referent, office"
            className="min-w-48 flex-1"
            aria-label="Search companies"
          />
          <Button variant="outline" size="sm" onClick={() => setAll(true)} disabled={!companies}>
            Select all
          </Button>
          <Button variant="outline" size="sm" onClick={() => setAll(false)} disabled={!companies}>
            Clear all
          </Button>
        </div>
        <p className="text-muted-foreground text-sm">
          {companies ? `Selected ${selected.size} of ${companies.length}` : "Učitavanje registra…"}
          {companies && query.trim() !== "" && ` · shown ${shown.length}`}
        </p>

        <div className="max-h-[50vh] overflow-auto rounded-md border">
          {!companies && !error && (
            <div className="text-muted-foreground flex items-center gap-2 p-4 text-sm">
              <Loader2 className="size-4 animate-spin" />
              Učitavanje…
            </div>
          )}
          <ul>
            {shown.map((c) => {
              const id = `company-${c.company_id}`;
              const details = [c.pib && `PIB ${c.pib}`, c.referent, c.office, c.years.length > 0 && c.years.join(", ")]
                .filter(Boolean)
                .join(" · ");
              return (
                <li key={c.company_id} className="flex items-start gap-3 border-b px-3 py-2 last:border-b-0">
                  <Checkbox
                    id={id}
                    checked={selected.has(c.company_id)}
                    onCheckedChange={(on) => toggle(c.company_id, on === true)}
                    className="mt-0.5"
                  />
                  <label htmlFor={id} className="min-w-0 flex-1 cursor-pointer">
                    <span className="block text-sm font-medium break-words">{c.name}</span>
                    {details && <span className="text-muted-foreground block text-xs break-words">{details}</span>}
                  </label>
                </li>
              );
            })}
          </ul>
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void confirm()} disabled={saving || !companies || selected.size === 0}>
            {saving && <Loader2 className="animate-spin" />}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
