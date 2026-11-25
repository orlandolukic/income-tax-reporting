import { useState } from "react";
import { FileText, Loader2, Save } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { getLogger } from "@/logger";

const logger = getLogger("pb1Actions");

type Action = "save" | "report";

// One color per action (theme tokens), as tinted buttons.
const TINT: Record<Action, string> = {
  save: "border-success/40 bg-success/10 text-success hover:bg-success/20 hover:text-success",
  report: "border-chart-2/40 bg-chart-2/10 text-chart-2 hover:bg-chart-2/20 hover:text-chart-2",
};

const UNSAVED = "Neke izmene još nisu snimljene (nema veze sa serverom?). Pokušajte ponovo.";
const BLOCKED = "Pregledač nije dozvolio novu karticu. Dozvolite iskačuće prozore za ovu stranicu i pokušajte ponovo.";

/**
 * Company-level actions of the PB-1 form (all three tabs at once): save every unsaved change,
 * and generate the report: the PDF of the three tabs, made by the server from the saved values
 * (so unsaved changes are sent first), opened in a new browser tab.
 */
export function Pb1CompanyActions({
  year,
  row,
  report,
  flush,
}: {
  year: number;
  row: number;
  report: "preliminary" | "final"; // the report shown: the PDF is made of it
  flush: () => Promise<boolean>;
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

  const onSave = () =>
    run("save", async () => {
      await saveAll();
      setMessage({ kind: "ok", text: "Sve izmene su sačuvane." });
    });

  const onReport = () => {
    // The tab is opened right away, inside the click (a tab opened after waiting is blocked
    // as a pop-up); it shows the PDF once the changes are saved. The server's address keeps
    // the report's file name for saving it from the browser's PDF viewer.
    const tab = window.open("", "_blank");
    if (!tab) {
      setMessage({ kind: "error", text: BLOCKED });
      return;
    }
    tab.document.title = "PB-1";
    tab.document.body.textContent = "Izveštaj se pravi…";
    return run("report", async () => {
      try {
        await saveAll();
      } catch (err) {
        tab.close();
        throw err;
      }
      tab.location.href = `/api/reporting-years/${year}/companies/${row}/pb1-pdf?inline=true&report=${report}`;
      logger.info(`PB-1 ${report} report opened (${year}, row ${row})`);
    });
  };

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
        {button("report", "Napravi PDF izveštaj", <FileText />, onReport)}
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
