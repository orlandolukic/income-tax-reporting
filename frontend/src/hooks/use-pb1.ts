import { useCallback, useEffect, useRef, useState } from "react";
import { useAutosave } from "@/context/CellAutosaveProvider";
import type { Pb1Report, PendingEdit } from "@/hooks/use-cell-autosave";

export type { Pb1Report };
import { getLogger } from "@/logger";

const logger = getLogger("pb1");

export type Pb1Value = string | number | boolean | null;
export type Pb1Cell = {
  value?: Pb1Value;
  format?: string;
  bold?: boolean;
  amount?: boolean; // amount field of the form (same for every company): 2 decimals, 0 when empty
  editable?: boolean; // every field except the line numbers
  number?: boolean; // edited as a number (amounts, numeric template fields); else as text
  edited?: boolean; // changed in the app (amount: for this company; template: for all companies)
  fill?: string; // fill color from the sheet ("#rrggbb"; Poreski bilans head rows only)
  tone?: "expense" | "income" | "balance"; // Klasa 5 red, Klasa 6 green; balance: > 0 green, < 0 red
  formula?: boolean; // computed with the workbook's formula from the current values (read-only)
  minus?: boolean; // Prekoracenje of a line with "-" in the line 59 formula: an overrun is green
  subtotal?: boolean; // signed subtotal of a section's overruns: > 0 red, < 0 green; soft brand background
};
export type Pb1Column = {
  key: string;
  header?: string | null;
  width: number;
  wrap?: boolean;
  amount?: boolean; // amount column (right-aligned)
  narrow?: boolean; // line-number column ("#"); longer text overflows into empty cells to the right
  dash_empty?: boolean; // an empty field is shown as "-" and "-" entered means empty (Konto)
  overrun?: boolean; // a positive value is an overrun, shown red (Prekoracenje)
};
export type Pb1Tab = { key: string; title: string };
export type Pb1Row = {
  row: number;
  cells: Record<string, Pb1Cell>;
  shaded?: boolean; // section row (bold description): grey background
};
export type Pb1HeadFigure = { label: string; row: number; column: string };
export type Pb1Data = {
  company: { row: number; name: string; pib: string | null };
  workbook: string;
  tab: string;
  tabs: Pb1Tab[];
  sheet: string;
  has_values?: boolean;
  entered?: number; // amounts of this tab entered in the app for this company
  columns: Pb1Column[];
  rows: Pb1Row[];
  summary?: Pb1Row[]; // closing rows (Poreski bilans), shown as a separate table below the form
  head?: Pb1Row[]; // the sheet's first rows (Poreski bilans), shown as a separate table above the form
  head_columns?: Pb1Column[]; // the head table's columns, one to one with `columns`
  head_figures?: Pb1HeadFigure[]; // the head as labelled values (Klasa 5, Klasa 6, Saldo, Meseci poslovanja)
  // Column of the comments (in the rows' cells, not in `columns`): shown beside the table as
  // description-comment pairs; global (the same for every year and company), shown only on Global Settings.
  comment_column?: string;
  loss?: { base: number }; // tax loss: the Poreski bilans tax base is negative ("Gubitak!")
  results?: Pb1Results; // accounting and tax result, shown beside the closing rows of Poreski bilans
  // The company's two reports (user, 2026-11-17): which one this is and where they stand.
  // Omitted by the API when false / "preliminary".
  report?: Pb1Report;
  preliminary_done?: boolean; // the preliminary report is done: locked, still viewable
  gfi_done?: boolean; // GFI is done: the final report can be created
  final_created?: boolean; // the final report has been created from the preliminary one
  final_done?: boolean; // the final report is done: locked until unlocked
  submitted_at?: string; // the report is submitted (ISO date and time)
  locked?: boolean; // nothing can be changed in this report
};

/** A result of the form: its amount and whether it is a profit, a loss or zero. */
export type Pb1Result = { value: number; status: "profit" | "loss" | "zero" };
export type Pb1Results = { accounting: Pb1Result; tax: Pb1Result };

/** Saves one field: Excel row and column of the form, the new value (null clears it). */
export type Pb1Commit = (row: number, column: string, value: number | string | null) => void;

/** The three tabs of every company's PB-1 form (same as the sheets of the PB-1 workbook). */
export const PB1_TABS = ["poreski-bilans", "uporedo", "preliminarni"] as const;
export const DEFAULT_PB1_TAB = PB1_TABS[0];

function patchCell(data: Pb1Data, row: number, column: string, patch: Partial<Pb1Cell>): Pb1Data {
  const patchRows = (rows: Pb1Row[]) =>
    rows.map((r) => (r.row === row ? { ...r, cells: { ...r.cells, [column]: { ...r.cells[column], ...patch } } } : r));
  return {
    ...data,
    rows: patchRows(data.rows),
    summary: data.summary && patchRows(data.summary),
    head: data.head && patchRows(data.head),
  };
}

function findCell(data: Pb1Data, row: number, column: string): Pb1Cell | undefined {
  return [...(data.head ?? []), ...data.rows, ...(data.summary ?? [])].find((r) => r.row === row)?.cells[column];
}

/** Changes not yet saved on the server, shown on top of freshly loaded data. */
function applyPending(data: Pb1Data, pending: PendingEdit[]): Pb1Data {
  return pending.reduce(
    (acc, p) => (findCell(acc, p.row, p.column)?.editable ? patchCell(acc, p.row, p.column, { value: p.value, edited: true }) : acc),
    data,
  );
}

/**
 * Loads one tab of the PB-1 form of the company in GFI row `row` for a reporting year, and
 * edits its fields through the app-wide autosave queue (amounts for this company, template
 * fields for every company).
 */
export function usePb1(
  year: number,
  row: number,
  tab: string,
  // undefined: the server's choice (final once the preliminary report is done)
  report: Pb1Report | undefined,
  onUnauthorized: () => void,
  // false: nothing is loaded (the Poreski bilans strip on that tab itself uses the page's data).
  enabled = true,
) {
  const autosave = useAutosave();
  const [data, setData] = useState<Pb1Data | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const pendingRef = useRef(autosave.pendingPb1);
  pendingRef.current = autosave.pendingPb1;

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    const query = report ? `?report=${report}` : "";
    fetch(`/api/reporting-years/${year}/companies/${row}/pb1/${tab}${query}`, { signal: controller.signal })
      .then(async (res) => {
        if (res.status === 401) {
          onUnauthorized();
          throw new Error("HTTP 401");
        }
        if (res.status === 404) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.detail ?? "Nije pronađeno.");
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((pb1: Pb1Data) => {
        setData(applyPending(pb1, pendingRef.current(year, row, tab, pb1.report ?? "preliminary")));
        logger.debug(`PB-1 ${tab} loaded for row ${row} (${year}), values: ${Boolean(pb1.has_values)}`);
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        logger.error(`Failed to load PB-1 for row ${row} (${year})`, err);
        setError(err.message.startsWith("HTTP") ? "PB-1 tabela nije mogla da se učita." : err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // onUnauthorized is intentionally not a dependency: it must not trigger a reload.
  }, [year, row, tab, report, reloadKey, enabled]);

  // Save results for this form: mark the field as edited or not (the server decides), and show
  // the tab's recomputed formula cells.
  useEffect(() => {
    const isOurs = (edit: PendingEdit) =>
      edit.pb1 !== undefined &&
      edit.year === year &&
      edit.pb1.tab === tab &&
      (edit.pb1.shared ||
        (edit.pb1.company === row && (edit.pb1.report ?? "preliminary") === (dataRef.current?.report ?? "preliminary")));
    return autosave.subscribe({
      onSaved: (edit, result) => {
        if (!isOurs(edit)) return;
        // A tax loss starting or ending changes which cells are 0 and read-only: reload the tab.
        if (Boolean(result.loss) !== Boolean(dataRef.current?.loss)) setReloadKey((k) => k + 1);
        setData((prev) => {
          if (!prev) return prev;
          let next: Pb1Data = {
            ...patchCell(prev, result.row, result.column, { edited: result.edited }),
            loss: result.loss ?? undefined,
            results: result.results ?? prev.results,
          };
          // Computed cells of the tab the change was made in (the page reloads on a tab switch).
          if (edit.pb1?.tab === prev.tab) {
            for (const c of result.computed ?? []) next = patchCell(next, c.row, c.column, { value: c.value });
          }
          return next;
        });
      },
      onRejected: (edit) => {
        if (isOurs(edit)) setReloadKey((k) => k + 1);
      },
    });
  }, [autosave.subscribe, year, row, tab]);

  const dataRef = useRef(data);
  dataRef.current = data;
  const enqueue = autosave.enqueue;
  const onCommit = useCallback<Pb1Commit>(
    (cellRow, column, value) => {
      const cell = dataRef.current && findCell(dataRef.current, cellRow, column);
      if (!cell?.editable) return;
      // Show the change at once; the queue sends it (amount: this company, else every company).
      setData((prev) => prev && patchCell(prev, cellRow, column, { value, edited: true }));
      const shown = dataRef.current?.report ?? "preliminary";
      enqueue({ year, row: cellRow, column, value, pb1: { company: row, tab, shared: !cell.amount, report: shown } });
    },
    [enqueue, year, row, tab],
  );

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);
  return { data, loading, error, onCommit, autosave, reload };
}
