import { createPortal } from "react-dom";
import { type CSSProperties, type KeyboardEvent, type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CalendarClock, Landmark, Percent, Scale } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Pb1Cell, Pb1Column, Pb1Commit, Pb1Data, Pb1HeadFigure, Pb1Result, Pb1Row } from "@/hooks/use-pb1";
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

/**
 * A number as shown: every negative number is red and has its minus sign, whatever its format
 * (user, 2026-11-17: a clear mark of a loss, on all three tabs, inputs and formulas alike).
 */
function shownNumber(value: number, format: string | null | undefined): Display {
  const { text } = formatNumber(value, format);
  if (value >= 0) return { text, red: false, isNumber: true };
  const signed = /[-(]/.test(text) ? text : `-${text}`;
  return { text: signed, red: true, isNumber: true };
}

export function display(cell: Pb1Cell): Display {
  const value = cell.value ?? null;
  if (cell.amount) {
    // Amount field: its number with two decimals; 0 when it has none (empty, " ", #DIV/0!,
    // or another company's form, which carries no amounts).
    const amount = typeof value === "number" ? value : 0;
    return shownNumber(amount, withDecimals(cell.format, AMOUNT_DECIMALS));
  }
  if (value === null) return { text: "", red: false, isNumber: false };
  if (typeof value === "number") return shownNumber(value, cell.format);
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
// Invalid input (as on Home): a character that isn't allowed is not typed in and the border
// flashes red; a value that isn't valid on Enter / leaving the field shows a red border, then
// the field goes back to its old value.
const INVALID_FLASH_MS = 600;
const INVALID_REVERT_MS = 900;
// Characters a number may hold while typing (Serbian or plain notation, a sign, spaces).
const NUMBER_CHARS = /^[-+\d.,\s]*$/;

function FieldEditor({
  cell,
  alignEnd,
  dashEmpty,
  overlay,
  onDone,
}: {
  cell: Pb1Cell;
  alignEnd: boolean;
  dashEmpty?: boolean; // "-" means empty (Konto)
  // The editor floats over the cell, as wide as the value being typed (at least the cell), anchored
  // at the cell's right edge, so the whole value is in sight and nothing around moves (Klasa 5 / 6
  // in the strip, user 2026-11-25).
  overlay?: boolean;
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
  const [reverting, setReverting] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  // Numbers: Serbian or plain input (1.234,56 / 1234.56); empty clears; amounts are rounded to
  // two decimals. Text: empty (or "-" where it means empty) clears.
  const parse = (input: string) => {
    if (!isNumber) {
      const value = input.trim();
      return value === "" || (dashEmpty && value === "-") ? null : value;
    }
    const number = parseNumberInput(percent ? input.replace("%", "") : input);
    if (typeof number !== "number") return number;
    if (percent) return Number((number / 100).toPrecision(12));
    return cell.amount ? Math.round(number * 100) / 100 : number;
  };

  const finish = (commit: boolean) => {
    if (reverting) return;
    if (!commit) return onDone(undefined);
    const parsed = parse(text);
    if (parsed === undefined) {
      // Not a valid value: red border, then the old value comes back.
      setInvalid(true);
      setReverting(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => onDone(undefined), INVALID_REVERT_MS);
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
    "aria-label": "Vrednost polja",
    "aria-invalid": invalid || undefined,
    title: invalid ? "Unesite broj, npr. 1.234,56" : undefined,
    value: text,
    readOnly: reverting,
    onKeyDown,
    // Leaving the field saves a valid value; invalid input turns the border red and is discarded.
    onBlur: () => finish(true),
    className: cn(
      "border-ring ring-ring/50 bg-background aria-invalid:border-destructive aria-invalid:ring-destructive/20 w-full min-w-0 rounded-sm border px-1.5 py-0.5 font-normal ring-[3px] outline-none",
      alignEnd ? "text-end tabular-nums" : "text-start",
      overlay && "absolute top-1/2 right-0 z-20 min-w-full -translate-y-1/2 shadow-md",
    ),
    style: overlay ? { width: `${Math.max(text.length + 3, 10)}ch` } : undefined,
  };
  if (isNumber) {
    return (
      <input
        {...common}
        // size / cols 1: no built-in width (about 20 characters by default), so the field takes
        // the cell's width and opening it never widens a table sized by its content (the
        // closing-rows box, user 2026-11-16).
        size={1}
        inputMode="decimal"
        onFocus={(e) => e.currentTarget.select()}
        onChange={(e) => {
          const next = e.target.value;
          window.clearTimeout(timer.current);
          if (!NUMBER_CHARS.test(percent ? next.replace("%", "") : next)) {
            // A letter or other character a number can't hold: not typed in, a short red flash.
            setInvalid(true);
            timer.current = window.setTimeout(() => setInvalid(false), INVALID_FLASH_MS);
            return;
          }
          setText(next);
          setInvalid(false);
        }}
      />
    );
  }
  return (
    <textarea
      {...common}
      rows={Math.min(6, Math.max(1, Math.ceil(text.length / 45)))}
      cols={1}
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

/**
 * One field of the form. Editable fields open an editor on click (or Enter / F2). Used by the
 * Poreski bilans tables and by the styled Uporedo / Preliminarni views (Pb1Styled), so editing
 * is the same everywhere; `adornment` (e.g. a trend marker) and `className` only add looks.
 */
export function FieldCell({
  cell,
  column,
  span = 1,
  rowSpan = 1,
  onCommit,
  adornment,
  className,
  wideEditor,
}: {
  cell: Pb1Cell;
  column: Pb1Column;
  span?: number;
  // Rows the cell covers downwards (the head's company name over the empty cells below it).
  rowSpan?: number;
  onCommit: (value: number | string | null) => void;
  adornment?: ReactNode;
  className?: string;
  wideEditor?: boolean; // the editor floats over the cell, as wide as the value (FieldEditor overlay)
}) {
  const [editing, setEditing] = useState(false);
  const shown = display(cell);
  const { text, isNumber } = shown;
  // Prekoracenje column (user, 2026-11-17): an overrun (> 0) red, or green on a line with "-" in
  // the line 59 formula (user, 2026-11-25); it is never negative (0 when Ostvareni <= Priznati,
  // user 2026-11-22). Elsewhere every negative number red. Computed from the value, so it follows
  // the recomputed formulas at once.
  // A section's subtotal (shaded Roman-numeral rows, on a soft brand background, user 2026-11-25):
  // above 0 red, below 0 green with its minus sign (the supervisor's rule).
  const subtotal = Boolean(cell.subtotal);
  const number = typeof cell.value === "number" ? cell.value : 0;
  const overrun = Boolean(column.overrun) && !subtotal && number > 0;
  // Klasa 5 / Klasa 6 (user, 2026-11-25): expenses red, revenue green, without a sign; the
  // Saldo (Klasa 6 - 5) by its sign: a profit green, a loss red with its minus.
  const green =
    cell.tone === "balance"
      ? number > 0
      : cell.tone
        ? cell.tone === "income"
        : subtotal
          ? number < 0
          : overrun && Boolean(cell.minus);
  const red =
    cell.tone === "balance"
      ? number < 0
      : cell.tone
        ? cell.tone === "expense"
        : subtotal
          ? number > 0
          : (overrun && !green) || shown.red;
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
      rowSpan={rowSpan > 1 ? rowSpan : undefined}
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
        rowSpan > 1 && "align-middle", // a cell over several rows (company name): centred vertically
        COLUMN_BORDER,
        isNumber ? "tabular-nums" : "break-words whitespace-normal",
        numericText && "tabular-nums",
        column.narrow && "px-1.5",
        column.narrow && span === 1 && "text-muted-foreground text-xs",
        alignEnd && "text-end",
        cell.bold && "font-semibold",
        red && "text-destructive",
        green && "text-success",
        subtotal && "bg-brand/15",
        // A fixed, computed value (formula; not editable) on all three tabs: hatched grey (user,
        // 2026-11-25). Not the subtotals (own background) nor the head cells with a sheet fill.
        cell.formula && !subtotal && !cell.fill && "bg-locked",
        cell.fill && FILL,
        canEdit && "focus-visible:ring-ring/50 outline-none focus-visible:ring-[3px] focus-visible:ring-inset",
        // Clickable (opens the editor): pointing hand, as everything clickable in the app.
        canEdit && !editing && "cursor-pointer",
        editing && "py-1",
        // Changed in the app: small corner marker, like Excel's comment indicator.
        cell.edited &&
          "after:border-t-primary after:border-r-primary after:absolute after:top-0 after:right-0 after:border-4 after:border-b-transparent after:border-l-transparent",
        className,
      )}
    >
      {editing && wideEditor && <span className="invisible">{text}</span>}
      {editing ? (
        <FieldEditor
          cell={cell}
          alignEnd={alignEnd}
          dashEmpty={column.dash_empty}
          overlay={wideEditor}
          onDone={(value) => {
            setEditing(false);
            // Nothing changed (e.g. an amount shown as 0,00 over " " left empty): nothing to save.
            if (value !== undefined && value !== editValue(cell)) onCommit(value);
          }}
        />
      ) : adornment ? (
        // The adornment at the cell's left edge, so the markers of every row line up; the value right.
        <span className="flex w-full items-center justify-between gap-2">
          {adornment}
          <span>{text}</span>
        </span>
      ) : column.dash_empty && canEdit && text.trim() === "" ? (
        // An empty editable field shown as "-" (Konto, user 2026-11-16); a locked cell (e.g. in a
        // section row) stays empty.
        <span className="text-muted-foreground">-</span>
      ) : (
        text
      )}
    </TableCell>
  );
}

/** A row's global comment as shown (rates formatted), or "" when it has none ("-" counts as none). */
export function commentText(row: Pb1Row, commentColumn: string | undefined): string {
  const cell = commentColumn ? row.cells[commentColumn] : undefined;
  const text = cell ? display(cell).text.trim() : "";
  return text === "-" ? "" : text;
}

/** One form row; cells of a long text in a line-number column span the empty cells after it. */
/** Rows found by the header search (PB-1 Poreski bilans): all matches, and the one in focus. */
export type Pb1SearchMarks = { rows: Set<number>; current: number | null };

/** Row background of a search match (light) and of the match in focus (stronger). */
function markClass(row: Pb1Row, marks?: Pb1SearchMarks): string | false {
  if (!marks?.rows.has(row.row)) return false;
  return marks.current === row.row ? "bg-brand-accent/45 hover:bg-brand-accent/45" : "bg-brand-accent/15 hover:bg-brand-accent/15";
}

function Pb1RowView({
  row,
  columns,
  onCommit,
  tips,
  rowSpans,
  marks,
}: {
  row: Pb1Row;
  columns: Pb1Column[];
  onCommit: Pb1Commit;
  // The global comments: a row that has one shows it at the mouse pointer.
  tips?: CommentTips;
  // Column -> rows its cell covers downwards; 0: covered by a cell above (not drawn).
  rowSpans?: Record<string, number>;
  marks?: Pb1SearchMarks;
}) {
  const cells: ReactNode[] = [];
  for (let index = 0; index < columns.length; index++) {
    const column = columns[index];
    if (rowSpans?.[column.key] === 0) continue;
    const cell = row.cells[column.key] ?? {};
    const span = spanOf(row.cells, columns, index, display(cell).text);
    cells.push(
      <FieldCell
        key={column.key}
        cell={cell}
        column={column}
        span={span}
        rowSpan={rowSpans?.[column.key]}
        onCommit={(value) => onCommit(row.row, column.key, value)}
      />,
    );
    index += span - 1;
  }
  // Section rows (bold description) are shaded to separate the sections.
  const comment = tips ? commentText(row, tips.column) : "";
  const mark = markClass(row, marks);
  if (!comment) {
    return (
      <TableRow
        data-pb1-row={row.row}
        className={cn("hover:bg-transparent", row.shaded && "bg-muted/60 hover:bg-muted/60", mark)}
      >
        {cells}
      </TableRow>
    );
  }
  // The row's global comment pops up above and to the right of the mouse pointer while it is
  // over the row (user, 2026-11-15); the only mouse reaction of the PB-1 tables.
  const number = row.cells.A?.value;
  const description = String(row.cells.B?.value ?? "").trim();
  const title = [
    "Komentar",
    number !== null && number !== undefined && number !== "" ? String(number) : "",
    description,
  ].filter(Boolean).join(" · ");
  return (
    <TableRow
      data-pb1-row={row.row}
      className={cn("hover:bg-transparent", row.shaded && "bg-muted/60 hover:bg-muted/60", mark)}
      onMouseMove={(e) => tips?.show({ title, text: comment, x: e.clientX, y: e.clientY })}
      onMouseLeave={() => tips?.show(null)}
    >
      {cells}
    </TableRow>
  );
}

type CommentTip = { title: string; text: string; x: number; y: number };
/** The comment column and the function that shows a comment at the mouse (null hides it). */
type CommentTips = { column: string; show: (tip: CommentTip | null) => void };

const TIP_GAP = 14; // px between the mouse pointer and the comment
const TIP_MARGIN = 8; // px kept from the window's edges

/**
 * The comment that follows the mouse: above and to the right of the pointer, moved inside the
 * window when it would leave it (above and to the left of the pointer near the right edge,
 * below it near the top, never past the bottom edge); its width doesn't depend on where it is. Holds its own state so the table doesn't re-render while the mouse moves.
 */
function CommentTipLayer({ tips }: { tips: { current: CommentTips["show"] } }) {
  const [tip, setTip] = useState<CommentTip | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    tips.current = setTip;
    return () => {
      tips.current = () => {};
    };
  }, [tips]);
  useLayoutEffect(() => {
    const box = boxRef.current;
    if (!tip || !box) return;
    const { width, height } = box.getBoundingClientRect();
    let left = tip.x + TIP_GAP;
    let top = tip.y - TIP_GAP - height;
    // No room on the right: above and to the LEFT of the pointer (user, 2026-11-15).
    if (left + width > window.innerWidth - TIP_MARGIN) left = Math.max(TIP_MARGIN, tip.x - TIP_GAP - width);
    if (top < TIP_MARGIN) top = tip.y + TIP_GAP + 6;
    // Never past the bottom edge either (e.g. a long comment shown below the pointer).
    top = Math.max(TIP_MARGIN, Math.min(top, window.innerHeight - TIP_MARGIN - height));
    box.style.left = `${left}px`;
    box.style.top = `${top}px`;
  }, [tip]);
  if (!tip) return null;
  return createPortal(
    <div
      ref={boxRef}
      role="tooltip"
      // w-max: the box keeps its width wherever it is (near the window's right edge the browser
      // would otherwise shrink it and wrap the comment into a tall, narrow column).
      className="bg-popover text-popover-foreground pointer-events-none fixed top-0 left-0 z-50 w-max max-w-xs rounded-md border px-3 py-2 text-sm shadow-md"
    >
      <div className="text-muted-foreground mb-1 text-xs">{tip.title}</div>
      <div className="break-words whitespace-pre-wrap">{tip.text}</div>
    </div>,
    document.body,
  );
}

/**
 * PB-1 form table: original columns, row order and bold styling; nothing is truncated.
 * Every field except the line numbers can be edited (amounts for this company, template
 * fields for every company).
 */
export function Pb1Table({
  data,
  onCommit,
  marks,
}: {
  data: Pb1Data;
  onCommit: Pb1Commit;
  marks?: Pb1SearchMarks; // rows found by the header search
}) {
  const { columns, rows } = data;
  const head = data.head ?? [];
  const headColumns = data.head_columns?.length === columns.length ? data.head_columns : columns;
  const summary = data.summary ?? [];
  // Some sheets (Preliminarni rezultat) have no header row.
  const hasHeader = columns.some((c) => c.header !== null && c.header !== undefined);
  // The global comments, shown at the mouse pointer over their rows (CommentTipLayer).
  const showTip = useRef<CommentTips["show"]>(() => {});
  const tipsRef = useRef<CommentTips | null>(null);
  if (data.comment_column && tipsRef.current?.column !== data.comment_column) {
    tipsRef.current = { column: data.comment_column, show: (tip) => showTip.current(tip) };
  }
  const tips = data.comment_column ? (tipsRef.current ?? undefined) : undefined;

  return (
    <>
      {tips && <CommentTipLayer tips={showTip} />}
      {/* As tall as the window below the page header (4rem) and the stuck strip (about 4.5rem)
          plus the bottom padding (1.5rem): at the top the table starts at about 203 px; once the
          page is scrolled only the strip stays in sight (stuck) and the table grows by the
          height of the rows above it (user, 2026-11-25). If the strip's height changes, change
          10rem here (see Pb1Strip, layout rule 4). */}
      <div className="max-h-[calc(100svh-10rem)] overflow-auto rounded-md border">
        <table className="w-full caption-bottom text-sm">
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
              <Pb1RowView key={row.row} row={row} columns={columns} onCommit={onCommit} tips={tips} marks={marks} />
            ))}
          </TableBody>
        </table>
      </div>

    </>
  );
}

const RESULT_STATUS: Record<Pb1Result["status"], { text: string; className: string }> = {
  profit: { text: "Dobitak", className: "border-success/40 bg-success/10 text-success" },
  loss: { text: "Gubitak", className: "border-destructive/40 bg-destructive/10 text-destructive" },
  zero: { text: "Nula", className: "text-muted-foreground" },
};

/** A result (computed by the backend): its label, a profit / loss badge and the amount. */
function ResultTile({
  label,
  result,
  note,
  plain,
  className,
}: {
  label: string;
  result: Pb1Result;
  note?: string;
  // No badge and no colour (Poreski rezultat, user 2026-11-25); else the badge, and the amount
  // green above 0, red with its minus below 0 (Knjigovodstveni rezultat, the balance 6 - 5).
  plain?: boolean;
  className?: string;
}) {
  const status = RESULT_STATUS[result.status];
  // A tile of normal width over the strip's height: label and badge at the top, the amount
  // below (and the note); nothing wraps.
  return (
    <div className={cn("bg-card flex min-w-56 flex-col justify-between gap-1 rounded-md border px-4 py-2 whitespace-nowrap", className)}>
      <div className="flex items-center justify-between gap-3">
        <span className="text-muted-foreground text-xs font-medium">{label}</span>
        {!plain && (
          <Badge variant="outline" className={status.className}>
            {status.text}
          </Badge>
        )}
      </div>
      <div className="grid justify-items-end gap-0.5">
        <span
          className={cn(
            "text-xl font-semibold tabular-nums",
            !plain && result.value < 0 && "text-destructive",
            !plain && result.value > 0 && "text-success",
          )}
        >
          {formatNumber(result.value, "#,##0.00").text}
        </span>
        <span className={cn("text-xs", note ? "text-muted-foreground" : "invisible")}>{note ?? "-"}</span>
      </div>
    </div>
  );
}

/**
 * The strip of Poreski bilans, on all three tabs (user, 2026-11-25), stuck right under the page
 * header while the page scrolls (not on phones): the tabs (two-line titles) with the head table
 * right of them; the two results one under the other; Porez (15%) over Mesecna akontacija.
 * `data` is always the Poreski bilans tab.
 *
 * LAYOUT RULES: keep them, so the strip holds with other numbers and texts (user, 2026-11-25:
 * "it must not fall apart on a small difference"):
 * 1. Nothing in it wraps or is cut: every label and amount is `whitespace-nowrap`, every tile
 *    and row is at least as wide as its content (`min-w-max` on the result rows, `shrink-0` on
 *    the tabs / head table / closing column). Never use fixed widths for amounts: a longer
 *    amount (e.g. -123.456.789,00) makes its tile wider, it never overlaps a neighbour.
 * 2. Only the results column grows (`flex-1`): it takes the free width; the other parts keep
 *    their content width. No sideways scrolling (user, 2026-11-25: arrange it, there is room):
 *    the line must fit; keep the spare width (about 280 px at 1536 px with 1. OKTOBAR 2026)
 *    by keeping gaps and paddings small (gap-2, px-2.5, tabs w-22). No overflow clipping
 *    anywhere in the strip either: the Klasa 5 / 6 editor floats over its cell
 *    (FieldCell wideEditor), as wide as the value typed, and must not be cut.
 * 3. Amounts are `tabular-nums`, right-aligned at the row's end, so the two results line up.
 * 4. The strip's height is fixed by its rows, not by its contents: two rows of about 28 px
 *    (head table h-6 + py-0.5 cells; result and closing rows share the height with `grid`),
 *    the tabs `h-12`. A taller strip moves the form table below 204 px at the top; if the
 *    strip's height changes, adjust the table's max-h in Pb1Table (window - header - strip).
 * 5. Colours only through theme tokens (text-success / text-destructive, border-l-*), so light
 *    and dark both work.
 */
export function Pb1Strip({
  data,
  onCommit,
  tabs,
  marks,
}: {
  data: Pb1Data | null;
  onCommit: Pb1Commit;
  tabs: ReactNode;
  marks?: Pb1SearchMarks;
}) {
  const head = data?.head ?? [];
  const summary = data?.summary ?? [];
  const columns = data?.columns ?? [];
  const headColumns = data?.head_columns?.length === columns.length ? data.head_columns : columns;
  // The closing rows after the tax base (Porez (15%), Mesecna akontacija): label and value.
  const closing = closingFigures(summary, columns).slice(1);
  const accounting = data?.results?.accounting;
  const tax = data?.results?.tax;
  const closingIcons = [Percent, CalendarClock];
  return (
    // Framed (user, 2026-11-25): a rounded border with a soft muted background, the tiles on the
    // card colour inside; the outer band (page background) covers the form when stuck. One low
    // line: the tabs with the head table right of them, the two results one under the other
    // (narrow, value in the middle, a coloured edge and an icon), Porez (15%) over Mesecna
    // akontacija.
    <div className="bg-background pt-1 pb-1 sm:sticky sm:top-16 sm:z-30">
      <div className="bg-muted/50 flex flex-nowrap items-stretch gap-2 rounded-lg border p-1">
        <div className="flex shrink-0 items-center gap-2">
          {tabs}
          {data && head.length > 0 && data.head_figures && data.head_figures.length > 0 ? (
            <HeadFigures head={head} figures={data.head_figures} onCommit={onCommit} />
          ) : head.length > 0 ? (
            <AlignedTable
              rows={head}
              columns={compactFirstColumn(head, headColumns, usedColumns(head, headColumns))}
              range={usedColumns(head, headColumns)}
              onCommit={onCommit}
              mergeFirstDown
            />
          ) : null}
        </div>
        {accounting && tax && (
          <div className="grid min-w-max flex-1 gap-1">
            <ResultRow
              icon={Scale}
              label="Knjigovodstveni rezultat (6 - 5)"
              result={accounting}
              edge={accounting.value > 0 ? "border-l-success" : accounting.value < 0 ? "border-l-destructive" : "border-l-border"}
            />
            <ResultRow
              icon={Landmark}
              label="Poreski rezultat (poreska osnovica)"
              result={tax}
              plain
              edge="border-l-brand"
              note={tax.status === "loss" ? "Porez i akontacija su 0." : undefined}
            />
          </div>
        )}
        {closing.length > 0 && (
          <div className="grid shrink-0 gap-1">
            {closing.map((figure, index) => {
              const Icon = closingIcons[index] ?? Percent;
              return (
                <div
                  key={figure.row}
                  data-pb1-row={figure.row}
                  className={cn(
                    "bg-card flex items-center gap-2 rounded-md border px-2.5 whitespace-nowrap",
                    markClass({ row: figure.row, cells: {} }, marks),
                  )}
                >
                  <Icon className="text-muted-foreground size-3.5 shrink-0" />
                  <span className="text-muted-foreground text-xs font-medium">{figure.label}</span>
                  <span className={cn("ms-auto text-sm font-semibold tabular-nums", figure.red && "text-destructive")}>
                    {figure.text}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * One result as a low row (user, 2026-11-25): icon and label left, the badge and the amount at the
 * right edge, a coloured left edge. Knjigovodstveni rezultat: its badge, the amount green above 0 and red with
 * the minus below 0; Poreski rezultat (`plain`): no badge, no colour.
 */
function ResultRow({
  icon: Icon,
  label,
  result,
  plain,
  edge,
  note,
}: {
  icon: typeof Scale;
  label: string;
  result: Pb1Result;
  plain?: boolean;
  edge: string;
  note?: string;
}) {
  const status = RESULT_STATUS[result.status];
  return (
    // Never narrower than its content (min-w-max): the strip scrolls instead of overlapping.
    <div className={cn("bg-card grid min-w-max grid-cols-[auto_1fr_auto] items-center gap-2 rounded-md border border-l-4 px-2.5 whitespace-nowrap", edge)}>
      <span className="text-muted-foreground flex items-center gap-2 text-xs font-medium">
        <Icon className="size-4 shrink-0" />
        {label}
      </span>
      {/* The badge (or the loss note) left of the amount, the amount at the right edge (user,
          2026-11-25), so the amounts of both rows line up. */}
      <span className="flex justify-end">
        {!plain ? (
          <Badge variant="outline" className={status.className}>
            {status.text}
          </Badge>
        ) : note ? (
          <span className="text-muted-foreground text-xs">{note}</span>
        ) : null}
      </span>
      <span
        className={cn(
          "justify-self-end text-base font-bold tabular-nums",
          !plain && result.value < 0 && "text-destructive",
          !plain && result.value > 0 && "text-success",
        )}
      >
        {formatNumber(result.value, "#,##0.00").text}
      </span>
    </div>
  );
}

/** The closing rows with a value as label + shown value (no line number). */
function closingFigures(rows: Pb1Row[], columns: Pb1Column[]) {
  const figures: { row: number; label: string; text: string; red: boolean }[] = [];
  for (const row of rows) {
    const label = columns
      .filter((c) => !c.narrow && !c.amount)
      .map((c) => display(row.cells[c.key] ?? {}).text.trim())
      .find(Boolean);
    const value = columns.map((c) => (c.amount ? row.cells[c.key] : undefined)).find((cell) => cell?.amount);
    if (label && value) {
      const shown = display(value);
      figures.push({ row: row.row, label, text: shown.text, red: shown.red });
    }
  }
  return figures;
}

/**
 * The form's closing rows as a small box: only the columns that hold something in them,
 * without the line-number column (description and amount).
 */
function SummaryBox({
  rows,
  columns,
  onCommit,
  tips,
  marks,
}: {
  rows: Pb1Row[];
  columns: Pb1Column[];
  onCommit: Pb1Commit;
  tips?: CommentTips;
  marks?: Pb1SearchMarks;
}) {
  const shown = columns.filter(
    (column) =>
      !column.narrow &&
      rows.some((r) => {
        const cell = r.cells[column.key];
        return cell && (cell.amount || display(cell).text.trim() !== "");
      }),
  );
  return (
    <div className="max-w-full overflow-x-auto rounded-md border">
      <table className="caption-bottom text-sm">
        <TableBody>
          {rows.map((row) => {
            // The box's heading ("V. Poreska osnovica": a row without any amount field): one cell
            // over the whole width, no inner border, darker than the rest (user, 2026-11-17).
            // Not shown any more (user, 2026-11-25): only the three rows with a value remain.
            const heading = shown.every((c) => !row.cells[c.key]?.amount && !row.cells[c.key]?.editable);
            if (heading) return null;
            return <Pb1RowView key={row.row} row={row} columns={shown} onCommit={onCommit} tips={tips} marks={marks} />;
          })}
        </TableBody>
      </table>
    </div>
  );
}

type ColumnRange = { start: number; end: number }; // column indexes, end exclusive

/** The columns with the first one of `range` narrowed to its longest text in `rows` (at least 8 characters). */
function compactFirstColumn(rows: Pb1Row[], columns: Pb1Column[], range: ColumnRange): Pb1Column[] {
  const first = columns[range.start];
  if (!first) return columns;
  const longest = Math.max(0, ...rows.map((r) => display(r.cells[first.key] ?? {}).text.trim().length));
  const width = Math.min(first.width, Math.max(8, longest));
  return columns.map((c, i) => (i === range.start ? { ...c, width } : c));
}

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

/** The head of Poreski bilans as labelled values: one row of labels, one row of values (fields). */
function HeadFigures({
  head,
  figures,
  onCommit,
}: {
  head: Pb1Row[];
  figures: Pb1HeadFigure[];
  onCommit: Pb1Commit;
}) {
  const cellOf = (figure: Pb1HeadFigure): Pb1Cell => {
    const cell = head.find((r) => r.row === figure.row)?.cells[figure.column] ?? {};
    return { ...cell, fill: undefined }; // no sheet colours here
  };
  return (
    // No overflow clipping: the Klasa 5 / 6 editor floats over the cell, wider than it.
    <div className="bg-card w-fit rounded-md border">
      <table className="caption-bottom text-sm">
        <TableBody>
          <TableRow className="bg-muted/60 hover:bg-muted/60">
            {figures.map((figure) => (
              <TableHead
                key={`${figure.row}${figure.column}`}
                className={cn("text-muted-foreground h-6 px-2 text-end text-xs font-medium", COLUMN_BORDER)}
              >
                {figure.label}
              </TableHead>
            ))}
          </TableRow>
          <TableRow className="hover:bg-transparent">
            {figures.map((figure) => (
              <FieldCell
                key={`${figure.row}${figure.column}`}
                cell={cellOf(figure)}
                column={{ key: figure.column, width: 14, amount: true }}
                onCommit={(value) => onCommit(figure.row, figure.column, value)}
                className="min-w-24 px-2 py-0.5"
                wideEditor
              />
            ))}
          </TableRow>
        </TableBody>
      </table>
    </div>
  );
}

/**
 * A separate small table of form rows (the head rows): only the columns of `range` are drawn,
 * each with its form width (in characters).
 */
function AlignedTable({
  rows,
  columns,
  range,
  onCommit,
  tips,
  mergeFirstDown,
  className,
}: {
  rows: Pb1Row[];
  columns: Pb1Column[];
  range?: ColumnRange;
  onCommit: Pb1Commit;
  tips?: CommentTips;
  // The first column's cells cover the empty, read-only cells below them (user, 2026-11-16:
  // no empty cells under the company name in the head rows).
  mergeFirstDown?: boolean;
  className?: string;
}) {
  const { start, end } = range ?? { start: 0, end: columns.length };
  const shown = columns.slice(start, end);
  const spans = mergeFirstDown && shown[0] ? mergeDown(rows, shown[0].key) : undefined;
  return (
    <div className={cn("w-fit max-w-full overflow-x-auto rounded-md border", className)}>
      <table className="w-full caption-bottom text-sm">
        <colgroup>
          {shown.map((column) => (
            <col key={column.key} style={{ width: columnWidth(column) }} />
          ))}
        </colgroup>
        <TableBody>
          {rows.map((row, i) => (
            <Pb1RowView
              key={row.row}
              row={row}
              columns={shown}
              onCommit={onCommit}
              tips={tips}
              rowSpans={spans?.[i] !== undefined ? { [shown[0].key]: spans[i] } : undefined}
            />
          ))}
        </TableBody>
      </table>
    </div>
  );
}

/** Per row, how many rows the cell of `key` covers (0: covered by the one above). A cell with
 * content covers the empty, read-only cells right below it. */
function mergeDown(rows: Pb1Row[], key: string): number[] {
  const spans = rows.map(() => 1);
  let owner = -1;
  rows.forEach((row, i) => {
    const cell = row.cells[key];
    const empty = !cell || (!cell.editable && !cell.amount && display(cell).text.trim() === "");
    if (empty && owner >= 0) {
      spans[owner] += 1;
      spans[i] = 0;
    } else {
      owner = empty ? -1 : i;
    }
  });
  return spans;
}

/**
 * The PB-1 comments as "# · Opis → comment" pairs, one per row. Global (the same for every year
 * and company); shown and edited only on the Global Settings page (the API marks the fields
 * editable there; the PB-1 page doesn't show them). Rates (5,00%, ...) are numbers used by the
 * formulas. `note`: a sentence under the title; `className`: the list's size.
 */
export function Pb1Comments({
  data,
  onCommit,
  note,
  className,
}: {
  data: Pick<Pb1Data, "rows" | "summary" | "comment_column">;
  onCommit: Pb1Commit;
  note?: string;
  className?: string;
}) {
  const column = data.comment_column;
  if (!column) return null;
  const items = [...data.rows, ...(data.summary ?? [])].filter((row) => {
    const description = row.cells.B?.value;
    return typeof description === "string" && description.trim() !== "";
  });
  return (
    <div className={cn("flex max-h-[calc(100svh-16rem)] flex-col rounded-md border", className)}>
      <div className="bg-muted border-b px-3 py-2 text-sm font-medium">
        Komentari
        {note && <p className="text-muted-foreground mt-0.5 text-xs font-normal">{note}</p>}
      </div>
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
        canEdit && !editing && "cursor-pointer",
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
