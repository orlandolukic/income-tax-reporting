import { CompanyTable, CompanyTableSkeleton, type TableVariant } from "@/components/CompanyTable";
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

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          {description && <p className="text-muted-foreground">{description}</p>}
          {table.data && (
            <p className="text-muted-foreground text-sm">
              {table.data.rows.length} companies · {table.data.workbook}
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
          <p className="text-muted-foreground text-sm">No financial reporting workbooks found.</p>
        )}
        {table.error && (
          <Alert variant="destructive">
            <AlertDescription>{table.error}</AlertDescription>
          </Alert>
        )}
        {table.loading && !table.data && <CompanyTableSkeleton />}
        {table.data && selectedYear !== null && (
          <div className={table.loading ? "pointer-events-none opacity-60 transition-opacity" : undefined}>
            <CompanyTable data={table.data} onCommit={onCommit} year={selectedYear} variant={variant} />
            {/* Statistics under the table: Home only. */}
            {variant === "home" && table.data.stats && (
              <div className="mt-4">
                <GfiStats stats={table.data.stats} />
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
