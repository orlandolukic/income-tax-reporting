import { useEffect, useState } from "react";
import { getLogger } from "@/logger";

const logger = getLogger("pb1");

export type Pb1Cell = { value?: string | number | boolean | null; format?: string; bold?: boolean };
export type Pb1Column = { key: string; header: string | null; width: number };
export type Pb1Row = { row: number; cells: Record<string, Pb1Cell> };
export type Pb1Data = {
  company: { row: number; name: string; pib: string | null };
  workbook: string;
  sheet: string;
  has_values?: boolean;
  columns: Pb1Column[];
  rows: Pb1Row[];
};

/** Loads the PB-1 table of the company in GFI row `row` for a reporting year. */
export function usePb1(year: number, row: number, onUnauthorized: () => void) {
  const [data, setData] = useState<Pb1Data | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetch(`/api/reporting-years/${year}/companies/${row}/pb1`, { signal: controller.signal })
      .then(async (res) => {
        if (res.status === 401) {
          onUnauthorized();
          throw new Error("HTTP 401");
        }
        if (res.status === 404) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.detail ?? "Not found");
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((pb1: Pb1Data) => {
        setData(pb1);
        logger.debug(`PB-1 loaded for row ${row} (${year}), values: ${Boolean(pb1.has_values)}`);
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        logger.error(`Failed to load PB-1 for row ${row} (${year})`, err);
        setError(err.message.startsWith("HTTP") ? "Unable to load the PB-1 table." : err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // onUnauthorized is intentionally not a dependency: it must not trigger a reload.
  }, [year, row]);

  return { data, loading, error };
}
