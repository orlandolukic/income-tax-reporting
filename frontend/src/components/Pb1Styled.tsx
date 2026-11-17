import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { Card } from "@/components/ui/card";
import { TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { display, FieldCell } from "@/components/Pb1Table";
import type { Pb1Cell, Pb1Column, Pb1Commit, Pb1Data, Pb1Row } from "@/hooks/use-pb1";
import { cn } from "@/lib/utils";

/*
 * Styled views of the PB-1 tabs "Uporedo" and "Preliminarni rezultat" (user's request,
 * 2026-11-15: more readable, for every company and year). Looks only: the same rows, values,
 * formulas and the same fields editable (every field goes through FieldCell, as in the plain
 * table). The parts of the Preliminarni sheet are found from its structure, not row numbers.
 */

const EMPTY: Pb1Cell = {};

/** Whether a cell shows something (a value, or an amount field shown as 0,00). */
const hasContent = (cell: Pb1Cell | undefined) => Boolean(cell && (cell.amount || display(cell).text.trim() !== ""));

const columnMap = (data: Pb1Data) => Object.fromEntries(data.columns.map((c) => [c.key, c])) as Record<string, Pb1Column>;

function Cells({
  row,
  keys,
  columns,
  onCommit,
  cellClass,
}: {
  row: Pb1Row;
  keys: string[];
  columns: Record<string, Pb1Column>;
  onCommit: Pb1Commit;
  cellClass?: (key: string) => string | undefined;
}) {
  return (
    <>
      {keys.map((key) => (
        <FieldCell
          key={key}
          cell={row.cells[key] ?? EMPTY}
          column={columns[key] ?? { key, width: 10 }}
          onCommit={(value) => onCommit(row.row, key, value)}
          className={cellClass?.(key) ?? "py-2"}
        />
      ))}
    </>
  );
}

// ---------------------------------------------------------------- Uporedo ----

/**
 * Index (current / previous year): an arrow and a small bar (100 % = half the track). Shown in
 * every line (user, 2026-11-17); an Index of 0 or one that can't be computed (shown 0,00): a
 * level arrow and an empty bar, neither rising nor falling. The bar has a thin outline in the
 * text colour (black in light mode) so an empty one is visible; bars sit at the cell's left edge.
 */
function IndexTrend({ value }: { value: Pb1Cell["value"] }) {
  const index = typeof value === "number" && Number.isFinite(value) ? value : 0;
  const Icon = index === 0 ? Minus : index > 1.0005 ? TrendingUp : index < 0.9995 ? TrendingDown : Minus;
  const fill = Math.max(0, Math.min(index, 2)) / 2;
  return (
    <span className="text-muted-foreground inline-flex items-center gap-1.5" aria-hidden>
      <span className="bg-muted outline-foreground relative hidden h-1.5 w-12 overflow-hidden rounded-full outline sm:inline-block">
        <span className="bg-chart-2 absolute inset-y-0 left-0 rounded-full" style={{ width: `${fill * 100}%` }} />
        <span className="bg-foreground/30 absolute inset-y-0 left-1/2 w-px" />
      </span>
      <Icon className="size-3.5" />
    </span>
  );
}

// Vertical lines between the header cells, like the body's columns (user, 2026-11-17).
const HEAD_BORDER = "shadow-[inset_-1px_0_var(--border)]";

/**
 * Uporedo <year> i <year-1>: the two years side by side. The current year stands out, the
 * previous one is muted in the header; the Index shows its trend; section rows are shaded and
 * empty spacer rows are thin gaps.
 */
export function Pb1ComparisonTable({ data, onCommit }: { data: Pb1Data; onCommit: Pb1Commit }) {
  const columns = columnMap(data);
  const [num, label, current, previous, index] = data.columns.map((c) => c.key);
  const header = (key: string) => columns[key]?.header ?? "";
  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="max-h-[calc(100svh-16rem)] overflow-auto">
        <table className="w-full caption-bottom text-sm">
          <colgroup>
            <col style={{ width: "3rem" }} />
            <col />
            <col style={{ width: "11rem" }} />
            <col style={{ width: "11rem" }} />
            <col style={{ width: "10rem" }} />
          </colgroup>
          <TableHeader className="bg-muted sticky top-0 z-20 shadow-[inset_0_-1px_0_var(--border)] [&_tr]:border-b-0">
            <TableRow className="hover:bg-transparent">
              <TableHead className={cn("text-muted-foreground text-end text-xs", HEAD_BORDER)}>#</TableHead>
              <TableHead className={HEAD_BORDER}>{header(label)}</TableHead>
              <TableHead className={cn("text-foreground text-end font-semibold", HEAD_BORDER)}>{header(current)}</TableHead>
              <TableHead className={cn("text-muted-foreground text-end", HEAD_BORDER)}>{header(previous)}</TableHead>
              <TableHead className="text-end">{header(index)}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.rows.map((row) => {
              const keys = [num, label, current, previous, index];
              if (!keys.some((k) => hasContent(row.cells[k]))) {
                // A spacer row: a thin gap; its (empty) fields stay clickable.
                return (
                  <TableRow key={row.row} className="hover:bg-transparent">
                    <Cells row={row} keys={keys} columns={columns} onCommit={onCommit} cellClass={() => "h-3 py-0"} />
                  </TableRow>
                );
              }
              return (
                <TableRow
                  key={row.row}
                  className={cn("hover:bg-transparent", row.shaded && "bg-muted/60 hover:bg-muted/60 border-t-2")}
                >
                  <Cells row={row} keys={[num, label, current, previous]} columns={columns} onCommit={onCommit} />
                  <FieldCell
                    cell={row.cells[index] ?? EMPTY}
                    column={columns[index]}
                    onCommit={(value) => onCommit(row.row, index, value)}
                    adornment={<IndexTrend value={row.cells[index]?.value} />}
                    className="py-2"
                  />
                </TableRow>
              );
            })}
          </TableBody>
        </table>
      </div>
    </Card>
  );
}

// ---------------------------------------------------- Preliminarni rezultat ----

type Group = { rows: Pb1Row[] };
type Section = { title: string; groups: Group[] };

/** Card with a title bar and a table of form rows. */
function SectionCard({
  title,
  header,
  groups,
  keys,
  columns,
  onCommit,
  isTotal,
  className,
}: {
  title: string;
  header?: string[];
  groups: Group[];
  keys: string[];
  columns: Record<string, Pb1Column>;
  onCommit: Pb1Commit;
  // Emphasized rows: by default the row's own section shading (bold description, column B);
  // the right-hand cards pass their own rule (the shading belongs to the left table).
  isTotal?: (row: Pb1Row) => boolean;
  className?: string;
}) {
  return (
    <Card className={cn("gap-0 overflow-hidden py-0", className)}>
      <div className="bg-muted/60 border-b px-4 py-2.5 text-sm font-semibold">{title}</div>
      <div className="overflow-x-auto">
        <table className="w-full caption-bottom text-sm">
          <colgroup>
            <col style={{ width: "2.5rem" }} />
            <col />
            <col style={{ width: "10rem" }} />
          </colgroup>
          {header && (
            <TableHeader className="[&_tr]:border-b">
              <TableRow className="hover:bg-transparent">
                {header.map((text, i) => (
                  <TableHead
                    key={i}
                    className={cn(
                      "text-muted-foreground h-8 text-xs",
                      (i === 0 || i === header.length - 1) && "text-end",
                      // Lines between the header cells, like the columns below (user, 2026-11-17).
                      i < header.length - 1 && HEAD_BORDER,
                    )}
                  >
                    {text}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
          )}
          <TableBody>
            {groups.map((group, g) =>
              group.rows.map((row, i) => {
                const total = isTotal ? isTotal(row) : row.shaded;
                return (
                  <TableRow
                    key={row.row}
                    className={cn(
                      "hover:bg-transparent",
                      total && "bg-muted/60 hover:bg-muted/60 font-semibold",
                      g > 0 && i === 0 && "border-t-2",
                    )}
                  >
                    <Cells row={row} keys={keys} columns={columns} onCommit={onCommit} />
                  </TableRow>
                );
              }),
            )}
          </TableBody>
        </table>
      </div>
    </Card>
  );
}

const text = (cell: Pb1Cell | undefined) => (cell ? display(cell).text.trim() : "");

/**
 * Preliminarni rezultat: the sheet's two tables side by side and the sections below it, as
 * cards. Left: the main calculation (title row, "# | Opis | RSD" header row, lines). Right:
 * one card per section heading of the right table (a heading is a longer text in its
 * line-number column with nothing beside it); a group whose numbering starts again at 1 is
 * separated by a line. The sections below the two tables (one card per heading: a description
 * without a number and amount) are stacked right under the main calculation in the left column
 * (Podbilansi bilansa uspeha, then Troskovi koji se ne priznaju; user, 2026-11-15), so both
 * columns end at about the same height.
 */
export function Pb1PreliminaryView({ data, onCommit }: { data: Pb1Data; onCommit: Pb1Commit }) {
  const columns = columnMap(data);
  const [a, b, c, , e, f, g] = data.columns.map((col) => col.key);
  const left = [a, b, c];
  const right = [e, f, g];
  const rows = data.rows;
  const lastRight = Math.max(0, ...rows.filter((r) => right.some((k) => hasContent(r.cells[k]))).map((r) => r.row));

  // Left table
  const leftRows = rows.filter((r) => r.row <= lastRight && left.some((k) => hasContent(r.cells[k])));
  const titleRow = leftRows.find((r) => !hasContent(r.cells[a]) && hasContent(r.cells[b]) && !hasContent(r.cells[c]));
  const headerRow = leftRows.find((r) => text(r.cells[a]) === "#");
  const leftBody = leftRows.filter((r) => r !== titleRow && r !== headerRow);

  // Right sections
  const sections: Section[] = [];
  for (const row of rows) {
    if (!right.some((k) => hasContent(row.cells[k]))) continue;
    const heading = text(row.cells[e]);
    if (heading.length > 4 && !hasContent(row.cells[f]) && !hasContent(row.cells[g])) {
      sections.push({ title: heading, groups: [{ rows: [] }] });
      continue;
    }
    if (sections.length === 0) sections.push({ title: "", groups: [{ rows: [] }] });
    const groups = sections[sections.length - 1].groups;
    const current = groups[groups.length - 1];
    if (text(row.cells[e]) === "1" && current.rows.length > 0) groups.push({ rows: [row] });
    else current.rows.push(row);
  }

  // Sections below
  const lower: Section[] = [];
  for (const row of rows) {
    if (row.row <= lastRight || !left.some((k) => hasContent(row.cells[k]) || row.cells[k]?.editable)) continue;
    const isHeading = hasContent(row.cells[b]) && !hasContent(row.cells[a]) && !row.cells[c]?.amount && !hasContent(row.cells[c]);
    if (isHeading) lower.push({ title: text(row.cells[b]), groups: [{ rows: [] }] });
    else if (hasContent(row.cells[a]) || hasContent(row.cells[b])) {
      if (lower.length === 0) lower.push({ title: "", groups: [{ rows: [] }] });
      lower[lower.length - 1].groups[0].rows.push(row);
    }
  }

  const isTotal = (row: Pb1Row) => /^ukupno\b/i.test(text(row.cells[f]));
  const header = headerRow ? left.map((k) => text(headerRow.cells[k])) : undefined;

  return (
    <div className="grid gap-4">
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <div className="grid gap-4">
          <SectionCard
            title={titleRow ? text(titleRow.cells[b]) : data.sheet}
            header={header}
            groups={[{ rows: leftBody }]}
            keys={left}
            columns={columns}
            onCommit={onCommit}
          />
          {lower.map((section, i) => (
            <SectionCard
              key={i}
              title={section.title}
              groups={section.groups}
              keys={left}
              columns={columns}
              onCommit={onCommit}
            />
          ))}
        </div>
        <div className="grid gap-4">
          {sections.map((section, i) => (
            <SectionCard
              key={i}
              title={section.title}
              groups={section.groups.filter((gr) => gr.rows.length > 0)}
              keys={right}
              columns={columns}
              onCommit={onCommit}
              isTotal={isTotal}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
