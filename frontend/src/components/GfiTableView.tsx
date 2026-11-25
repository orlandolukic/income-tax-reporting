import { companies, ofCompanies } from "@/lib/plural";
import { useEffect, useState } from "react";
import { AddCompanyDialog } from "@/components/AddCompanyDialog";
import { DeleteCompaniesDialog } from "@/components/DeleteCompaniesDialog";
import { TypeFilterButton, type TypeFilter } from "@/components/TypeFilterButton";
import { CompanyTable, CompanyTableSkeleton, type TableVariant } from "@/components/CompanyTable";
import { HeaderSearch } from "@/components/HeaderSearch";
import { GfiStats } from "@/components/GfiStats";
import { ReportingYearSelect } from "@/components/ReportingYearSelect";
import { SaveStatus } from "@/components/SaveStatus";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useGfiEditor } from "@/hooks/use-gfi-editor";
import { cn } from "@/lib/utils";

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
  // Home: which company type is shown (user, 2026-11-25); all by default.
  const [typeFilter, setTypeFilter] = useState<TypeFilter>(null);
  // Both pages (user, 2026-11-25): the table starts 204 px from the top of the window.
  const compact = true;
  // A company just added (Edit Company Data): once the table is reloaded, its last row is
  // scrolled into sight.
  const [added, setAdded] = useState<number | null>(null);
  useEffect(() => {
    if (added === null || !table.data?.rows.some((r) => r.row === added)) return;
    const rows = document.querySelectorAll("main table tbody tr");
    rows[rows.length - 1]?.scrollIntoView({ block: "center", behavior: "smooth" });
    setAdded(null);
  }, [added, table.data]);
  const home = variant === "home";
  const count = table.data
    ? (query.trim() || typeFilter) && shown !== null
      ? `${shown} od ${ofCompanies(table.data.rows.length)}`
      : companies(table.data.rows.length)
    : null;

  return (
    <>
      <HeaderSearch
        value={query}
        onChange={setQuery}
        placeholder="Pretraga firmi"
        leading={variant === "home" ? <TypeFilterButton value={typeFilter} onChange={setTypeFilter} /> : undefined}
      />
      {/* Home and Edit Company Data (user, 2026-11-25): the table starts as high as the PB-1 report
          switch (204 px from the top of the window): the year selector and save status stay right of
          the heading instead of wrapping below it, the description in small text. Home: the company
          count beside the title, the statistics strip right below the description. */}
      <div
        className={cn(
          "flex flex-wrap items-center justify-between gap-4",
          compact && "md:flex-nowrap md:items-start",
        )}
      >
        <div className={cn(compact && "min-w-0 flex-1")}>
          <div className="flex items-baseline gap-3">
            <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
            {home && count && <span className="text-muted-foreground text-sm">{count}</span>}
          </div>
          {description && <p className={cn("text-muted-foreground", compact && "text-sm")}>{description}</p>}
          {!home && count && <p className="text-muted-foreground text-sm">{count}</p>}
        </div>
        {/* Level with the first line of the description (user, 2026-11-25). */}
        <div className={cn("flex flex-wrap items-center gap-4", compact && "md:mt-6 md:flex-nowrap")}>
          <SaveStatus status={autosave.status} pendingCount={autosave.pendingCount} onRetry={autosave.retry} />
          {/* A new company at the end of the year's table (user, 2026-11-25). */}
          {variant === "registry" && selectedYear !== null && (
            <AddCompanyDialog
              year={selectedYear}
              onAdded={(row) => {
                setAdded(row);
                table.reload();
              }}
            />
          )}
          {/* Deleting companies without data, one or more at once (user, 2026-11-25). */}
          {variant === "registry" && selectedYear !== null && (
            <DeleteCompaniesDialog year={selectedYear} onDeleted={() => table.reload()} />
          )}
          <ReportingYearSelect />
        </div>
      </div>
      {/* Home statistics (user, 2026-11-25): a low strip over the full width right below the
          heading; when the page is scrolled it stays stuck under the page header and the table
          gets the room the heading leaves (never less than at the top). Not stuck on phones. */}
      {home && table.data?.stats && (
        <div className="bg-background pt-1 pb-1.5 sm:sticky sm:top-16 sm:z-30">
          <GfiStats stats={table.data.stats} />
        </div>
      )}
      <div className={home ? undefined : "mt-6"}>
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
            <CompanyTable
              data={table.data}
              onCommit={onCommit}
              year={selectedYear}
              variant={variant}
              query={query}
              typeFilter={variant === "home" ? typeFilter : null}
              onShown={setShown}
            />
          </div>
        )}
      </div>
    </>
  );
}
