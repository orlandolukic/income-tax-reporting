import { useCallback, useEffect, useRef } from "react";
import { useAuth } from "@/auth/AuthContext";
import { textOf, type CommitCell } from "@/components/CompanyTable";
import { useAutosave } from "@/context/CellAutosaveProvider";
import { useReportingYear } from "@/context/ReportingYearProvider";
import { originalValue, useCompanyTable } from "@/hooks/use-company-table";

/**
 * Data and editing for a GFI table page (Home, Company Registry): loads the table for the
 * selected reporting year and saves edits through the shared autosave queue. Every page
 * loads fresh data when opened, so changes made on one page show on the other.
 */
export function useGfiEditor() {
  const { markSessionExpired } = useAuth();
  const reportingYear = useReportingYear();
  const { selectedYear } = reportingYear;
  const autosave = useAutosave();
  const table = useCompanyTable(selectedYear, {
    pendingFor: autosave.pendingFor,
    onUnauthorized: markSessionExpired,
  });

  const tableRef = useRef(table);
  tableRef.current = table;
  const yearRef = useRef(selectedYear);
  yearRef.current = selectedYear;

  useEffect(
    () =>
      autosave.subscribe({
        onSaved: (edit, result) => {
          // PB-1 form edits share the queue; they are not GFI cells.
          if (edit.pb1 || edit.year !== yearRef.current) return;
          tableRef.current.setCell(result.row, result.column, { edited: result.edited });
          // Formulas (computed by the server) follow the new value right away.
          for (const [column, value] of Object.entries(result.formulas ?? {})) {
            tableRef.current.setCell(result.row, column, { value });
          }
          // Totals under the Home table follow too.
          if (result.stats) tableRef.current.setStats(result.stats);
        },
        onRejected: (edit) => {
          if (!edit.pb1 && edit.year === yearRef.current) tableRef.current.reload();
        },
      }),
    [autosave.subscribe],
  );

  const handleCommit: CommitCell = (row, column, value) => {
    const cell = tableRef.current.data?.rows.find((r) => r.row === row)?.cells[column];
    const year = yearRef.current;
    if (!cell || year === null) return;
    const original = originalValue(cell);
    const edited = cell.text ? textOf(value) !== textOf(original) : value !== original;
    // Show the change immediately; the autosave queue sends it to the server.
    table.setCell(row, column, { value, edited, original });
    autosave.enqueue({ year, row, column, value });
  };
  // Stable callback so table rows don't re-render on every page render.
  const commitRef = useRef(handleCommit);
  commitRef.current = handleCommit;
  const onCommit = useCallback<CommitCell>((...args) => commitRef.current(...args), []);

  return { ...reportingYear, table, autosave, onCommit };
}
