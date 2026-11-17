import { cn } from "@/lib/utils";

/**
 * The app's mark (user, 2026-11-17): the Landmark icon (lucide "landmark": tax administration)
 * on a blue tile, white columns and a golden roof. Colors come from the theme tokens --brand,
 * --brand-foreground and --brand-accent (src/index.css); the same mark is the browser tab icon
 * (public/favicon.svg).
 */
export function AppLogo({ className }: { className?: string }) {
  return (
    <div className={cn("bg-brand flex aspect-square size-8 shrink-0 items-center justify-center rounded-lg", className)}>
      <svg
        viewBox="0 0 24 24"
        className="size-[1.15rem]"
        fill="none"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        {/* Roof */}
        <path
          d="M11.119 2.205a2 2 0 0 1 1.762 0l7.84 3.846A.5.5 0 0 1 20.5 7h-17a.5.5 0 0 1-.22-.949z"
          className="fill-brand-accent stroke-brand-accent"
        />
        {/* Columns and base */}
        <path d="M6 18v-7M10 18v-7M14 18v-7M18 18v-7M3 22h18" className="stroke-brand-foreground" />
      </svg>
    </div>
  );
}
