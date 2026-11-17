import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { TableStats } from "@/hooks/use-company-table";
import { formatNumber } from "@/lib/excel-format";

const TOTAL_FORMAT = "#,##0.##";
const SHARE_FORMAT = "0.0%";

/**
 * Statistics above the Home table: the totals of Preliminarni, GFI uradjen and GFI ZA RAD
 * over all companies, each with its share of the kom total, i.e. of the number of companies
 * (kom = 1 for every company). Computed by the server.
 */
export function GfiStats({ stats }: { stats: TableStats }) {
  const baseTotal = formatNumber(stats.base_total, TOTAL_FORMAT).text;

  return (
    <div className="grid gap-4 sm:grid-cols-3">
      {stats.columns.map((column) => (
        <Card key={column.key} className="gap-2 py-4">
          <CardHeader className="px-4">
            <CardDescription>{column.header?.trim() || column.key}</CardDescription>
            <CardTitle className="text-2xl font-bold tabular-nums">
              {formatNumber(column.total, TOTAL_FORMAT).text}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-muted-foreground px-4 text-sm tabular-nums">
            {column.share !== undefined
              ? `${formatNumber(column.share, SHARE_FORMAT).text} of ${baseTotal} companies`
              : "Nema firmi."}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
