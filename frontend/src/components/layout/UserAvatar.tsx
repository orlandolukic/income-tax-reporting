import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

export function UserAvatar({ username, className }: { username: string; className?: string }) {
  return (
    <Avatar className={cn("size-8 rounded-lg", className)}>
      <AvatarFallback className="rounded-[inherit] uppercase">{username.slice(0, 2)}</AvatarFallback>
    </Avatar>
  );
}
