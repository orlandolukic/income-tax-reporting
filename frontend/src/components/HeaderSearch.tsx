import { createContext, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ChevronUp, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/*
 * A page's search field, shown at the top right of the sticky page header, so it stays in sight
 * however far the page is scrolled (user, 2026-11-17: PB-1 Poreski bilans, Home, Edit Company
 * Data). The header holds an empty slot; a page that wants a search renders <HeaderSearch> and
 * it appears there (a portal), and goes away with the page.
 */

const SlotContext = createContext<{ slot: HTMLElement | null; setSlot: (el: HTMLElement | null) => void } | null>(null);

export function HeaderSearchProvider({ children }: { children: ReactNode }) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  return <SlotContext.Provider value={{ slot, setSlot }}>{children}</SlotContext.Provider>;
}

/** The place in the header where a page's search field appears. */
export function HeaderSearchSlot() {
  const context = useContext(SlotContext);
  return <div ref={context?.setSlot} className="flex min-w-0 items-center" />;
}

/** Matches of a search that steps through them (PB-1): "2 / 5" with previous / next. */
export type SearchSteps = { current: number; total: number; onPrevious: () => void; onNext: () => void };

export function HeaderSearch({
  value,
  onChange,
  placeholder,
  steps,
  emptyText,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  steps?: SearchSteps;
  emptyText?: string; // shown when the search finds nothing (Serbian)
}) {
  const slot = useContext(SlotContext)?.slot;
  if (!slot) return null;
  const searching = value.trim() !== "";
  return createPortal(
    <div className="flex items-center gap-1.5">
      <div className="relative w-44 sm:w-64">
        <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
        <Input
          type="search"
          value={value}
          placeholder={placeholder}
          aria-label={placeholder}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") onChange("");
            if (e.key === "Enter" && steps && steps.total > 0) {
              e.preventDefault();
              if (e.shiftKey) steps.onPrevious();
              else steps.onNext();
            }
          }}
          className={cn("h-9 ps-8 pe-8 [&::-webkit-search-cancel-button]:hidden", searching && "border-brand/60")}
        />
        {searching && (
          <button
            type="button"
            aria-label="Clear search"
            onClick={() => onChange("")}
            className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2 -translate-y-1/2 cursor-pointer"
          >
            <X className="size-4" />
          </button>
        )}
      </div>
      {searching && steps && (
        <>
          <span
            className={cn(
              "min-w-12 text-center text-xs tabular-nums",
              steps.total ? "text-muted-foreground" : "text-destructive",
            )}
          >
            {steps.total ? `${steps.current + 1} / ${steps.total}` : (emptyText ?? "0")}
          </span>
          <Button variant="ghost" size="icon" className="size-8" aria-label="Previous match" disabled={!steps.total} onClick={steps.onPrevious}>
            <ChevronUp />
          </Button>
          <Button variant="ghost" size="icon" className="size-8" aria-label="Next match" disabled={!steps.total} onClick={steps.onNext}>
            <ChevronDown />
          </Button>
        </>
      )}
    </div>,
    slot,
  );
}
