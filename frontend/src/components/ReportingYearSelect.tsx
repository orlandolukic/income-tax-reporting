import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useReportingYear } from "@/context/ReportingYearProvider";

export function ReportingYearSelect() {
  const { years, selectedYear, setSelectedYear, loading } = useReportingYear();

  if (loading) return <Skeleton className="h-9 w-32" />;

  return (
    <div className="flex items-center gap-2">
      <Label htmlFor="reporting-year" className="text-muted-foreground">
        Reporting year
      </Label>
      <Select
        value={selectedYear !== null ? String(selectedYear) : undefined}
        onValueChange={(value) => setSelectedYear(Number(value))}
        disabled={years.length === 0}
      >
        <SelectTrigger id="reporting-year" className="w-28">
          <SelectValue placeholder="—" />
        </SelectTrigger>
        <SelectContent position="popper" align="end">
          {years.map((year) => (
            <SelectItem key={year} value={String(year)}>
              {year}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
