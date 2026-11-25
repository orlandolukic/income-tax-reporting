import { CalendarPlus, House, Settings, SquarePen, type LucideIcon } from "lucide-react";

export type NavItem = { title: string; url: string; icon: LucideIcon };
export type NavGroup = { title: string; items: NavItem[] };

// Sidebar navigation. Add new pages here so they appear in the sidebar.
export const navGroups: NavGroup[] = [
  {
    title: "Opšte",
    items: [{ title: "Početna", url: "/", icon: House }],
  },
  {
    title: "Firme",
    items: [{ title: "Izmena podataka firmi", url: "/edit-company-data", icon: SquarePen }],
  },
  {
    title: "Administracija",
    items: [{ title: "Migracija", url: "/migration", icon: CalendarPlus }],
  },
];

// Pinned to the bottom of the sidebar, right above the user menu (settings are always last).
export const footerNavItems: NavItem[] = [{ title: "Globalna podešavanja", url: "/global-settings", icon: Settings }];
