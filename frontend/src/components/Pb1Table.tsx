import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Pb1Cell, Pb1Data } from "@/hooks/use-pb1";
import { formatNumber } from "@/lib/excel-format";
import { cn } from "@/lib/utils";

// Column B (description) wraps like in the Excel form; the others stay on one line.
const WRAPPING_COLUMN = "B";

function display(cell: Pb1Cell): { text: string; red: boolean; isNumber: boolean } {
  const value = cell.value ?? null;
  if (value === null) return { text: "", red: false, isNumber: false };
  if (typeof value === "number") return { ...formatNumber(value, cell.format), isNumber: true };
  if (typeof value === "boolean") return { text: value ? "TRUE" : "FALSE", red: false, isNumber: false };
  return { text: value, red: false, isNumber: false };
}

/** Read-only PB-1 table: original header, columns, row order and bold styling. */
export function Pb1Table({ data }: { data: Pb1Data }) {
  const { columns, rows } = data;

  return (
    <div className="max-h-[calc(100svh-16rem)] overflow-auto rounded-md border">
      <table className="w-full caption-bottom text-sm">
        <TableHeader className="bg-muted sticky top-0 z-20 [&_tr]:border-b-0 shadow-[inset_0_-1px_0_var(--border)]">
          <TableRow className="hover:bg-transparent">
            {columns.map((column) => (
              <TableHead
                key={column.key}
                // Column widths follow the Excel sheet (in characters).
                style={{ width: `${column.width + 2}ch`, minWidth: `${Math.min(column.width + 2, 12)}ch` }}
                className="whitespace-normal"
                title={`Column ${column.key}`}
              >
                {column.header ?? ""}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.row}>
              {columns.map((column, index) => {
                const cell = row.cells[column.key] ?? {};
                const { text, red, isNumber } = display(cell);
                const wraps = column.key === WRAPPING_COLUMN;
                return (
                  <TableCell
                    key={column.key}
                    className={cn(
                      "group/cell hover:bg-accent hover:text-accent-foreground relative align-top transition-colors",
                      wraps ? "whitespace-normal" : "max-w-64",
                      isNumber && "text-end tabular-nums",
                      cell.bold && "font-semibold",
                      red && "text-destructive hover:text-destructive",
                    )}
                  >
                    <span className={cn("block", !wraps && "truncate")}>{text}</span>
                    {!wraps && text.trim() !== "" && (
                      // Enlarged preview of the full value, shown while hovering the cell.
                      <span
                        className={cn(
                          "bg-popover text-popover-foreground pointer-events-none absolute top-1/2 z-30 hidden w-max max-w-sm -translate-y-1/2 rounded-md border px-3 py-1.5 text-base font-medium break-words whitespace-normal shadow-md group-hover/cell:block",
                          index >= columns.length - 3 ? "right-0" : "left-0",
                          isNumber && "tabular-nums",
                          red && "text-destructive",
                        )}
                      >
                        {text}
                      </span>
                    )}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </table>
    </div>
  );
}
