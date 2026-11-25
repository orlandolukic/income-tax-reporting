import { cn } from "@/lib/utils";
import type { TableStats } from "@/hooks/use-company-table";
import { formatNumber } from "@/lib/excel-format";

const TOTAL_FORMAT = "#,##0.##";
const SHARE_FORMAT = "0.0%";
// One accent per statistic (shadcn chart palette), for the share bar.
const BAR = ["bg-chart-1", "bg-chart-2", "bg-chart-3"];

/**
 * Statistics of the Home table: the totals of Preliminarni, GFI uradjen and GFI ZA RAD over all
 * companies, each with its share of the kom total, i.e. of the number of companies (kom = 1 for
 * every company). Computed by the server.
 *
 * A low strip of three small cards over the full width, each with a share bar (user, 2026-11-25:
 * modest, so the Home table starts 204 px from the top; it stays stuck under the page header when
 * the page is scrolled).
 */
export function GfiStats({ stats }: { stats: TableStats }) {
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {stats.columns.map((column, index) => {
        const share = column.share ?? 0;
        return (
          <div
            key={column.key}
            className="bg-card flex items-center gap-3 rounded-md border px-3 py-1 shadow-xs"
          >
            <span className="text-muted-foreground shrink-0 text-xs">{column.header?.trim() || column.key}</span>
            <span className="shrink-0 text-base font-bold tabular-nums">
              {formatNumber(column.total, TOTAL_FORMAT).text}
            </span>
            <div className="bg-muted h-1.5 min-w-8 flex-1 overflow-hidden rounded-full" aria-hidden>
              <div
                className={cn("h-full rounded-full", BAR[index % BAR.length])}
                style={{ width: `${Math.max(0, Math.min(1, share)) * 100}%` }}
              />
            </div>
            <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
              {column.share !== undefined ? formatNumber(column.share, SHARE_FORMAT).text : "-"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
