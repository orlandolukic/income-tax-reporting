import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ThemeSwitch } from "@/components/ThemeSwitch";
import { ProfileDropdown } from "./ProfileDropdown";

export function Header() {
  return (
    <header className="bg-background/80 sticky top-0 z-50 flex h-16 items-center gap-3 px-4 backdrop-blur sm:gap-4">
      <SidebarTrigger variant="outline" className="max-md:scale-125" />
      <Separator orientation="vertical" className="data-[orientation=vertical]:h-6" />
      <div className="ms-auto flex items-center gap-2">
        <ThemeSwitch />
        <ProfileDropdown />
      </div>
    </header>
  );
}
