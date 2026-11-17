import { memo, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  originalValue,
  type CellValue,
  type CompanyCell,
  type CompanyColumn,
  type CompanyRow,
  type CompanyTableData,
} from "@/hooks/use-company-table";
import { formatNumber, toEditText } from "@/lib/excel-format";
import { matches, searchText } from "@/lib/search";
import { cn } from "@/lib/utils";

/**
 * GFI company table, in two variants:
 * - "home": the compact Home table. Hidden columns, PIB below the name, empty numbers shown
 *   as 0, empty referent cells as "-". Company details are read-only. An "Actions" column
 *   opens the three tabs of the company's PB-1 form.
 * - "registry": Edit Company Data, for editing. Columns # … "PB-1, PB-2 Predat" (no formula columns), fitted to
 *   the screen; nothing is truncated (rows grow instead). Empty cells show 0 (from Preliminarni on)
 *   or "-" (company details) and can be filled in. Company details (NAZIV, PIB, REFERENT,
 *   office) are editable as text.
 *   Home's "Naziv (PIB)" column shows two of these values together: NAZIV, and the PIB
 *   column below it in parentheses. Editing either in the Registry changes it on Home.
 * Both edit the same data (same API and autosave queue).
 */
export type TableVariant = "home" | "registry";

// Hover preview opens to the left for the last columns so it stays inside the table.
const RIGHT_ANCHORED_COLUMNS = 3;
// Columns are found by their (normalized) Excel header, never by position.
const NAME_HEADER = "NAZIV";
const NAME_DISPLAY_HEADER = "Naziv (PIB)";
const PIB_HEADER = "PIB";
// Home: the PIB column is hidden (shown below the name); its data, edits and the API are unchanged.
// ("kom" is not a column any more: kom = 1 for every company, set by the server.)
const HIDDEN_HEADERS = new Set([PIB_HEADER]);
// Home: a PIB (9 digits) or JMBG (13) is shown below the name; an empty one as "-".
const PIB_PATTERN = /^(\d{9}|\d{13})$/;

// Home: from this column to the last one, the columns are numeric and empty cells are shown as 0.
const FIRST_NUMERIC_HEADER = "PRELIMINARNI";
// Edit Company Data: numeric columns start at "Preliminarni", as on Home.
const REGISTRY_FIRST_NUMERIC_HEADER = FIRST_NUMERIC_HEADER;
// Home: the unnamed column right after this one (column N) is hidden.
const LAST_SHOWN_HEADER = "PB-1,PB-2 ZA RAD";
// Edit Company Data (variant "registry"): the formula columns are not shown; nothing is entered
// in them (user's rule). Home shows them, shaded.
const FORMULA_HEADERS = new Set(["GFI ZA RAD", LAST_SHOWN_HEADER]);
// Home: REFERENT and the unnamed column right after it (office): empty cells are shown as "-".
const REFERENT_HEADER = "REFERENT";
const EMPTY_TEXT_PLACEHOLDER = "-";
// Home "Actions": one button per tab of the company's PB-1 form (one color each). The first
// opens what clicking the company name used to open (PB-1, Poreski bilans).
const PB1_ACTIONS = [
  {
    path: "",
    label: "PB",
    title: "PB-1 · Poreski bilans",
    className: "border-chart-1/40 bg-chart-1/10 text-chart-1 hover:bg-chart-1/20 hover:text-chart-1",
  },
  {
    path: "/uporedo",
    label: "Uporedo",
    title: "PB-1 · Uporedo (tekuća i prethodna godina)",
    className: "border-chart-2/40 bg-chart-2/10 text-chart-2 hover:bg-chart-2/20 hover:text-chart-2",
  },
  {
    path: "/preliminarni",
    label: "Prelim.",
    title: "PB-1 · Preliminarni rezultat",
    className: "border-chart-3/40 bg-chart-3/10 text-chart-3 hover:bg-chart-3/20 hover:text-chart-3",
  },
] as const;

function Pb1Actions({ year, row }: { year: number; row: number }) {
  return (
    <TableCell className="px-1.5 py-1 whitespace-nowrap">
      <div className="flex gap-1">
        {PB1_ACTIONS.map((action) => (
          <Button
            key={action.label}
            variant="outline"
            size="sm"
            asChild
            className={cn("h-6 rounded-md px-2 text-xs font-medium shadow-none", action.className)}
          >
            <Link to={`/companies/${year}/${row}/pb1${action.path}`} title={action.title}>
              {action.label}
            </Link>
          </Button>
        ))}
      </div>
    </TableCell>
  );
}

// Vertical column border; an inset shadow, so it stays visible on sticky cells.
const COLUMN_BORDER = "not-last:shadow-[inset_-1px_0_var(--border)]";

// Input rules (user's decisions, 2026-11-14; the backend enforces the same, see app/gfi_store.py):
// - NAZIV, REFERENT, office: upper case while typing (as with caps lock on); NAZIV can't be empty;
// - PIB: digits only (other characters are not accepted), 9 digits (PIB) or 13 (JMBG); empty allowed;
// - status columns (the numeric cells that can be edited): only 0 or 1, never empty: an empty
//   editor saves 0;
// - an empty detail (PIB, REFERENT, office) is shown as "-"; "-" entered means empty.
// Invalid input is not accepted (user's rule): a character that isn't allowed is not typed in
// (short red flash), and a value that isn't valid on Enter / leaving the field turns the border
// red and the field goes back to its old value.
type TextRule = "name" | "pib" | "upper" | undefined;
const PIB_INPUT = /^(\d{9}|\d{13})$/;
const PIB_MAX_LENGTH = 13;
const TEXT_RULE_MESSAGES: Record<"number" | "name" | "pib" | "upper", string> = {
  number: "Dozvoljene su samo vrednosti 0 i 1.",
  name: "Naziv firme ne može biti prazan.",
  pib: "PIB mora imati 9 cifara, ili 13 cifara za JMBG fizičkog lica.",
  upper: "Neispravan unos.",
};
// How long the red border shows before the field goes back to its old value (ms).
const INVALID_REVERT_MS = 900;
// A character that isn't allowed: how long the red border flashes (ms).
const INVALID_FLASH_MS = 600;

/** The typed text as the field accepts it, or undefined when it can't be accepted at all. */
function acceptInput(text: string, kind: "number" | "text", rule: TextRule): string | undefined {
  if (kind === "number") return /^[01]?$/.test(text.trim()) ? text.trim() : undefined;
  if (rule === "pib") return /^\d*$/.test(text) && text.length <= PIB_MAX_LENGTH ? text : undefined;
  if (rule === "name" || rule === "upper") return text.toUpperCase();
  return text;
}

/** A status value: 0 or 1 (an empty editor means 0), or undefined when not valid. */
function parseStatus(text: string): number | undefined {
  const value = text.trim();
  if (value === "") return 0;
  return value === "0" || value === "1" ? Number(value) : undefined;
}

const normalizeHeader = (header: string | null) => header?.trim().toUpperCase() ?? "";

const findColumn = (columns: CompanyColumn[], header: string) =>
  columns.find((c) => normalizeHeader(c.header) === header)?.key;

const isBlank = (value: CellValue) => value === null || (typeof value === "string" && value.trim() === "");

/** Text form used to compare company details (PIB 114113887 equals "114113887"). */
export const textOf = (value: CellValue | undefined) =>
  value === null || value === undefined || typeof value === "boolean" ? null : String(value).trim() || null;

function pibText(cell: CompanyCell | undefined): string {
  const value = cell?.value;
  const text = typeof value === "number" || typeof value === "string" ? String(value).trim() : "";
  return PIB_PATTERN.test(text) ? text : EMPTY_TEXT_PLACEHOLDER;
}

export type CommitCell = (row: number, column: string, value: number | string | null) => void;

function formatValue(value: CellValue, format: string | undefined): { text: string; red: boolean } {
  if (value === null) return { text: "", red: false };
  if (typeof value === "number") return formatNumber(value, format);
  if (typeof value === "boolean") return { text: value ? "TRUE" : "FALSE", red: false };
  return { text: value, red: false };
}

function cellTitle(cell: CompanyCell, canEdit: boolean): string | undefined {
  if (cell.formula) return "Formula (samo za čitanje)";
  if (cell.edited) {
    const original = cell.text
      ? textOf(originalValue(cell)) || "prazno"
      : formatValue(originalValue(cell), cell.format).text || "prazno";
    return `Izmenjeno. Prvobitna vrednost: ${original}`;
  }
  if (canEdit) return "Kliknite za izmenu";
  return undefined;
}

function parseText(text: string, rule: TextRule): string | null | undefined {
  const value = text.trim();
  // "-" is how an empty detail is shown; entered, it means empty (NAZIV can't be empty).
  if (value === "" || value === EMPTY_TEXT_PLACEHOLDER) return rule === "name" ? undefined : null;
  if (rule === "pib" && !PIB_INPUT.test(value)) return undefined;
  return value;
}

function CellEditor({
  cell,
  kind,
  rule,
  fit = false,
  hint,
  onDone,
}: {
  cell: CompanyCell;
  kind: "number" | "text";
  rule: TextRule;
  fit?: boolean; // stay inside a fixed-width cell (Registry) instead of widening the column
  hint?: string; // shown in an empty editor (the value displayed for an empty cell)
  onDone: (value: number | string | null | undefined) => void;
}) {
  const [text, setText] = useState(() =>
    kind === "number" ? toEditText(typeof cell.value === "number" ? cell.value : null) : (textOf(cell.value) ?? ""),
  );
  const [invalid, setInvalid] = useState(false);
  const [reverting, setReverting] = useState(false);
  const flashTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(flashTimer.current), []);
  const parse = (input: string) => (kind === "number" ? parseStatus(input) : parseText(input, rule));

  // A value that isn't valid: red border, then back to the old value (the edit is cancelled).
  const rejectAndRevert = () => {
    setReverting(true);
    setInvalid(true);
    window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => onDone(undefined), INVALID_REVERT_MS);
  };

  // undefined = cancel (keep the current value)
  const finish = (commit: boolean) => {
    if (reverting) return;
    if (!commit) return onDone(undefined);
    const parsed = parse(text);
    if (parsed === undefined) return rejectAndRevert();
    onDone(parsed);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") finish(true);
    if (e.key === "Escape") finish(false);
  };

  return (
    <input
      autoFocus
      inputMode={kind === "number" || rule === "pib" ? "numeric" : "text"}
      maxLength={kind === "number" ? 1 : rule === "pib" ? PIB_MAX_LENGTH : undefined}
      aria-label="Cell value"
      aria-invalid={invalid || undefined}
      title={invalid ? TEXT_RULE_MESSAGES[kind === "number" ? "number" : (rule ?? "upper")] : undefined}
      value={text}
      placeholder={hint}
      onFocus={(e) => e.currentTarget.select()}
      readOnly={reverting}
      onChange={(e) => {
        if (reverting) return;
        const accepted = acceptInput(e.target.value, kind, rule);
        window.clearTimeout(flashTimer.current);
        if (accepted === undefined) {
          // Not accepted (e.g. a letter in PIB, 2 in a status column): the text stays, a short red flash.
          setInvalid(true);
          flashTimer.current = window.setTimeout(() => setInvalid(false), INVALID_FLASH_MS);
          return;
        }
        setText(accepted);
        setInvalid(false);
      }}
      onKeyDown={onKeyDown}
      // Leaving the field saves a valid value; an invalid one turns red and goes back.
      onBlur={() => finish(true)}
      className={cn(
        "border-ring ring-ring/50 bg-background aria-invalid:border-destructive aria-invalid:ring-destructive/20 -my-1 h-7 w-full rounded-sm border px-1.5 ring-[3px] outline-none",
        kind === "number" ? "text-end tabular-nums" : "text-start",
        fit ? "min-w-0" : kind === "number" ? "min-w-20" : "min-w-40",
      )}
    />
  );
}

function DataCell({
  cell,
  alignEnd,
  onCommit,
  href,
  subText,
  numeric = false,
  zeroFill = false,
  statusColors = false,
  shadeFormula = false,
  shadeAll = false,
  viewOnly = false,
  emptyPlaceholder,
  allowText = false,
  textRule,
  quiet = false,
  fillEmpty = false,
}: {
  cell: CompanyCell;
  alignEnd: boolean;
  onCommit: (value: number | string | null) => void;
  href?: string;
  subText?: string; // second line in parentheses, e.g. the PIB below the company name
  numeric?: boolean; // numeric column: right-aligned
  zeroFill?: boolean; // empty cells are displayed as 0 (display only)
  // Home status columns (Preliminarni … PB-1,PB-2 za rad, values 0 / 1): 1 green, 0 red.
  statusColors?: boolean;
  // Home: the formula columns (GFI ZA RAD, PB-1,PB-2 za rad) are shaded, so they read as
  // computed from the other columns, not filled in (user's rule).
  shadeFormula?: boolean;
  // Shaded because nothing can be entered here (user, 2026-11-17): every Home cell (Home is view
  // only), and the status columns on Edit Company Data (set only by the PB-1 report steps).
  shadeAll?: boolean;
  // Home is view only (user, 2026-11-17): its cells don't react to the mouse at all (no
  // highlight, no enlarged preview box, no tooltip).
  viewOnly?: boolean;
  emptyPlaceholder?: string; // shown (muted) instead of an empty read-only cell (display only)
  allowText?: boolean; // company details can be edited (Edit Company Data)
  textRule?: TextRule;
  // Registry: read-only cells don't react to the mouse (no highlight, preview or tooltip),
  // and editors fit the fixed-width cell.
  quiet?: boolean;
  // Registry: empty cells in the numeric columns can be filled in (Home edits only cells
  // that hold a number in Excel).
  fillEmpty?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const value = cell.value ?? null;
  const kind = cell.editable ? (cell.text ? "text" : "number") : undefined;
  const canEdit =
    (kind === "number" && (fillEmpty || typeof originalValue(cell) === "number")) || (kind === "text" && allowText);
  const zeroFilled = zeroFill && isBlank(value);
  const placeholder = !numeric && emptyPlaceholder && isBlank(value) ? emptyPlaceholder : undefined;
  // Company details are text: numbers in them (e.g. a PIB) are shown as plain digits.
  const { text, red: negative } = formatValue(zeroFilled ? 0 : value, cell.text ? undefined : cell.format);
  // Status columns: the number shown is 1 (done) in green, 0 (not done) in red.
  const shown = zeroFilled ? 0 : value;
  const status = statusColors && typeof shown === "number" ? (shown === 1 ? "one" : shown === 0 ? "zero" : null) : null;
  const red = negative || status === "zero";
  const green = status === "one";
  const isNumber = !cell.text && (numeric || typeof value === "number" || (kind === "number" && value === null));
  // No reaction to the mouse (highlight, preview, tooltip): read-only cells in the Registry,
  // and the formula columns (GFI ZA RAD, PB-1,PB-2 za rad) on every page.
  const still = viewOnly || (quiet && !canEdit) || Boolean(cell.formula);
  const title = still
    ? undefined
    : (zeroFilled || placeholder) && !canEdit && !cell.edited && !cell.formula
      ? "Prazno (samo za čitanje)"
      : cellTitle(cell, canEdit);

  const startEditing = () => {
    if (canEdit) setEditing(true);
  };

  return (
    <TableCell
      title={editing ? undefined : title}
      tabIndex={canEdit ? 0 : undefined}
      onClick={editing ? undefined : startEditing}
      onKeyDown={(e) => {
        if (!editing && (e.key === "Enter" || e.key === "F2")) {
          e.preventDefault();
          startEditing();
        }
      }}
      className={cn(
        "group/cell relative max-w-64 px-1.5 py-1 transition-colors",
        // Registry: show everything; long values wrap and the row grows.
        quiet && "whitespace-normal",
        !still && "hover:bg-accent hover:text-accent-foreground",
        COLUMN_BORDER,
        (shadeAll || (shadeFormula && cell.formula)) && "bg-muted/60",
        isNumber && "text-end tabular-nums",
        red && "text-destructive hover:text-destructive",
        green && "text-success hover:text-success",
        // Clickable (opens the editor): pointing hand, as everything clickable in the app.
        canEdit && "focus-visible:ring-ring/50 outline-none focus-visible:ring-[3px] focus-visible:ring-inset",
        canEdit && !editing && "cursor-pointer",
        // Edited cells: small corner marker, like Excel's comment indicator.
        cell.edited &&
          "after:border-t-primary after:border-r-primary after:absolute after:top-0 after:right-0 after:border-4 after:border-b-transparent after:border-l-transparent",
      )}
    >
      {editing && kind ? (
        <CellEditor
          cell={cell}
          kind={kind}
          rule={textRule}
          fit={quiet}
          hint={zeroFilled ? "0" : placeholder}
          onDone={(newValue) => {
            setEditing(false);
            if (newValue === undefined) return;
            const unchanged = kind === "text" ? textOf(newValue) === textOf(value) : newValue === value;
            if (!unchanged) onCommit(newValue);
          }}
        />
      ) : (
        <>
          {href ? (
            <Link
              to={href}
              className="focus-visible:ring-ring/50 block truncate rounded-sm font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-[3px]"
            >
              {text}
            </Link>
          ) : (
            <span
              className={cn(
                "block",
                // Without a preview (Registry, view-only Home) a long value wraps instead of being cut.
                quiet || viewOnly ? "break-words whitespace-normal" : "truncate",
                placeholder && "text-muted-foreground",
              )}
            >
              {placeholder ?? text}
            </span>
          )}
          {subText && (
            <span className="text-muted-foreground block truncate text-xs tabular-nums">({subText})</span>
          )}
          {!still && (text.trim() !== "" || subText) && (
            // Enlarged preview of the full value, shown while hovering the cell.
            <span
              className={cn(
                "bg-popover text-popover-foreground pointer-events-none absolute top-1/2 z-30 hidden w-max max-w-sm -translate-y-1/2 rounded-md border px-3 py-1.5 text-base font-medium break-words whitespace-normal shadow-md group-hover/cell:block",
                // Over the value: numbers are right-aligned, so their preview opens from the right.
                alignEnd || isNumber ? "right-0" : "left-0",
                isNumber && "tabular-nums",
                red && "text-destructive",
                green && "text-success",
              )}
            >
              {text}
              {subText && <span className="text-muted-foreground block text-sm tabular-nums">({subText})</span>}
            </span>
          )}
        </>
      )}
    </TableCell>
  );
}

type ColumnPlan = {
  variant: TableVariant;
  nameColumn: string | undefined;
  pibColumn: string | undefined;
  visibleColumns: CompanyColumn[];
  numericColumns: Set<string>;
  zeroFillColumns: Set<string>;
  placeholderColumns: Set<string>;
  widths?: Record<string, string>; // Registry: fixed column widths, so the table fits the screen
};

// Registry column widths (percent of the table). The numeric columns share what is left.
const NUMBER_COLUMN_WIDTH = 3;
const REGISTRY_WIDTHS = { name: 22, pib: 9, referent: 11, office: 8 };

/** Columns up to and including "PB-1,PB-2 za rad"; the unnamed column after it (N) is dropped. */
function withoutColumnAfterLast(columns: CompanyColumn[]): CompanyColumn[] {
  const last = columns.findIndex((c) => normalizeHeader(c.header) === LAST_SHOWN_HEADER);
  return last >= 0 ? columns.filter((_, i) => i !== last + 1) : columns;
}

function planColumns(columns: CompanyColumn[], variant: TableVariant): ColumnPlan {
  const name = findColumn(columns, NAME_HEADER);
  const pib = findColumn(columns, PIB_HEADER);
  const keysFrom = (visible: CompanyColumn[], header: string, count?: number) => {
    const start = visible.findIndex((c) => normalizeHeader(c.header) === header);
    if (start < 0) return new Set<string>();
    return new Set(visible.slice(start, count === undefined ? undefined : start + count).map((c) => c.key));
  };

  if (variant === "registry") {
    // The workbook columns (NAZIV and PIB separate), ending with "PB-1, PB-2 Predat": without the
    // formula columns (GFI ZA RAD, PB-1,PB-2 za rad) and the unnamed column N.
    const visible = withoutColumnAfterLast(columns).filter((c) => !FORMULA_HEADERS.has(normalizeHeader(c.header)));
    const referent = visible.findIndex((c) => normalizeHeader(c.header) === REFERENT_HEADER);
    const numeric = keysFrom(visible, REGISTRY_FIRST_NUMERIC_HEADER);
    const fixed: Record<string, number> = {};
    if (name) fixed[name] = REGISTRY_WIDTHS.name;
    if (pib) fixed[pib] = REGISTRY_WIDTHS.pib;
    if (referent >= 0) fixed[visible[referent].key] = REGISTRY_WIDTHS.referent;
    if (referent >= 0 && visible[referent + 1]) fixed[visible[referent + 1].key] = REGISTRY_WIDTHS.office;
    const rest = visible.filter((c) => fixed[c.key] === undefined).length;
    const used = NUMBER_COLUMN_WIDTH + Object.values(fixed).reduce((a, b) => a + b, 0);
    const share = rest ? (100 - used) / rest : 0;
    return {
      variant,
      nameColumn: name,
      pibColumn: pib,
      visibleColumns: visible,
      numericColumns: numeric,
      // Empty cells: 0 from "Preliminarni" on, "-" in the columns left of it (display only).
      zeroFillColumns: numeric,
      placeholderColumns: new Set(visible.filter((c) => !numeric.has(c.key)).map((c) => c.key)),
      widths: Object.fromEntries(visible.map((c) => [c.key, `${(fixed[c.key] ?? share).toFixed(2)}%`])),
    };
  }

  // The PIB column is hidden only when it can be shown below the names.
  const hidden = new Set([...HIDDEN_HEADERS].filter((h) => h !== PIB_HEADER || name));
  // Hide the column right after "PB-1,PB-2 za rad" (column N), if there is one.
  const visible = withoutColumnAfterLast(columns.filter((c) => !hidden.has(normalizeHeader(c.header))));
  const numeric = keysFrom(visible, FIRST_NUMERIC_HEADER);
  return {
    variant,
    nameColumn: name,
    pibColumn: name ? pib : undefined,
    visibleColumns: visible,
    numericColumns: numeric,
    zeroFillColumns: numeric,
    placeholderColumns: keysFrom(visible, REFERENT_HEADER, 2),
  };
}

// Memoized so editing one cell re-renders only its row.
const DataRow = memo(function DataRow({
  row,
  number,
  plan,
  onCommit,
  year,
}: {
  row: CompanyRow;
  number: number;
  plan: ColumnPlan;
  onCommit: CommitCell;
  year: number;
}) {
  const { variant, visibleColumns: columns, nameColumn, pibColumn } = plan;
  const home = variant === "home";
  return (
    <TableRow>
      {/* "#": position in the company list. Edits and links use the Excel row number (row.row). */}
      <TableCell
        className="bg-background text-muted-foreground sticky left-0 z-10 w-10 px-1.5 py-1 text-end text-xs tabular-nums shadow-[inset_-1px_0_var(--border)]"
      >
        {number}
      </TableCell>
      {columns.map((column, index) => {
        const cell = row.cells[column.key] ?? {};
        const isNameColumn = column.key === nameColumn;
        return (
          <DataCell
            key={column.key}
            cell={cell}
            alignEnd={index >= columns.length - RIGHT_ANCHORED_COLUMNS}
            onCommit={(value) => onCommit(row.row, column.key, value)}
            subText={home && isNameColumn && pibColumn ? pibText(row.cells[pibColumn]) : undefined}
            numeric={plan.numericColumns.has(column.key)}
            zeroFill={plan.zeroFillColumns.has(column.key)}
            statusColors={home && plan.numericColumns.has(column.key)}
            shadeFormula={home}
            shadeAll={home || plan.numericColumns.has(column.key)}
            viewOnly={home}
            emptyPlaceholder={plan.placeholderColumns.has(column.key) ? EMPTY_TEXT_PLACEHOLDER : undefined}
            allowText={!home}
            textRule={isNameColumn ? "name" : column.key === pibColumn ? "pib" : "upper"}
            quiet={!home}
            fillEmpty={!home}
          />
        );
      })}
      {home && isCompany(row, nameColumn) && <Pb1Actions year={year} row={row.row} />}
      {home && !isCompany(row, nameColumn) && <TableCell />}
    </TableRow>
  );
});

const isCompany = (row: CompanyRow, nameColumn: string | undefined) => {
  const value = nameColumn ? row.cells[nameColumn]?.value : null;
  return typeof value === "string" && value.trim() !== "";
};

export function CompanyTable({
  data,
  onCommit,
  year,
  variant = "home",
  query = "",
  onShown,
}: {
  data: CompanyTableData;
  onCommit: CommitCell;
  year: number;
  variant?: TableVariant;
  // Search (header field): only the companies whose name, PIB, referent or office contain it.
  query?: string;
  onShown?: (count: number) => void; // how many companies the search shows
}) {
  // The API returns only the company list (165 rows for 2025), in order.
  const { columns, rows } = data;
  const plan = useMemo(() => planColumns(columns, variant), [columns, variant]);
  const registry = variant === "registry";
  // Each company keeps its position in the list (#) while the search hides others.
  const wanted = searchText(query);
  const listed = useMemo(
    () =>
      rows
        .map((row, index) => ({ row, number: index + 1 }))
        .filter(({ row }) => !wanted || matches(wanted, Object.values(row.cells).filter((c) => c.text).map((c) => c.value))),
    [rows, wanted],
  );
  useEffect(() => onShown?.(listed.length), [listed.length, onShown]);

  return (
    // Registry: fixed column widths, so the table always fits the screen (no horizontal scroll).
    <div
      className={cn(
        "rounded-md border",
        // Home: the statistics cards float at the top (sticky, about 8rem, under the 4rem page
        // header). Scrolling the page moves the title away and the table fills the screen below
        // the cards (4rem header + 8rem cards + bottom padding).
        registry ? "max-h-[calc(100svh-12rem)] overflow-x-hidden overflow-y-auto" : "max-h-[calc(100svh-14rem)] overflow-auto",
      )}
    >
      <table className={cn("w-full caption-bottom text-sm", registry && "table-fixed")}>
        {plan.widths && (
          <colgroup>
            <col style={{ width: `${NUMBER_COLUMN_WIDTH}%` }} />
            {plan.visibleColumns.map((column) => (
              <col key={column.key} style={{ width: plan.widths?.[column.key] }} />
            ))}
          </colgroup>
        )}
        <TableHeader className="bg-muted sticky top-0 z-20 [&_tr]:border-b-0 shadow-[inset_0_-1px_0_var(--border)]">
          {/* No tooltips on the headers (user's rule, Home and Edit Company Data). */}
          <TableRow className="hover:bg-transparent">
            <TableHead
              className="bg-muted text-muted-foreground sticky left-0 z-10 h-auto w-10 px-1.5 py-1.5 text-end align-bottom shadow-[inset_-1px_0_var(--border)]"
            >
              #
            </TableHead>
            {plan.visibleColumns.map((column) => (
              // Headers keep their exact Excel text but may wrap, so narrow columns stay narrow.
              <TableHead
                key={column.key}
                className={cn(
                  "h-auto px-1.5 py-1.5 align-bottom leading-tight whitespace-pre-wrap",
                  registry && "break-words",
                  // Numeric columns: header aligned with the right-aligned amounts.
                  plan.numericColumns.has(column.key) && "text-end",
                  COLUMN_BORDER,
                )}
              >
                {variant === "home" && column.key === plan.nameColumn
                  ? NAME_DISPLAY_HEADER
                  : (column.header ?? "")}
              </TableHead>
            ))}
            {!registry && (
              <TableHead className="h-auto px-1.5 py-1.5 align-bottom leading-tight">Actions</TableHead>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {listed.map(({ row, number }) => (
            <DataRow key={row.row} row={row} number={number} plan={plan} onCommit={onCommit} year={year} />
          ))}
          {wanted && listed.length === 0 && (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={plan.visibleColumns.length + 2} className="text-muted-foreground py-6 text-center">
                Nijedna firma ne odgovara pretrazi.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </table>
    </div>
  );
}

export function CompanyTableSkeleton() {
  return (
    <div className="space-y-2 rounded-md border p-4">
      {Array.from({ length: 8 }, (_, i) => (
        <Skeleton key={i} className="h-6 w-full" />
      ))}
    </div>
  );
}
