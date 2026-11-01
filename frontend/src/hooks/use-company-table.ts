import { useCallback, useEffect, useRef, useState } from "react";
import { getLogger } from "@/logger";

const logger = getLogger("companyTable");

export type CellValue = string | number | boolean | null;
// Fields equal to their default are omitted by the API.
export type CompanyCell = {
  value?: CellValue;
  format?: string; // Excel number format; missing = "General"
  formula?: boolean;
  editable?: boolean;
  edited?: boolean;
  original?: CellValue; // Excel value of an edited cell
};
export type CompanyColumn = { key: string; header: string | null };
export type CompanyRow = { row: number; cells: Record<string, CompanyCell> };
export type CompanyTableData = {
  workbook: string;
  sheet: string;
  columns: CompanyColumn[];
  rows: CompanyRow[];
};

export type PendingValue = { row: number; column: string; value: number | null };

type Options = {
  /** Changes not yet saved on the server, applied on top of freshly loaded data. */
  pendingFor: (year: number) => PendingValue[];
  onUnauthorized: () => void;
};

/** Loads the company table for a reporting year; reloads whenever the year changes. */
export function useCompanyTable(year: number | null, options: Options) {
  const [data, setData] = useState<CompanyTableData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    if (year === null) {
      setData(null);
      return;
    }
    // Abort the previous request so a slow response can't overwrite a newer year.
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetch(`/api/reporting-years/${year}/companies`, { signal: controller.signal })
      .then((res) => {
        if (res.status === 401) {
          optionsRef.current.onUnauthorized();
          throw new Error("HTTP 401");
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((table: CompanyTableData) => {
        setData(applyPending(table, optionsRef.current.pendingFor(year)));
        logger.debug(`Company table loaded for ${year}: ${table.rows.length} rows`);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        logger.error(`Failed to load company table for ${year}`, err);
        setData(null);
        setError("Unable to load company data for this reporting year.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [year, reloadKey]);

  const setCell = useCallback((row: number, column: string, patch: Partial<CompanyCell>) => {
    setData((prev) => prev && patchCell(prev, row, column, patch));
  }, []);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  return { data, loading, error, setCell, reload };
}

function patchCell(
  table: CompanyTableData,
  row: number,
  column: string,
  patch: Partial<CompanyCell>,
): CompanyTableData {
  return {
    ...table,
    rows: table.rows.map((r) =>
      r.row === row ? { ...r, cells: { ...r.cells, [column]: { ...r.cells[column], ...patch } } } : r,
    ),
  };
}

/** Excel value of a cell (before any edit). */
export function originalValue(cell: CompanyCell): CellValue {
  return (cell.edited ? cell.original : cell.value) ?? null;
}

function applyPending(table: CompanyTableData, pending: PendingValue[]): CompanyTableData {
  return pending.reduce((acc, p) => {
    const cell = acc.rows.find((r) => r.row === p.row)?.cells[p.column];
    if (!cell?.editable) return acc;
    const original = originalValue(cell);
    return patchCell(acc, p.row, p.column, {
      value: p.value,
      edited: p.value !== original,
      original,
    });
  }, table);
}
