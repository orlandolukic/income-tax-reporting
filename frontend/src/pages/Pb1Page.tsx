import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router";
import { useAuth } from "@/auth/AuthContext";
import { CompanyTableSkeleton } from "@/components/CompanyTable";
import { Main } from "@/components/layout/Main";
import { Pb1Table } from "@/components/Pb1Table";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePb1 } from "@/hooks/use-pb1";

/** PB-1 (Poreski bilans) detail page of one company from the GFI table. */
export default function Pb1Page() {
  const params = useParams();
  const year = Number(params.year);
  const row = Number(params.row);
  const { markSessionExpired } = useAuth();
  const { data, loading, error } = usePb1(year, row, markSessionExpired);

  return (
    <Main>
      <Button variant="outline" size="sm" asChild>
        <Link to="/">
          <ArrowLeft />
          Back
        </Link>
      </Button>

      <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{data?.company.name ?? "PB-1"}</h1>
          <p className="text-muted-foreground text-sm">
            PB-1 · {data?.sheet ?? "Poreski bilans"} · {year}
            {data?.company.pib && ` · PIB ${data.company.pib}`}
          </p>
        </div>
        {data && (
          <Badge variant={data.has_values ? "secondary" : "outline"}>
            {data.has_values ? `Values from ${data.workbook}` : "No PB-1 values yet"}
          </Badge>
        )}
      </div>

      <div className="mt-6">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {loading && !data && <CompanyTableSkeleton />}
        {data && <Pb1Table data={data} />}
      </div>
    </Main>
  );
}
