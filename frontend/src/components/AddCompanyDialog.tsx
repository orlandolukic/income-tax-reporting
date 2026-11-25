import { useState, type FormEvent } from "react";
import { Loader2, Plus } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
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
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { getLogger } from "@/logger";

const logger = getLogger("addCompany");

const PIB_INPUT = /^(\d{9}|\d{13})$/;
const EMPTY = { name: "", pib: "", referent: "", office: "" };
type Field = keyof typeof EMPTY;
// The company's type (user, 2026-11-25): which PB-1 form it files.
type FormType = "pdp" | "ppdg";
const FORM_TYPES: { value: FormType; label: string }[] = [
  { value: "pdp", label: "PDP" },
  { value: "ppdg", label: "PPDG-1S" },
];

/**
 * "Dodaj firmu" on Edit Company Data (user, 2026-11-25): a new company for the year shown, added
 * as the last row of its table (POST /api/reporting-years/{year}/companies). The same input
 * rules as editing the details in the table (NAZIV, REFERENT, office upper case while typing,
 * NAZIV required; PIB digits only, 9 or 13 digits or empty); the backend checks them too.
 */
export function AddCompanyDialog({ year, onAdded }: { year: number; onAdded: (row: number) => void }) {
  const { markSessionExpired } = useAuth();
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState(EMPTY);
  const [formType, setFormType] = useState<FormType>("pdp");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (field: Field, text: string) => {
    // As in the table: digits only in PIB (at most 13), upper case elsewhere.
    if (field === "pib" && !/^\d{0,13}$/.test(text)) return;
    setValues((v) => ({ ...v, [field]: field === "pib" ? text : text.toUpperCase() }));
  };
  const nameMissing = values.name.trim() === "";
  const pibInvalid = values.pib !== "" && !PIB_INPUT.test(values.pib);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (nameMissing || pibInvalid) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/reporting-years/${year}/companies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: values.name,
          pib: values.pib || null,
          referent: values.referent || null,
          office: values.office || null,
          form_type: formType,
        }),
      });
      if (res.status === 401) {
        markSessionExpired();
        return;
      }
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.detail ?? `Greška na serveru (HTTP ${res.status}).`);
      logger.info(`Company added to ${year} as row ${body.row}`);
      setOpen(false);
      setValues(EMPTY);
      setFormType("pdp");
      onAdded(body.row);
    } catch (err) {
      logger.error("Adding a company failed", err);
      setError(err instanceof Error ? err.message : "Firma nije dodata.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (busy) return;
        setOpen(next);
        if (!next) {
          setValues(EMPTY);
          setFormType("pdp");
          setError(null);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="border-chart-1/40 bg-chart-1/10 text-chart-1 hover:bg-chart-1/20 hover:text-chart-1">
          <Plus />
          Dodaj firmu
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Nova firma za {year}.</DialogTitle>
            <DialogDescription>Firma se dodaje na kraj tabele, kao poslednji red. Statusi su 0.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="new-company-type">Tip firme</Label>
              <Select value={formType} onValueChange={(value) => setFormType(value as FormType)}>
                <SelectTrigger id="new-company-type" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FORM_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="new-company-name">Naziv</Label>
              <Input
                id="new-company-name"
                value={values.name}
                onChange={(e) => set("name", e.target.value)}
                aria-invalid={error !== null && nameMissing ? true : undefined}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="new-company-pib">PIB</Label>
              <Input
                id="new-company-pib"
                inputMode="numeric"
                placeholder="9 cifara, ili 13 za JMBG"
                value={values.pib}
                onChange={(e) => set("pib", e.target.value)}
                aria-invalid={pibInvalid || undefined}
              />
              {pibInvalid && (
                <p className="text-destructive text-xs">PIB mora imati 9 cifara, ili 13 cifara za JMBG fizičkog lica.</p>
              )}
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label htmlFor="new-company-referent">Referent</Label>
                <Input id="new-company-referent" value={values.referent} onChange={(e) => set("referent", e.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="new-company-office">Kancelarija</Label>
                <Input id="new-company-office" value={values.office} onChange={(e) => set("office", e.target.value)} />
              </div>
            </div>
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={busy} onClick={() => setOpen(false)}>
              Otkaži
            </Button>
            <Button type="submit" disabled={busy || nameMissing || pibInvalid}>
              {busy && <Loader2 className="animate-spin" />}
              Dodaj firmu
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
