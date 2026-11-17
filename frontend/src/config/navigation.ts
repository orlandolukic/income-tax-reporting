import { CalendarPlus, House, Settings, SquarePen, type LucideIcon } from "lucide-react";

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
    items: [{ title: "Edit Company Data", url: "/edit-company-data", icon: SquarePen }],
  },
  {
    title: "Administration",
    items: [{ title: "Migration", url: "/migration", icon: CalendarPlus }],
  },
];

// Pinned to the bottom of the sidebar, right above the user menu (settings are always last).
export const footerNavItems: NavItem[] = [{ title: "Global Settings", url: "/global-settings", icon: Settings }];
