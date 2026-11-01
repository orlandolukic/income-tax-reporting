import { memo, useState, type KeyboardEvent } from "react";
import { Link } from "react-router";
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

// Hover preview opens to the left for the last columns so it stays inside the table.
const RIGHT_ANCHORED_COLUMNS = 3;
// Company names (this column) link to the company's PB-1 page.
const NAME_HEADER = "NAZIV";

export type CommitCell = (row: number, column: string, value: number | null) => void;

function formatValue(value: CellValue, format: string | undefined): { text: string; red: boolean } {
  if (value === null) return { text: "", red: false };
  if (typeof value === "number") return formatNumber(value, format);
  if (typeof value === "boolean") return { text: value ? "TRUE" : "FALSE", red: false };
  return { text: value, red: false };
}

function cellTitle(cell: CompanyCell): string | undefined {
  if (cell.formula) return "Formula (read-only)";
  if (cell.edited) {
    const original = formatValue(originalValue(cell), cell.format).text || "empty";
    return `Changed. Excel value: ${original}`;
  }
  if (cell.editable) return "Click to edit";
  return undefined;
}

function CellEditor({
  cell,
  onDone,
}: {
  cell: CompanyCell;
  onDone: (value: number | null | undefined) => void;
}) {
  const current = typeof cell.value === "number" ? cell.value : null;
  const [text, setText] = useState(toEditText(current));
  const [invalid, setInvalid] = useState(false);

  // undefined = cancel (keep the current value)
  const finish = (commit: boolean) => {
    if (!commit) return onDone(undefined);
    const parsed = parseNumberInput(text);
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
      inputMode="decimal"
      aria-label="Cell value"
      aria-invalid={invalid || undefined}
      title={invalid ? "Enter a number, e.g. 1234,56" : undefined}
      value={text}
      onFocus={(e) => e.currentTarget.select()}
      onChange={(e) => {
        setText(e.target.value);
        setInvalid(false);
      }}
      onKeyDown={onKeyDown}
      // Leaving the field saves a valid number and discards invalid input.
      onBlur={() => (parseNumberInput(text) === undefined ? finish(false) : finish(true))}
      className="border-ring ring-ring/50 bg-background aria-invalid:border-destructive aria-invalid:ring-destructive/20 -my-1 h-7 w-full min-w-20 rounded-sm border px-1.5 text-end tabular-nums ring-[3px] outline-none"
    />
  );
}

function DataCell({
  cell,
  alignEnd,
  onCommit,
  href,
}: {
  cell: CompanyCell;
  alignEnd: boolean;
  onCommit: (value: number | null) => void;
  href?: string;
}) {
  const [editing, setEditing] = useState(false);
  const value = cell.value ?? null;
  const { text, red } = formatValue(value, cell.format);
  const isNumber = typeof value === "number" || (cell.editable && value === null);

  const startEditing = () => {
    if (cell.editable) setEditing(true);
  };

  return (
    <TableCell
      title={editing ? undefined : cellTitle(cell)}
      tabIndex={cell.editable ? 0 : undefined}
      onClick={editing ? undefined : startEditing}
      onKeyDown={(e) => {
        if (!editing && (e.key === "Enter" || e.key === "F2")) {
          e.preventDefault();
          startEditing();
        }
      }}
      className={cn(
        "group/cell hover:bg-accent hover:text-accent-foreground relative max-w-64 transition-colors",
        isNumber && "text-end tabular-nums",
        red && "text-destructive hover:text-destructive",
        cell.editable && "focus-visible:ring-ring/50 cursor-text outline-none focus-visible:ring-[3px] focus-visible:ring-inset",
        // Edited cells: small corner marker, like Excel's comment indicator.
        cell.edited &&
          "after:border-t-primary after:border-r-primary after:absolute after:top-0 after:right-0 after:border-4 after:border-b-transparent after:border-l-transparent",
      )}
    >
      {editing ? (
        <CellEditor
          cell={cell}
          onDone={(newValue) => {
            setEditing(false);
            if (newValue !== undefined && newValue !== value) onCommit(newValue);
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
            <span className="block truncate">{text}</span>
          )}
          {text.trim() !== "" && (
            // Enlarged preview of the full value, shown while hovering the cell.
            <span
              className={cn(
                "bg-popover text-popover-foreground pointer-events-none absolute top-1/2 z-30 hidden w-max max-w-sm -translate-y-1/2 rounded-md border px-3 py-1.5 text-base font-medium break-words whitespace-normal shadow-md group-hover/cell:block",
                alignEnd ? "right-0" : "left-0",
                isNumber && "tabular-nums",
                red && "text-destructive",
              )}
            >
              {text}
            </span>
          )}
        </>
      )}
    </TableCell>
  );
}

// Memoized so editing one cell re-renders only its row.
const DataRow = memo(function DataRow({
  row,
  columns,
  onCommit,
  year,
  nameColumn,
}: {
  row: CompanyRow;
  columns: CompanyColumn[];
  onCommit: CommitCell;
  year: number;
  nameColumn: string | undefined;
}) {
  return (
    <TableRow>
      {/* Excel row number, like Excel's row gutter. */}
      <TableCell className="bg-background text-muted-foreground sticky left-0 z-10 w-12 text-end text-xs tabular-nums shadow-[inset_-1px_0_var(--border)]">
        {row.row}
      </TableCell>
      {columns.map((column, index) => {
        const cell = row.cells[column.key] ?? {};
        const isCompanyName =
          column.key === nameColumn && typeof cell.value === "string" && cell.value.trim() !== "";
        return (
          <DataCell
            key={column.key}
            cell={cell}
            alignEnd={index >= columns.length - RIGHT_ANCHORED_COLUMNS}
            onCommit={(value) => onCommit(row.row, column.key, value)}
            href={isCompanyName ? `/companies/${year}/${row.row}/pb1` : undefined}
          />
        );
      })}
    </TableRow>
  );
});

export function CompanyTable({
  data,
  onCommit,
  year,
}: {
  data: CompanyTableData;
  onCommit: CommitCell;
  year: number;
}) {
  const { columns, rows } = data;
  const nameColumn = columns.find((c) => c.header?.trim().toUpperCase() === NAME_HEADER)?.key;

  return (
    <div className="max-h-[calc(100svh-12rem)] overflow-auto rounded-md border">
      <table className="w-full caption-bottom text-sm">
        <TableHeader className="bg-muted sticky top-0 z-20 [&_tr]:border-b-0 shadow-[inset_0_-1px_0_var(--border)]">
          <TableRow className="hover:bg-transparent">
            <TableHead className="bg-muted text-muted-foreground sticky left-0 z-10 w-12 text-end shadow-[inset_-1px_0_var(--border)]">
              #
            </TableHead>
            {columns.map((column) => (
              <TableHead key={column.key} className="whitespace-pre" title={`Column ${column.key}`}>
                {column.header ?? ""}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <DataRow
              key={row.row}
              row={row}
              columns={columns}
              onCommit={onCommit}
              year={year}
              nameColumn={nameColumn}
            />
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
