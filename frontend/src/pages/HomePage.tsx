import { useCallback, useRef } from "react";
import { useAuth } from "@/auth/AuthContext";
import { CompanyTable, CompanyTableSkeleton, type CommitCell } from "@/components/CompanyTable";
import { Main } from "@/components/layout/Main";
import { ReportingYearSelect } from "@/components/ReportingYearSelect";
import { SaveStatus } from "@/components/SaveStatus";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useReportingYear } from "@/context/ReportingYearProvider";
import { useCellAutosave } from "@/hooks/use-cell-autosave";
import { originalValue, useCompanyTable } from "@/hooks/use-company-table";

export default function HomePage() {
  const { markSessionExpired } = useAuth();
  const { years, selectedYear, loading, error } = useReportingYear();

  const autosave = useCellAutosave({
    onSaved: (edit, result) => {
      if (edit.year === selectedYear) table.setCell(result.row, result.column, { edited: result.edited });
    },
    onRejected: (edit) => {
      if (edit.year === selectedYear) table.reload();
    },
    onUnauthorized: markSessionExpired,
  });
  const table = useCompanyTable(selectedYear, {
    pendingFor: autosave.pendingFor,
    onUnauthorized: markSessionExpired,
  });

  const handleCommit: CommitCell = (row, column, value) => {
    const cell = table.data?.rows.find((r) => r.row === row)?.cells[column];
    if (!cell || selectedYear === null) return;
    const original = originalValue(cell);
    // Show the change immediately; the autosave queue sends it to the server.
    table.setCell(row, column, { value, edited: value !== original, original });
    autosave.enqueue({ year: selectedYear, row, column, value });
  };
  // Stable callback so table rows don't re-render on every page render.
  const commitRef = useRef(handleCommit);
  commitRef.current = handleCommit;
  const onCommit = useCallback<CommitCell>((...args) => commitRef.current(...args), []);

  return (
    <Main>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Home</h1>
          {table.data && (
            <p className="text-muted-foreground text-sm">
              {table.data.rows.length} rows · {table.data.workbook}
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
            <CompanyTable data={table.data} onCommit={onCommit} year={selectedYear} />
          </div>
        )}
      </div>
    </Main>
  );
}
