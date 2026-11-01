import { Outlet } from "react-router";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { ReportingYearProvider } from "@/context/ReportingYearProvider";
import { AppSidebar } from "./AppSidebar";
import { Header } from "./Header";

/** Shell for all logged-in pages: sidebar + header + routed page content. */
export function AuthenticatedLayout() {
  return (
    <ReportingYearProvider>
      <SidebarProvider>
        <AppSidebar />
        {/* min-w-0: wide content (tables) scrolls inside the page instead of widening it. */}
        <SidebarInset className="min-w-0">
          <Header />
          <Outlet />
        </SidebarInset>
      </SidebarProvider>
    </ReportingYearProvider>
  );
}
