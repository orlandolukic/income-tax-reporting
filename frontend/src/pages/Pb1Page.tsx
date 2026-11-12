import { AlertCircle, ArrowLeft } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router";
import { useAuth } from "@/auth/AuthContext";
import { CompanyTableSkeleton } from "@/components/CompanyTable";
import { Pb1CompanyActions } from "@/components/Pb1CompanyActions";
import { Main } from "@/components/layout/Main";
import { Pb1Comments, Pb1Table } from "@/components/Pb1Table";
import { SaveStatus } from "@/components/SaveStatus";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DEFAULT_PB1_TAB, PB1_TABS, usePb1 } from "@/hooks/use-pb1";
import { formatNumber } from "@/lib/excel-format";

// Tab titles before the first response (the API sends the exact sheet names).
const FALLBACK_TITLES: Record<string, string> = {
  "poreski-bilans": "Poreski bilans",
  uporedo: "Uporedo",
  preliminarni: "Preliminarni rezultat",
};

/**
 * PB-1 form of one company from the GFI table, with the three tabs of the PB-1 workbook
 * (Poreski bilans, Uporedo, Preliminarni rezultat). The tab is part of the URL:
 * /companies/:year/:row/pb1/:tab (default Poreski bilans).
 */
export default function Pb1Page() {
  const params = useParams();
  const navigate = useNavigate();
  const year = Number(params.year);
  const row = Number(params.row);
  const tab = params.tab ?? DEFAULT_PB1_TAB;
  const { markSessionExpired } = useAuth();
  const { data, loading, error, onCommit, autosave } = usePb1(year, row, tab, markSessionExpired);
  const tabs = data?.tabs ?? PB1_TABS.map((key) => ({ key, title: FALLBACK_TITLES[key] }));

  // Changes are saved after each field; save once more before leaving the tab or the page.
  const leaveTo = async (to: string) => {
    await autosave.flush();
    navigate(to);
  };

  return (
    <Main>
      <Button variant="outline" size="sm" asChild>
        <Link
          to="/"
          onClick={(e) => {
            e.preventDefault();
            void leaveTo("/");
          }}
        >
          <ArrowLeft />
          Back
        </Link>
      </Button>

      <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{data?.company.name ?? "PB-1"}</h1>
          <p className="text-muted-foreground text-sm">
            PB-1 · {data?.sheet ?? FALLBACK_TITLES[tab] ?? tab} · {year}
            {data?.company.pib && ` · PIB ${data.company.pib}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <SaveStatus status={autosave.status} pendingCount={autosave.pendingCount} onRetry={autosave.retry} />
          {data && (
            <Badge variant={data.has_values || data.entered ? "secondary" : "outline"}>
              {data.has_values
                ? `Values from ${data.workbook}`
                : data.entered
                  ? `${data.entered} ${data.entered === 1 ? "value" : "values"} entered`
                  : "No PB-1 values yet"}
            </Badge>
          )}
        </div>
      </div>

      {data?.loss && (
        // Tax loss: the tax base is negative, so the tax and the monthly advance are 0.
        <Alert variant="destructive" className="mt-4">
          <AlertCircle />
          <AlertTitle>Gubitak!</AlertTitle>
          <AlertDescription>
            Poreska osnovica {formatNumber(data.loss.base, "#,##0.00").text}: porez i mesečna akontacija su 0.
          </AlertDescription>
        </Alert>
      )}

      {data && (
        // Actions for the whole company form (all three tabs).
        <div className="mt-4">
          <Pb1CompanyActions
            year={year}
            row={row}
            companyName={data.company.name}
            flush={autosave.flush}
            onUnauthorized={markSessionExpired}
          />
        </div>
      )}

      <Tabs
        value={tab}
        onValueChange={(next) => void leaveTo(`/companies/${year}/${row}/pb1/${next}`)}
        className="mt-4"
      >
        <TabsList>
          {tabs.map((t) => (
            <TabsTrigger key={t.key} value={t.key}>
              {t.title}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div className="mt-4">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {loading && !data && <CompanyTableSkeleton />}
        {data && (
          <div className={loading ? "pointer-events-none opacity-60 transition-opacity" : undefined}>
            {data.comment_column ? (
              // The comments beside the form (below it on narrower screens).
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
                <div className="min-w-0">
                  <Pb1Table data={data} onCommit={onCommit} />
                </div>
                <Pb1Comments data={data} onCommit={onCommit} />
              </div>
            ) : (
              <Pb1Table data={data} onCommit={onCommit} />
            )}
          </div>
        )}
      </div>
    </Main>
  );
}
