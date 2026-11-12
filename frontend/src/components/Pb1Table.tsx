import { type CSSProperties, type KeyboardEvent, type ReactNode, type RefObject, useLayoutEffect, useRef, useState } from "react";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Pb1Cell, Pb1Column, Pb1Commit, Pb1Data, Pb1Row } from "@/hooks/use-pb1";
import { formatNumber, parseNumberInput, toEditText, withDecimals } from "@/lib/excel-format";
import { cn } from "@/lib/utils";

// Amounts in every PB-1 tab are shown with exactly two decimals.
const AMOUNT_DECIMALS = 2;

// Vertical column border; an inset shadow, so it stays visible on the sticky header.
const COLUMN_BORDER = "not-last:shadow-[inset_-1px_0_var(--border)]";

type Display = { text: string; red: boolean; isNumber: boolean };

// Excel fill color of a cell (data from the sheet, not a theme color): as in Excel in the light
// theme; mixed into the background in the dark theme so the text stays readable.
const FILL = "bg-(--cell-fill) dark:bg-[color-mix(in_oklab,var(--cell-fill)_25%,var(--background))]";

// Any letter (also č, ć, ž, š, đ): the text is a comment in words, not a number.
const LETTER = /\p{L}/u;

function display(cell: Pb1Cell): Display {
  const value = cell.value ?? null;
  if (cell.amount) {
    // Amount field: its number with two decimals; 0 when it has none (empty, " ", #DIV/0!,
    // or another company's form, which carries no amounts).
    const amount = typeof value === "number" ? value : 0;
    return { ...formatNumber(amount, withDecimals(cell.format, AMOUNT_DECIMALS)), isNumber: true };
  }
  if (value === null) return { text: "", red: false, isNumber: false };
  if (typeof value === "number") return { ...formatNumber(value, cell.format), isNumber: true };
  if (typeof value === "boolean") return { text: value ? "TRUE" : "FALSE", red: false, isNumber: false };
  return { text: value, red: false, isNumber: false };
}

/** Column width from the Excel sheet (characters); line-number columns fit their numbers. */
function columnWidth(column: Pb1Column): string {
  // "1%": the line-number column shrinks to its numbers; the other columns take the rest.
  return column.narrow ? "1%" : `${column.width + 2}ch`;
}

/**
 * How many columns a cell covers. A text longer than its line-number column (a section
 * heading in Preliminarni rezultat) overflows into the empty cells to its right, as in Excel.
 */
function spanOf(cells: Record<string, Pb1Cell>, columns: Pb1Column[], index: number, text: string): number {
  const column = columns[index];
  if (!column.narrow || text.length <= column.width) return 1;
  let span = 1;
  while (index + span < columns.length) {
    const next = cells[columns[index + span].key] ?? {};
    if (next.amount || display(next).text.trim() !== "") break;
    span++;
  }
  return span;
}

/**
 * Inline editor of one field: a number (amounts, numeric template fields) or a text
 * (descriptions, comments). Enter or leaving the field saves, Escape cancels.
 */
function FieldEditor({
  cell,
  alignEnd,
  onDone,
}: {
  cell: Pb1Cell;
  alignEnd: boolean;
  onDone: (value: number | string | null | undefined) => void; // undefined = cancel
}) {
  const isNumber = Boolean(cell.number);
  // A percent (a rate such as 5,00%) is typed as percent: "5" or "5%" is 0.05.
  const percent = isNumber && (cell.format ?? "").includes("%");
  const [text, setText] = useState(() =>
    isNumber
      ? typeof cell.value === "number"
        ? toEditText(percent ? Number((cell.value * 100).toFixed(10)) : cell.value) + (percent ? "%" : "")
        : ""
      : typeof cell.value === "string" || typeof cell.value === "number"
        ? String(cell.value)
        : "",
  );
  const [invalid, setInvalid] = useState(false);
  // Numbers: Serbian or plain input (1.234,56 / 1234.56); empty clears. Text: empty clears.
  const parse = (input: string) => {
    if (!isNumber) return input.trim() === "" ? null : input.trim();
    const number = parseNumberInput(percent ? input.replace("%", "") : input);
    return percent && typeof number === "number" ? Number((number / 100).toPrecision(12)) : number;
  };

  const finish = (commit: boolean) => {
    if (!commit) return onDone(undefined);
    const parsed = parse(text);
    if (parsed === undefined) {
      setInvalid(true);
      return;
    }
    onDone(parsed);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      finish(true);
    }
    if (e.key === "Escape") finish(false);
  };
  const common = {
    autoFocus: true,
    "aria-label": "Field value",
    "aria-invalid": invalid || undefined,
    title: invalid ? "Enter a number, e.g. 1.234,56" : undefined,
    value: text,
    onKeyDown,
    // Leaving the field saves a valid value and discards invalid input.
    onBlur: () => finish(parse(text) !== undefined),
    className: cn(
      "border-ring ring-ring/50 bg-background aria-invalid:border-destructive aria-invalid:ring-destructive/20 w-full min-w-0 rounded-sm border px-1.5 py-0.5 font-normal ring-[3px] outline-none",
      alignEnd ? "text-end tabular-nums" : "text-start",
    ),
  };
  if (isNumber) {
    return (
      <input
        {...common}
        inputMode="decimal"
        onFocus={(e) => e.currentTarget.select()}
        onChange={(e) => {
          setText(e.target.value);
          setInvalid(false);
        }}
      />
    );
  }
  return (
    <textarea
      {...common}
      rows={Math.min(6, Math.max(1, Math.ceil(text.length / 45)))}
      className={cn(common.className, "resize-none")}
      onChange={(e) => {
        setText(e.target.value);
        setInvalid(false);
      }}
    />
  );
}

/** The field's value as its editor sees it: a number or null, a trimmed text or null. */
function editValue(cell: Pb1Cell): number | string | null {
  const value = cell.value ?? null;
  if (cell.number) return typeof value === "number" ? value : null;
  return typeof value === "string" ? value.trim() || null : typeof value === "number" ? String(value) : null;
}

/** One field of the form. Editable fields open an editor on click (or Enter / F2). */
function FieldCell({
  cell,
  column,
  span,
  onCommit,
}: {
  cell: Pb1Cell;
  column: Pb1Column;
  span: number;
  onCommit: (value: number | string | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const { text, red, isNumber } = display(cell);
  const canEdit = Boolean(cell.editable);
  // Numbers written as text (konto lists such as "57, 58"): no words.
  const numericText = !isNumber && text.trim() !== "" && !LETTER.test(text);
  // Accounting rule: numbers (amounts, konto, line numbers) right, comments in words left.
  // Amount and line-number columns are right-aligned; overflowing headings are not.
  const alignEnd = span === 1 && (isNumber || numericText || Boolean(column.amount) || Boolean(column.narrow));
  const startEditing = () => {
    if (canEdit) setEditing(true);
  };

  return (
    <TableCell
      colSpan={span > 1 ? span : undefined}
      // Fill color from the sheet (head rows): data, passed as a variable; see FILL below.
      style={cell.fill ? ({ "--cell-fill": cell.fill } as CSSProperties) : undefined}
      tabIndex={canEdit && !editing ? 0 : undefined}
      onClick={editing ? undefined : startEditing}
      onKeyDown={(e) => {
        if (!editing && (e.key === "Enter" || e.key === "F2")) {
          e.preventDefault();
          startEditing();
        }
      }}
      className={cn(
        // The PB-1 tables don't react to the mouse (no highlight, no preview); a click edits.
        "relative align-top",
        COLUMN_BORDER,
        isNumber ? "tabular-nums" : "break-words whitespace-normal",
        numericText && "tabular-nums",
        column.narrow && "px-1.5",
        column.narrow && span === 1 && "text-muted-foreground text-xs",
        alignEnd && "text-end",
        cell.bold && "font-semibold",
        red && "text-destructive",
        cell.fill && FILL,
        canEdit && "focus-visible:ring-ring/50 outline-none focus-visible:ring-[3px] focus-visible:ring-inset",
        editing && "py-1",
        // Changed in the app: small corner marker, like Excel's comment indicator.
        cell.edited &&
          "after:border-t-primary after:border-r-primary after:absolute after:top-0 after:right-0 after:border-4 after:border-b-transparent after:border-l-transparent",
      )}
    >
      {editing ? (
        <FieldEditor
          cell={cell}
          alignEnd={alignEnd}
          onDone={(value) => {
            setEditing(false);
            // Nothing changed (e.g. an amount shown as 0,00 over " " left empty): nothing to save.
            if (value !== undefined && value !== editValue(cell)) onCommit(value);
          }}
        />
      ) : (
        text
      )}
    </TableCell>
  );
}

/** One form row; cells of a long text in a line-number column span the empty cells after it. */
function Pb1RowView({ row, columns, onCommit }: { row: Pb1Row; columns: Pb1Column[]; onCommit: Pb1Commit }) {
  const cells: ReactNode[] = [];
  for (let index = 0; index < columns.length; index++) {
    const column = columns[index];
    const cell = row.cells[column.key] ?? {};
    const span = spanOf(row.cells, columns, index, display(cell).text);
    cells.push(
      <FieldCell
        key={column.key}
        cell={cell}
        column={column}
        span={span}
        onCommit={(value) => onCommit(row.row, column.key, value)}
      />,
    );
    index += span - 1;
  }
  // Section rows (bold description) are shaded to separate the sections.
  return <TableRow className={cn("hover:bg-transparent", row.shaded && "bg-muted/60 hover:bg-muted/60")}>{cells}</TableRow>;
}

/**
 * Column widths of the rendered form table in pixels, so the summary table below it lines up
 * column by column. Measured from the header row (or a body row without merged cells) and
 * kept up to date when the table is resized.
 */
function useColumnWidths(tableRef: RefObject<HTMLTableElement | null>, columnCount: number, enabled: boolean) {
  const [widths, setWidths] = useState<{ table: number; columns: number[] } | null>(null);
  useLayoutEffect(() => {
    const table = tableRef.current;
    if (!enabled || !table) return;
    const measure = () => {
      const row = [...table.rows].find((r) => r.cells.length === columnCount);
      if (!row) return;
      const columns = [...row.cells].map((c) => c.getBoundingClientRect().width);
      const width = table.getBoundingClientRect().width;
      setWidths((prev) =>
        prev && prev.table === width && prev.columns.every((w, i) => w === columns[i]) ? prev : { table: width, columns },
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(table);
    return () => observer.disconnect();
  }, [tableRef, columnCount, enabled]);
  return widths;
}

/**
 * PB-1 form table: original columns, row order and bold styling; nothing is truncated.
 * Every field except the line numbers can be edited (amounts for this company, template
 * fields for every company).
 */
export function Pb1Table({ data, onCommit }: { data: Pb1Data; onCommit: Pb1Commit }) {
  const { columns, rows } = data;
  const head = data.head ?? [];
  const headColumns = data.head_columns?.length === columns.length ? data.head_columns : columns;
  const summary = data.summary ?? [];
  // Some sheets (Preliminarni rezultat) have no header row.
  const hasHeader = columns.some((c) => c.header !== null && c.header !== undefined);
  const tableRef = useRef<HTMLTableElement>(null);
  const widths = useColumnWidths(tableRef, columns.length, head.length > 0 || summary.length > 0);

  return (
    <>
      {head.length > 0 && (
        // The sheet's first rows (Poreski bilans: title, company name, class 5/6 totals) as a
        // separate table above the form, with the same columns.
        // Its empty first and last columns (# and Konto) are left out; the other columns keep
        // their widths and positions.
        // Its own columns (with the comment column's head cells), one to one with the form's.
        <AlignedTable
          rows={head}
          columns={headColumns}
          range={usedColumns(head, headColumns)}
          widths={widths}
          onCommit={onCommit}
          className="mb-4"
        />
      )}

      <div className="max-h-[calc(100svh-16rem)] overflow-auto rounded-md border">
        <table ref={tableRef} className="w-full caption-bottom text-sm">
          <colgroup>
            {columns.map((column) => (
              <col key={column.key} style={{ width: columnWidth(column) }} />
            ))}
          </colgroup>
          {hasHeader && (
            <TableHeader className="bg-muted sticky top-0 z-20 [&_tr]:border-b-0 shadow-[inset_0_-1px_0_var(--border)]">
              <TableRow className="hover:bg-transparent">
                {columns.map((column) => (
                  <TableHead
                    key={column.key}
                    // Headers on one line, aligned left (the column is at least as wide as its header).
                    className={cn("h-auto py-2 align-bottom whitespace-nowrap", column.narrow && "px-1.5", COLUMN_BORDER)}
                  >
                    {column.header ?? ""}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
          )}
          <TableBody>
            {rows.map((row) => (
              <Pb1RowView key={row.row} row={row} columns={columns} onCommit={onCommit} />
            ))}
          </TableBody>
        </table>
      </div>

      {summary.length > 0 && (
        // The form's closing rows (Poreski bilans: Poreska osnovica, Porez 15%, Mesecna akontacija)
        // as a separate table below it, with the same columns.
        <AlignedTable rows={summary} columns={columns} widths={widths} onCommit={onCommit} className="mt-4" />
      )}
    </>
  );
}

type ColumnRange = { start: number; end: number }; // column indexes, end exclusive

const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);

/** The columns from the first to the last one with any content (value, amount field or fill). */
function usedColumns(rows: Pb1Row[], columns: Pb1Column[]): ColumnRange {
  const used = (index: number) =>
    rows.some((r) => {
      const cell = r.cells[columns[index].key];
      return cell && (cell.amount || cell.fill || display(cell).text.trim() !== "");
    });
  let start = 0;
  let end = columns.length;
  while (end > 1 && !used(end - 1)) end--;
  while (start < end - 1 && !used(start)) start++;
  return { start, end };
}

/**
 * A separate table of form rows whose columns line up with the form table (widths measured
 * from it). With a `range` of the form's columns, the columns left out at the start and end
 * are not drawn: the table is narrower by their width and moved right by the width of those
 * at the start, so every remaining column stays above its own.
 */
function AlignedTable({
  rows,
  columns,
  range,
  widths,
  onCommit,
  className,
}: {
  rows: Pb1Row[];
  columns: Pb1Column[];
  range?: ColumnRange;
  widths: { table: number; columns: number[] } | null;
  onCommit: Pb1Commit;
  className?: string;
}) {
  const { start, end } = range ?? { start: 0, end: columns.length };
  const shown = columns.slice(start, end);
  const full = start === 0 && end === columns.length;
  const style: CSSProperties | undefined = widths
    ? {
        width: full ? widths.table : sum(widths.columns.slice(start, end)),
        marginLeft: start > 0 ? sum(widths.columns.slice(0, start)) : undefined,
      }
    : undefined;
  return (
    <div
      className={cn("max-w-full overflow-x-auto rounded-md border", !full && "w-fit", className)}
      style={widths && start > 0 ? { marginLeft: style?.marginLeft } : undefined}
    >
      <table
        className={cn("caption-bottom text-sm", widths ? "table-fixed" : "w-full")}
        style={widths ? { width: style?.width } : undefined}
      >
        <colgroup>
          {shown.map((column, i) => (
            <col key={column.key} style={{ width: widths ? widths.columns[start + i] : columnWidth(column) }} />
          ))}
        </colgroup>
        <TableBody>
          {rows.map((row) => (
            <Pb1RowView key={row.row} row={row} columns={shown} onCommit={onCommit} />
          ))}
        </TableBody>
      </table>
    </div>
  );
}

/**
 * The form's comments (column "Komentar, stopa, konto") beside the table: one pair of
 * description and comment per row. A click edits the comment; it is saved for this company
 * only. Rates (5,00%, ...) are numbers and are used by the formulas.
 */
export function Pb1Comments({ data, onCommit }: { data: Pb1Data; onCommit: Pb1Commit }) {
  const column = data.comment_column;
  if (!column) return null;
  const items = [...data.rows, ...(data.summary ?? [])].filter((row) => {
    const description = row.cells.B?.value;
    return typeof description === "string" && description.trim() !== "";
  });
  return (
    <div className="flex max-h-[calc(100svh-16rem)] flex-col rounded-md border">
      <div className="bg-muted border-b px-3 py-2 text-sm font-medium">Komentari</div>
      <ul className="overflow-auto text-sm">
        {items.map((row) => (
          <CommentItem
            key={row.row}
            row={row}
            cell={row.cells[column] ?? {}}
            onCommit={(value) => onCommit(row.row, column, value)}
          />
        ))}
      </ul>
    </div>
  );
}

function CommentItem({
  row,
  cell,
  onCommit,
}: {
  row: Pb1Row;
  cell: Pb1Cell;
  onCommit: (value: number | string | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const number = row.cells.A?.value;
  const description = String(row.cells.B?.value ?? "");
  const { text, isNumber } = display(cell);
  const canEdit = Boolean(cell.editable);
  const startEditing = () => {
    if (canEdit) setEditing(true);
  };
  return (
    <li
      // No reaction to the mouse (like the tables); a click edits the comment.
      tabIndex={canEdit && !editing ? 0 : undefined}
      onClick={editing ? undefined : startEditing}
      onKeyDown={(e) => {
        if (!editing && (e.key === "Enter" || e.key === "F2")) {
          e.preventDefault();
          startEditing();
        }
      }}
      className={cn(
        "relative border-b px-3 py-2 last:border-b-0",
        row.shaded && "bg-muted/60",
        canEdit && "focus-visible:ring-ring/50 outline-none focus-visible:ring-[3px] focus-visible:ring-inset",
        // Changed for this company: small corner marker, like in the tables.
        cell.edited &&
          "after:border-t-primary after:border-r-primary after:absolute after:top-0 after:right-0 after:border-4 after:border-b-transparent after:border-l-transparent",
      )}
    >
      <div className={cn("text-muted-foreground text-xs break-words", row.shaded && "font-semibold")}>
        {number !== null && number !== undefined && number !== "" && <span className="tabular-nums">{String(number)} · </span>}
        {description}
      </div>
      <div className="mt-1">
        {editing ? (
          <FieldEditor
            cell={cell}
            alignEnd={false}
            onDone={(value) => {
              setEditing(false);
              if (value !== undefined && value !== editValue(cell)) onCommit(value);
            }}
          />
        ) : text.trim() !== "" ? (
          <span className={cn("break-words", isNumber && "tabular-nums")}>{text}</span>
        ) : (
          <span className="text-muted-foreground">-</span>
        )}
      </div>
    </li>
  );
}
