import { ArrowLeft } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { useAuth } from "@/auth/AuthContext";
import { CompanyTableSkeleton } from "@/components/CompanyTable";
import { Pb1CompanyActions } from "@/components/Pb1CompanyActions";
import { Main } from "@/components/layout/Main";
import { HeaderSearch } from "@/components/HeaderSearch";
import { Pb1Strip, Pb1Table } from "@/components/Pb1Table";
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
  // The Poreski bilans strip is shown on all three tabs (user, 2026-11-25): on the other two its
  // data is loaded beside the tab's own (same report).
  const onBalance = tab === "poreski-bilans";
  const balance = usePb1(year, row, "poreski-bilans", requested, markSessionExpired, !onBalance);
  const stripData = onBalance ? data : balance.data;
  const stripCommit = onBalance ? onCommit : balance.onCommit;
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

  const tabsList = (
    <Tabs value={tab} onValueChange={(next) => void leaveTo(pageOf({ tab: next }))}>
      {/* Compact (user, 2026-11-25): narrow and taller, each title on two lines, as high as the
          head table beside them. */}
      <TabsList className="h-12 border">
        {tabs.map((t) => (
          <TabsTrigger
            key={t.key}
            value={t.key}
            // A line round every tab (user, 2026-11-25: more visible), stronger on the chosen one.
            className="border-border h-full w-22 px-1.5 text-xs leading-tight whitespace-normal data-[state=active]:border-foreground/25"
          >
            {t.title}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );

  return (
    // Less top padding (user, 2026-11-25: everything above the form as compact as it can be).
    <Main className="pt-1">
      {searchable && (
        <HeaderSearch
          value={query}
          onChange={setQuery}
          placeholder="Pretraga obrasca"
          emptyText="Nema"
          steps={{ current: Math.min(current, Math.max(found.length - 1, 0)), total: found.length, onPrevious: () => step(-1), onNext: () => step(1) }}
        />
      )}
      {/* Compact (user, 2026-11-25: room for the strip and the table): Back, the company name, its
          line and the save status in one row; the report switch, its steps, the actions and History
          in the next; a line; then the strip (with the tabs) on all three tabs. */}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
          <Button variant="outline" size="sm" className="h-7" asChild>
            <Link
              to="/"
              onClick={(e) => {
                e.preventDefault();
                void leaveTo("/");
              }}
            >
              <ArrowLeft />
              Nazad
            </Link>
          </Button>
          <h1 className="text-xl font-bold tracking-tight">{data?.company.name ?? "PB-1"}</h1>
          <p className="text-muted-foreground text-sm">
            PB-1 · {data?.sheet ?? FALLBACK_TITLES[tab] ?? tab} · {year}
            {data?.company.pib && ` · PIB ${data.company.pib}`}
          </p>
        </div>
        <div className="flex h-7 flex-wrap items-center gap-4">
          <SaveStatus status={autosave.status} pendingCount={autosave.pendingCount} onRetry={autosave.retry} />
        </div>
      </div>

      {data && (
        // The company's two reports (user, 2026-11-17): Preliminary / Final.
        <div className="mt-1">
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
      {data && !finalMissing ? (
        <Pb1Strip
          data={stripData}
          onCommit={stripCommit}
          tabs={tabsList}
          marks={onBalance ? { rows: new Set(found), current: focus } : undefined}
        />
      ) : (
        <div className="mt-3">{tabsList}</div>
      )}

      <div>
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
