import { useState } from "react";
import { CompanyTable, CompanyTableSkeleton, type TableVariant } from "@/components/CompanyTable";
import { HeaderSearch } from "@/components/HeaderSearch";
import { GfiStats } from "@/components/GfiStats";
import { ReportingYearSelect } from "@/components/ReportingYearSelect";
import { SaveStatus } from "@/components/SaveStatus";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useGfiEditor } from "@/hooks/use-gfi-editor";

/** Page body for a GFI table page: heading, save status, year selector and the table. */
export function GfiTableView({
  title,
  description,
  variant,
}: {
  title: string;
  description?: string;
  variant: TableVariant;
}) {
  const { years, selectedYear, loading, error, table, autosave, onCommit } = useGfiEditor();
  // Companies shown: those matching the search in the header (name, PIB, referent, office).
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState<number | null>(null);

  return (
    <>
      <HeaderSearch value={query} onChange={setQuery} placeholder="Search companies" />
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          {description && <p className="text-muted-foreground">{description}</p>}
          {table.data && (
            <p className="text-muted-foreground text-sm">
              {query.trim() && shown !== null
                ? `${shown} of ${table.data.rows.length} companies`
                : `${table.data.rows.length} companies`}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <SaveStatus status={autosave.status} pendingCount={autosave.pendingCount} onRetry={autosave.retry} />
          <ReportingYearSelect />
        </div>
      </div>
      <div className="mt-6">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {!loading && !error && years.length === 0 && (
          <p className="text-muted-foreground text-sm">Još nema nijedne godine u bazi.</p>
        )}
        {table.error && (
          <Alert variant="destructive">
            <AlertDescription>{table.error}</AlertDescription>
          </Alert>
        )}
        {table.loading && !table.data && <CompanyTableSkeleton />}
        {table.data && selectedYear !== null && (
          <div className={table.loading ? "pointer-events-none opacity-60 transition-opacity" : undefined}>
            {/* Statistics above the table, full width, stuck under the page header while the page
                scrolls (user's rule, 2026-11-15): Home only. Not stuck on phones, where the three
                cards are stacked and would cover the screen. */}
            {variant === "home" && table.data.stats && (
              <div className="bg-background pb-4 sm:sticky sm:top-16 sm:z-30">
                <GfiStats stats={table.data.stats} />
              </div>
            )}
            <CompanyTable
              data={table.data}
              onCommit={onCommit}
              year={selectedYear}
              variant={variant}
              query={query}
              onShown={setShown}
            />
          </div>
        )}
      </div>
    </>
  );
}
