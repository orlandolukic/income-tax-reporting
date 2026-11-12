import { Building2, CalendarPlus, House, type LucideIcon } from "lucide-react";

export type NavItem = { title: string; url: string; icon: LucideIcon };
export type NavGroup = { title: string; items: NavItem[] };

// Sidebar navigation. Add new pages here so they appear in the sidebar.
export const navGroups: NavGroup[] = [
  {
    title: "General",
    items: [{ title: "Home", url: "/", icon: House }],
  },
  {
    title: "Companies",
    items: [{ title: "Company Registry", url: "/company-registry", icon: Building2 }],
  },
  {
    title: "Administracija",
    items: [{ title: "Migracija", url: "/migration", icon: CalendarPlus }],
  },
];
