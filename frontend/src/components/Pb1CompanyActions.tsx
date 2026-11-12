import { useState } from "react";
import { Download, Loader2, Printer, Save } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { getLogger } from "@/logger";

const logger = getLogger("pb1Actions");

type Action = "save" | "download" | "print";

// One color per action (theme tokens), as tinted buttons.
const TINT: Record<Action, string> = {
  save: "border-success/40 bg-success/10 text-success hover:bg-success/20 hover:text-success",
  download: "border-chart-2/40 bg-chart-2/10 text-chart-2 hover:bg-chart-2/20 hover:text-chart-2",
  print: "border-chart-3/40 bg-chart-3/10 text-chart-3 hover:bg-chart-3/20 hover:text-chart-3",
};

const UNSAVED = "Neke izmene još nisu snimljene (nema veze sa serverom?). Pokušajte ponovo.";

/** The file name the server gives in Content-Disposition (filename*=UTF-8''...), else a fallback. */
function fileName(res: Response, fallback: string): string {
  const header = res.headers.get("Content-Disposition") ?? "";
  const match = /filename\*=UTF-8''([^;]+)/i.exec(header);
  return match ? decodeURIComponent(match[1]) : fallback;
}

/**
 * Company-level actions of the PB-1 form (all three tabs at once): save every unsaved change,
 * download the form as a PDF, print it. The PDF is made by the server from the saved values,
 * so unsaved changes are always sent first.
 */
export function Pb1CompanyActions({
  year,
  row,
  companyName,
  flush,
  onUnauthorized,
}: {
  year: number;
  row: number;
  companyName: string;
  flush: () => Promise<boolean>;
  onUnauthorized: () => void;
}) {
  const [busy, setBusy] = useState<Action | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const run = async (action: Action, work: () => Promise<void>) => {
    setBusy(action);
    setMessage(null);
    try {
      await work();
    } catch (err) {
      logger.error(`PB-1 ${action} failed`, err);
      setMessage({ kind: "error", text: err instanceof Error ? err.message : "Greška." });
    } finally {
      setBusy(null);
    }
  };

  const saveAll = async () => {
    if (!(await flush())) throw new Error(UNSAVED);
  };

  const fetchPdf = async (inline: boolean): Promise<{ blob: Blob; name: string }> => {
    await saveAll();
    const res = await fetch(`/api/reporting-years/${year}/companies/${row}/pb1-pdf${inline ? "?inline=true" : ""}`);
    if (res.status === 401) {
      onUnauthorized();
      throw new Error("Sesija je istekla.");
    }
    if (!res.ok) throw new Error("PDF nije mogao da se napravi.");
    return { blob: await res.blob(), name: fileName(res, `PB-1 ${year} ${companyName}.pdf`) };
  };

  const onSave = () =>
    run("save", async () => {
      await saveAll();
      setMessage({ kind: "ok", text: "Sve izmene su sačuvane." });
    });

  const onDownload = () =>
    run("download", async () => {
      const { blob, name } = await fetchPdf(false);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      logger.info(`PB-1 PDF downloaded: ${name}`);
    });

  const onPrint = () =>
    run("print", async () => {
      const { blob } = await fetchPdf(true);
      const url = URL.createObjectURL(blob);
      // The browser's PDF viewer in a hidden frame opens its print dialog (print or save as PDF).
      const frame = document.createElement("iframe");
      frame.className = "fixed size-0 border-0";
      frame.src = url;
      frame.onload = () => {
        frame.contentWindow?.focus();
        frame.contentWindow?.print();
      };
      document.body.appendChild(frame);
      setTimeout(() => {
        frame.remove();
        URL.revokeObjectURL(url);
      }, 300_000);
    });

  const button = (action: Action, label: string, icon: React.ReactNode, onClick: () => void) => (
    <Button
      variant="outline"
      size="sm"
      className={cn(TINT[action])}
      disabled={busy !== null}
      onClick={onClick}
    >
      {busy === action ? <Loader2 className="animate-spin" /> : icon}
      {label}
    </Button>
  );

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {button("save", "Sačuvaj izmene", <Save />, onSave)}
        {button("download", "Preuzmi PDF", <Download />, onDownload)}
        {button("print", "Štampaj PDF", <Printer />, onPrint)}
        {message?.kind === "ok" && <span className="text-success text-sm">{message.text}</span>}
      </div>
      {message?.kind === "error" && (
        <Alert variant="destructive">
          <AlertDescription>{message.text}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
