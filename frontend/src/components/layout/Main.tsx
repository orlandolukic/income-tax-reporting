import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Content area of an authenticated page. */
export function Main({ children, className }: { children: ReactNode; className?: string }) {
  return <main className={cn("px-4 py-6", className)}>{children}</main>;
}
