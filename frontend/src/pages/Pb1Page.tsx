import { ArrowLeft } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { useAuth } from "@/auth/AuthContext";
import { CompanyTableSkeleton } from "@/components/CompanyTable";
import { Pb1CompanyActions } from "@/components/Pb1CompanyActions";
import { Main } from "@/components/layout/Main";
import { HeaderSearch } from "@/components/HeaderSearch";
import { Pb1Table } from "@/components/Pb1Table";
import { Pb1CreateFinal, Pb1ReportSwitch } from "@/components/Pb1ReportSwitch";
import { Pb1ComparisonTable, Pb1PreliminaryView } from "@/components/Pb1Styled";
import { SaveStatus } from "@/components/SaveStatus";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DEFAULT_PB1_TAB, PB1_TABS, type Pb1Report, usePb1 } from "@/hooks/use-pb1";
import { matches, searchText } from "@/lib/search";

// Tab titles before the first response (the API sends the exact sheet names).
const FALLBACK_TITLES: Record<string, string> = {
  "poreski-bilans": "Poreski bilans",
  uporedo: "Uporedo",
  preliminarni: "Preliminarni rezultat",
};

/**
 * PB-1 form of one company from the GFI table, with the three tabs of the PB-1 workbook
 * (Poreski bilans, Uporedo, Preliminarni rezultat). The tab is part of the URL:
 * /companies/:year/:row/pb1/:tab (default Poreski bilans), the report its query
 * (?report=preliminary | final; default: final once the preliminary report is done).
 */
export default function Pb1Page() {
  const params = useParams();
  const navigate = useNavigate();
  const year = Number(params.year);
  const row = Number(params.row);
  const tab = params.tab ?? DEFAULT_PB1_TAB;
  const [search] = useSearchParams();
  const asked = search.get("report");
  const requested: Pb1Report | undefined = asked === "preliminary" || asked === "final" ? asked : undefined;
  const { markSessionExpired } = useAuth();
  const { data, loading, error, onCommit, autosave, reload } = usePb1(year, row, tab, requested, markSessionExpired);
  const report: Pb1Report = data?.report ?? requested ?? "preliminary";
  const pageOf = (to: { tab?: string; report?: Pb1Report }) =>
    `/companies/${year}/${row}/pb1/${to.tab ?? tab}?report=${to.report ?? report}`;
  const finalMissing = data?.report === "final" && !data.final_created;

  // Search (header field, Poreski bilans only; user, 2026-11-17): the rows whose line number,
  // description or konto contain it are marked; Enter / the arrows step through them.
  const [query, setQuery] = useState("");
  const [current, setCurrent] = useState(0);
  const searchable = data?.tab === "poreski-bilans" && !finalMissing;
  const found = useMemo(() => {
    const wanted = searchText(query);
    if (!searchable || !data || !wanted) return [];
    return [...data.rows, ...(data.summary ?? [])]
      .filter((r) => matches(wanted, [r.cells.A?.value, r.cells.B?.value, r.cells.G?.value]))
      .map((r) => r.row);
  }, [searchable, data, query]);
  useEffect(() => setCurrent(0), [query]);
  const focus = found.length ? found[Math.min(current, found.length - 1)] : null;
  useEffect(() => {
    if (focus === null) return;
    document.querySelector(`[data-pb1-row="${focus}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus]);
  const step = (by: number) => setCurrent((c) => (found.length ? (c + by + found.length) % found.length : 0));
  const tabs = data?.tabs ?? PB1_TABS.map((key) => ({ key, title: FALLBACK_TITLES[key] }));

  // Changes are saved after each field; save once more before leaving the tab or the page.
  const leaveTo = async (to: string) => {
    await autosave.flush();
    navigate(to);
  };

  return (
    <Main>
      {searchable && (
        <HeaderSearch
          value={query}
          onChange={setQuery}
          placeholder="Search the form"
          emptyText="Nema"
          steps={{ current: Math.min(current, Math.max(found.length - 1, 0)), total: found.length, onPrevious: () => step(-1), onNext: () => step(1) }}
        />
      )}
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
        </div>
      </div>


      {data && (
        // The company's two reports (user, 2026-11-17): Preliminary / Final.
        <div className="mt-4">
          <Pb1ReportSwitch
            year={year}
            row={row}
            report={report}
            preliminaryDone={Boolean(data.preliminary_done)}
            finalCreated={Boolean(data.final_created)}
            finalDone={Boolean(data.final_done)}
            submittedAt={data.submitted_at}
            flush={autosave.flush}
            onSelect={(next) => void leaveTo(pageOf({ report: next }))}
            onChanged={reload}
            // In the same line (user, 2026-11-17): the actions for the whole company form (all
            // three tabs of the report shown); none while the final report doesn't exist.
            actions={
              finalMissing ? undefined : (
                <Pb1CompanyActions year={year} row={row} report={report} flush={autosave.flush} />
              )
            }
          />
        </div>
      )}

      <Tabs value={tab} onValueChange={(next) => void leaveTo(pageOf({ tab: next }))} className="mt-14">
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
        {data && finalMissing && (
          <Pb1CreateFinal year={year} row={row} gfiDone={Boolean(data.gfi_done)} onChanged={reload} />
        )}
        {data && !finalMissing && (
          <div className={loading ? "pointer-events-none opacity-60 transition-opacity" : undefined}>
            {data.tab === "poreski-bilans" ? (
              // The form over the full width, as the other two tabs; its global comments pop up
              // at the mouse over their rows (edited on the Global Settings page).
              <Pb1Table data={data} onCommit={onCommit} marks={{ rows: new Set(found), current: focus }} />
            ) : data.tab === "uporedo" ? (
              // Styled views (same fields, same editing): the two years side by side.
              <Pb1ComparisonTable data={data} onCommit={onCommit} />
            ) : data.tab === "preliminarni" ? (
              // The sheet's two tables and the sections below as cards.
              <Pb1PreliminaryView data={data} onCommit={onCommit} />
            ) : (
              <Pb1Table data={data} onCommit={onCommit} />
            )}
          </div>
        )}
      </div>
    </Main>
  );
}
