import { useEffect, useState } from "react";
import { Bell, BellOff } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useNotifications } from "@/hooks/useNotifications";

export function TopHeader() {
  const [now, setNow] = useState<Date | null>(null);
  const { notificationsEnabled, toggleNotifications } = useNotifications();

  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 1000 * 30);
    return () => clearInterval(t);
  }, []);

  const dateStr = now?.toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
  const timeStr = now?.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <header
      id="top"
      className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-surface/80 px-4 backdrop-blur"
    >
      <SidebarTrigger className="-ml-1" />
      <div className="h-5 w-px bg-border" />

      <div className="text-sm font-semibold tracking-tight text-foreground">
        CT Prioritisation
      </div>

      <div className="ml-auto flex items-center gap-3">
        <div className="hidden text-right md:block" suppressHydrationWarning>
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
            {dateStr ?? ""}
          </div>
          <div className="text-sm font-semibold tabular-nums text-foreground">
            {timeStr ?? ""}
          </div>
        </div>
        <button
          onClick={toggleNotifications}
          aria-label={notificationsEnabled ? "Turn off notifications" : "Turn on notifications"}
          className={`relative flex h-9 w-9 items-center justify-center rounded-lg border border-border transition-colors ${
            notificationsEnabled
              ? "bg-surface text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              : "bg-accent text-accent-foreground hover:bg-accent/80"
          }`}
        >
          {notificationsEnabled ? (
            <>
              <Bell className="h-4 w-4" />
              <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-risk-critical" />
            </>
          ) : (
            <BellOff className="h-4 w-4" />
          )}
        </button>
      </div>
    </header>
  );
}
