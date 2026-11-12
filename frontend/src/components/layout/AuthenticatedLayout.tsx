import { Outlet } from "react-router";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { CellAutosaveProvider } from "@/context/CellAutosaveProvider";
import { ReportingYearProvider } from "@/context/ReportingYearProvider";
import { AppSidebar } from "./AppSidebar";
import { Header } from "./Header";

/** Shell for all logged-in pages: sidebar + header + routed page content. */
export function AuthenticatedLayout() {
  return (
    <ReportingYearProvider>
      {/* One autosave queue for all pages (Home, Company Registry). */}
      <CellAutosaveProvider>
        {/* Collapsed by default so wide tables get the full width; the header toggle expands it. */}
        <SidebarProvider defaultOpen={false}>
          <AppSidebar />
          {/* min-w-0: wide content (tables) scrolls inside the page instead of widening it. */}
          <SidebarInset className="min-w-0">
            <Header />
            <Outlet />
          </SidebarInset>
        </SidebarProvider>
      </CellAutosaveProvider>
    </ReportingYearProvider>
  );
}
