import { memo, useMemo, useState, type KeyboardEvent } from "react";
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
import { formatNumber, parseNumberInput, toEditText } from "@/lib/excel-format";
import { cn } from "@/lib/utils";

/**
 * GFI company table, in two variants:
 * - "home": the compact Home table. Hidden columns, PIB below the name, empty numbers shown
 *   as 0, empty referent cells as "-". Company details are read-only. An "Actions" column
 *   opens the three tabs of the company's PB-1 form.
 * - "registry": the Company Registry, for editing. Columns # … "PB-1,PB-2 za rad", fitted to
 *   the screen; nothing is truncated (rows grow instead). Empty cells show 0 (from kom on)
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
const KOM_HEADER = "KOM";
// Home: these columns are hidden; their data, edits and the API are unchanged.
const HIDDEN_HEADERS = new Set([KOM_HEADER, PIB_HEADER]);
// Home: only real PIBs (9 digits) are shown below the name.
const PIB_PATTERN = /^\d{9}$/;

// Home: from this column to the last one, the columns are numeric and empty cells are shown as 0.
const FIRST_NUMERIC_HEADER = "PRELIMINARNI";
// Registry: numeric columns start at "kom".
const REGISTRY_FIRST_NUMERIC_HEADER = KOM_HEADER;
// Home: the unnamed column right after this one (column N) is hidden.
const LAST_SHOWN_HEADER = "PB-1,PB-2 ZA RAD";
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
    title: "PB-1 · Uporedo (current and previous year)",
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

// Validation of company details (the backend checks the same).
type TextRule = "name" | "pib" | undefined;
const PIB_INPUT = /^\d+$/;
const TEXT_RULE_MESSAGES: Record<"number" | "name" | "pib", string> = {
  number: "Enter a number, e.g. 1234,56",
  name: "Company name can't be empty",
  pib: "PIB may contain digits only",
};

const normalizeHeader = (header: string | null) => header?.trim().toUpperCase() ?? "";

const findColumn = (columns: CompanyColumn[], header: string) =>
  columns.find((c) => normalizeHeader(c.header) === header)?.key;

const isBlank = (value: CellValue) => value === null || (typeof value === "string" && value.trim() === "");

/** Text form used to compare company details (PIB 114113887 equals "114113887"). */
export const textOf = (value: CellValue | undefined) =>
  value === null || value === undefined || typeof value === "boolean" ? null : String(value).trim() || null;

function pibText(cell: CompanyCell | undefined): string | undefined {
  const value = cell?.value;
  const text = typeof value === "number" || typeof value === "string" ? String(value).trim() : "";
  return PIB_PATTERN.test(text) ? text : undefined;
}

export type CommitCell = (row: number, column: string, value: number | string | null) => void;

function formatValue(value: CellValue, format: string | undefined): { text: string; red: boolean } {
  if (value === null) return { text: "", red: false };
  if (typeof value === "number") return formatNumber(value, format);
  if (typeof value === "boolean") return { text: value ? "TRUE" : "FALSE", red: false };
  return { text: value, red: false };
}

function cellTitle(cell: CompanyCell, canEdit: boolean): string | undefined {
  if (cell.formula) return "Formula (read-only)";
  if (cell.edited) {
    const original = cell.text
      ? textOf(originalValue(cell)) || "empty"
      : formatValue(originalValue(cell), cell.format).text || "empty";
    return `Changed. Excel value: ${original}`;
  }
  if (canEdit) return "Click to edit";
  return undefined;
}

function parseText(text: string, rule: TextRule): string | null | undefined {
  const value = text.trim();
  if (value === "") return rule === "name" ? undefined : null;
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
  const parse = (input: string) => (kind === "number" ? parseNumberInput(input) : parseText(input, rule));

  // undefined = cancel (keep the current value)
  const finish = (commit: boolean) => {
    if (!commit) return onDone(undefined);
    const parsed = parse(text);
    if (parsed === undefined) {
      setInvalid(true);
      return;
    }
    onDone(parsed);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") finish(true);
    if (e.key === "Escape") finish(false);
  };

  return (
    <input
      autoFocus
      inputMode={kind === "number" || rule === "pib" ? "decimal" : "text"}
      aria-label="Cell value"
      aria-invalid={invalid || undefined}
      title={invalid ? TEXT_RULE_MESSAGES[kind === "number" ? "number" : (rule ?? "name")] : undefined}
      value={text}
      placeholder={hint}
      onFocus={(e) => e.currentTarget.select()}
      onChange={(e) => {
        setText(e.target.value);
        setInvalid(false);
      }}
      onKeyDown={onKeyDown}
      // Leaving the field saves a valid value and discards invalid input.
      onBlur={() => (parse(text) === undefined ? finish(false) : finish(true))}
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
  emptyPlaceholder?: string; // shown (muted) instead of an empty read-only cell (display only)
  allowText?: boolean; // company details can be edited (Company Registry)
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
  const still = (quiet && !canEdit) || Boolean(cell.formula);
  const title = still
    ? undefined
    : (zeroFilled || placeholder) && !canEdit && !cell.edited && !cell.formula
      ? "Empty in Excel (read-only)"
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
        isNumber && "text-end tabular-nums",
        red && "text-destructive hover:text-destructive",
        green && "text-success hover:text-success",
        canEdit && "focus-visible:ring-ring/50 cursor-text outline-none focus-visible:ring-[3px] focus-visible:ring-inset",
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
            <span className={cn("block", quiet ? "break-words" : "truncate", placeholder && "text-muted-foreground")}>
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
    // The workbook columns (NAZIV and PIB separate), ending with "PB-1,PB-2 za rad".
    const visible = withoutColumnAfterLast(columns);
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
      // Empty cells: 0 from "kom" on, "-" in the columns left of it (display only).
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
        title={home ? `Excel row ${row.row}` : undefined}
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
            emptyPlaceholder={plan.placeholderColumns.has(column.key) ? EMPTY_TEXT_PLACEHOLDER : undefined}
            allowText={!home}
            textRule={isNameColumn ? "name" : column.key === pibColumn ? "pib" : undefined}
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
}: {
  data: CompanyTableData;
  onCommit: CommitCell;
  year: number;
  variant?: TableVariant;
}) {
  // The API returns only the company list (165 rows for 2025), in order.
  const { columns, rows } = data;
  const plan = useMemo(() => planColumns(columns, variant), [columns, variant]);
  const registry = variant === "registry";

  return (
    // Registry: fixed column widths, so the table always fits the screen (no horizontal scroll).
    <div
      className={cn(
        "max-h-[calc(100svh-12rem)] rounded-md border",
        registry ? "overflow-x-hidden overflow-y-auto" : "overflow-auto",
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
          <TableRow className="hover:bg-transparent">
            <TableHead
              title={registry ? undefined : "Number in the company list"}
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
                title={registry ? undefined : `Column ${column.key}`}
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
          {rows.map((row, index) => (
            <DataRow key={row.row} row={row} number={index + 1} plan={plan} onCommit={onCommit} year={year} />
          ))}
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
