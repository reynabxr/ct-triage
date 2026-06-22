import { motion } from "framer-motion";
import { GitBranch } from "lucide-react";
import { deriveNarrativeItems, type QueueCaseRecord, type QueueEventRecord } from "@/lib/queue-models";

export function ReasoningPanel({
  entries,
  caseRecords,
  isSimulationRunning,
}: {
  entries: QueueEventRecord[];
  caseRecords: QueueCaseRecord[];
  isSimulationRunning?: boolean;
}) {
  const items = deriveNarrativeItems(entries, caseRecords);

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col rounded-2xl border border-border bg-surface shadow-soft">
      <div className="flex flex-none items-center gap-2.5 border-b border-border px-4 py-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-info-soft text-info">
          <GitBranch className="h-4 w-4" />
        </div>
        <div>
          <div className="text-sm font-semibold tracking-tight text-foreground">Queue activity</div>
          <div className="text-[11px] text-muted-foreground">Live chronological log</div>
        </div>
      </div>
      <ol className="min-h-0 flex-1 space-y-0 overflow-y-auto px-4 py-3">
        {items.length === 0 && !isSimulationRunning && (
          <li className="text-xs text-muted-foreground py-4 text-center">
            No activity yet. Start the simulation to see queue events.
          </li>
        )}
        {items.length === 0 && isSimulationRunning && (
          <li className="flex flex-col items-center gap-2 py-6 text-center">
            <span className="flex gap-1">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="h-1.5 w-1.5 rounded-full bg-primary animate-bounce"
                  style={{ animationDelay: `${i * 150}ms` }}
                />
              ))}
            </span>
            <span className="text-xs text-muted-foreground">Agents processing — waiting for first event…</span>
          </li>
        )}
        {items.length > 0 && isSimulationRunning && (
          <li className="flex items-center gap-1.5 pb-3 text-[11px] text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
            Agents active
          </li>
        )}
        {items.map((item, index) => (
          <motion.li
            key={item.id}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            className="relative pl-5 pb-4 last:pb-1"
          >
            <span
              className={`absolute left-1 top-1.5 h-1.5 w-1.5 rounded-full ring-4 ${
                item.tone === "critical"
                  ? "bg-risk-critical ring-risk-critical/10"
                  : item.tone === "stable"
                    ? "bg-risk-stable ring-risk-stable/10"
                    : "bg-primary ring-primary/10"
              }`}
            />
            {index < items.length - 1 && (
              <span className="absolute left-[6.5px] top-3 h-full w-px bg-border" />
            )}

            <div className="relative z-10 rounded-md">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs font-semibold text-foreground">{item.headline}</span>
                <span
                  className="text-[10.5px] tabular-nums text-muted-foreground shrink-0"
                  suppressHydrationWarning
                >
                  {item.timestamp.toLocaleTimeString(undefined, {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })}
                </span>
              </div>
              {item.subheadline && (
                <div className="mt-0.5 text-[11.5px] font-medium text-muted-foreground">
                  {item.subheadline}
                </div>
              )}
              {item.bullets.length > 0 && (
                <ul className="mt-1 space-y-0.5">
                  {item.bullets.map((bullet, bi) => (
                    <li key={bi} className="text-[12px] text-muted-foreground">
                      · {bullet}
                    </li>
                  ))}
                </ul>
              )}
              {item.rankChange && (
                <div className="mt-1.5 rounded-md bg-info-soft/60 px-2 py-1 text-[11.5px] font-medium text-info">
                  {item.rankChange}
                </div>
              )}
            </div>
          </motion.li>
        ))}
      </ol>
    </div>
  );
}
