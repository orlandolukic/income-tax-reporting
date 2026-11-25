import { ListFilter } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Which companies Home shows: all (the default), only PDP or only PPDG-1S. */
export type TypeFilter = null | "PDP" | "PPDG-1S";

// The order every click steps through, back to the start after the third (user, 2026-11-25).
const ORDER: TypeFilter[] = [null, "PDP", "PPDG-1S"];
const LOOK: Record<string, { label: string; className: string }> = {
  all: { label: "Sve firme", className: "" },
  PDP: { label: "PDP", className: "border-chart-1/50 bg-chart-1/15 text-chart-1 hover:bg-chart-1/25 hover:text-chart-1" },
  "PPDG-1S": {
    label: "PPDG-1S",
    className: "border-chart-2/50 bg-chart-2/15 text-chart-2 hover:bg-chart-2/25 hover:text-chart-2",
  },
};

/**
 * The company type filter on Home, left of the search in the page header (user, 2026-11-25): one
 * button with three states, each its own colour; every click takes the next state:
 * Sve firme -> PDP -> PPDG-1S -> Sve firme.
 */
export function TypeFilterButton({ value, onChange }: { value: TypeFilter; onChange: (next: TypeFilter) => void }) {
  const look = LOOK[value ?? "all"];
  const next = ORDER[(ORDER.indexOf(value) + 1) % ORDER.length];
  return (
    <Button
      variant="outline"
      size="sm"
      className={cn("w-28 justify-start", look.className)}
      aria-label={`Tip firmi: ${look.label}. Klik prikazuje: ${LOOK[next ?? "all"].label}.`}
      onClick={() => onChange(next)}
    >
      <ListFilter />
      {look.label}
    </Button>
  );
}
