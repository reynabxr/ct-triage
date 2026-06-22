import { AnimatePresence, motion } from "framer-motion";
import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { deriveQueueCaseViewModel, isOverTarget, type ClinicalUrgencyLevel, type QueueCaseRecord, type QueueEventRecord } from "@/lib/queue-models";

interface SimulationStatus {
  status?: string;
  total_rows?: number;
  completed_rows?: number;
  current_case_id?: string | null;
}

const urgencyBadgeClass = (level: ClinicalUrgencyLevel) => {
  switch (level) {
    case "CRITICAL": return "bg-risk-critical-soft text-risk-critical";
    case "HIGH": return "bg-orange-100 text-orange-700";
    case "MEDIUM": return "bg-amber-100 text-amber-700";
    case "LOW": return "bg-risk-stable/10 text-risk-stable";
  }
};

export function LiveQueueTable({
  queue,
  reasoningEntries,
  selectedCaseId,
  onSelectCase,
  simulationStatus,
  isPolling,
}: {
  queue: QueueCaseRecord[];
  reasoningEntries: QueueEventRecord[];
  selectedCaseId?: string | null;
  onSelectCase?: (caseId: string) => void;
  simulationStatus?: SimulationStatus;
  isPolling?: boolean;
}) {
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [pollPulse, setPollPulse] = useState(false);

  useEffect(() => {
    if (!isPolling) return;
    setLastUpdated(new Date());
    setPollPulse(true);
    const t = setTimeout(() => setPollPulse(false), 600);
    return () => clearTimeout(t);
  }, [isPolling, queue, reasoningEntries]);

  const total = simulationStatus?.total_rows ?? 0;
  const completed = simulationStatus?.completed_rows ?? 0;
  const currentCaseId = simulationStatus?.current_case_id ?? null;
  const isRunning = simulationStatus?.status === "running";
  const progressPct = total > 0 ? Math.round((completed / total) * 100) : 0;
  const latestReviewByCaseId = new Map<string, QueueEventRecord>();
  const latestModeratorByCaseId = new Map<string, QueueEventRecord>();

  for (const entry of reasoningEntries) {
    if (!entry.caseId) continue;
    if (entry.eventType === "clinical_urgency_determined" && !latestReviewByCaseId.has(entry.caseId)) {
      latestReviewByCaseId.set(entry.caseId, entry);
    }
    if (entry.eventType === "moderator_decision" && !latestModeratorByCaseId.has(entry.caseId)) {
      latestModeratorByCaseId.set(entry.caseId, entry);
    }
  }

  return (
    <div
      id="queue"
      className="overflow-hidden rounded-2xl border border-border bg-surface shadow-soft"
    >
      <div className="border-b border-border px-5 py-3.5 space-y-2">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold tracking-tight text-foreground">
              Live CT Queue
            </h3>
            <p className="text-xs text-muted-foreground">
              {isRunning && currentCaseId
                ? `Processing case ${currentCaseId}…`
                : isRunning
                  ? "Simulation running — waiting for next case…"
                  : "New cases enter one by one and are placed by the Band workflow"}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {lastUpdated && (
              <span className="text-[10px] tabular-nums text-muted-foreground" suppressHydrationWarning>
                Updated {lastUpdated.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
            )}
            <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className={`h-1.5 w-1.5 rounded-full transition-colors duration-300 ${pollPulse ? "bg-primary" : "bg-risk-stable"} ${isRunning ? "animate-pulse" : ""}`} />
              {isRunning ? "Running" : "Live"}
            </span>
          </div>
        </div>
        {isRunning && total > 0 && (
          <div className="flex items-center gap-2">
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-border">
              <motion.div
                className="h-full rounded-full bg-primary"
                animate={{ width: `${progressPct}%` }}
                transition={{ type: "spring", stiffness: 120, damping: 20 }}
              />
            </div>
            <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
              {completed} / {total} cases
            </span>
          </div>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[880px] table-fixed text-sm">
          <colgroup>
            <col className="w-16" />
            <col className="w-[180px]" />
            <col className="w-[180px]" />
            <col className="w-[220px]" />
            <col className="w-[132px]" />
            <col className="w-[160px]" />
          </colgroup>
          <thead>
            <tr className="bg-surface-elevated/60 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
              <th className="whitespace-nowrap py-2.5 pl-5 pr-3">Rank</th>
              <th className="whitespace-nowrap py-2.5 pr-4">Patient</th>
              <th className="whitespace-nowrap py-2.5 pr-4">Chief Complaint (ICD-10)</th>
              <th className="whitespace-nowrap py-2.5 pr-4">Review reasoning</th>
              <th className="whitespace-nowrap py-2.5 pr-4">Time waited</th>
              <th className="whitespace-nowrap py-2.5 pr-5">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {queue.length === 0 && (
              <tr>
                <td colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                  No cases in queue yet. Start the simulation to feed in new cases.
                </td>
              </tr>
            )}
            <AnimatePresence initial={false}>
              {queue.map((record, idx) => {
                const view = deriveQueueCaseViewModel(record);
                const over = isOverTarget(record);
                const reviewDetails = latestReviewByCaseId.get(record.caseId)?.details ?? {};
                const moderatorDetails = latestModeratorByCaseId.get(record.caseId)?.details ?? {};
                const reviewSummary =
                  typeof reviewDetails.reasoning_summary === "string"
                    ? reviewDetails.reasoning_summary
                    : view.summaryText;
                const confidence =
                  typeof moderatorDetails.confidence === "number"
                    ? moderatorDetails.confidence
                    : typeof reviewDetails.confidence === "number"
                      ? reviewDetails.confidence
                      : record.payload.confidenceLevel ?? null;
                return (
                  <motion.tr
                    key={record.caseId}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ type: "spring", stiffness: 320, damping: 30 }}
                    onClick={() => onSelectCase?.(record.caseId)}
                    className={`group border-t border-border transition-colors cursor-pointer hover:bg-accent/40 ${selectedCaseId === record.caseId ? "bg-accent/60" : ""}`}
                  >
                    <td
                      className={`border-l-[3px] py-3 pl-5 pr-3 font-mono text-xs text-muted-foreground ${
                        over ? "border-l-risk-critical" : "border-l-transparent"
                      }`}
                    >
                      {record.queuePosition ?? idx + 1}
                    </td>
                    <td className="py-3 pr-4">
                      <Link
                        to="/reasoning"
                        search={{
                          caseId: record.caseId,
                          patientCode: view.patientCode,
                          patientName: view.displayName,
                          eventId: undefined,
                        }}
                        className="block space-y-1.5"
                      >
                        <div className="flex items-center gap-1.5">
                          {(() => {
                            const urgency = typeof reviewDetails.clinical_urgency === "string"
                              ? (reviewDetails.clinical_urgency as ClinicalUrgencyLevel)
                              : null;
                            return urgency ? (
                              <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold ${urgencyBadgeClass(urgency)}`}>
                                {urgency}
                              </span>
                            ) : (
                              <span className="inline-block rounded px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground border border-border">
                                Pending
                              </span>
                            );
                          })()}
                        </div>
                        <div>
                          <div className="text-[11px] font-medium text-foreground">Patient ID: {view.patientCode}</div>
                          <div className="text-[10px] text-muted-foreground">Case ID: {record.caseId}</div>
                        </div>
                      </Link>
                    </td>
                    <td className="py-3 pr-4 text-foreground">{view.scanLabel}</td>
                    <td className="py-3 pr-4">
                        <div
                          className="line-clamp-2 text-[12.5px] text-muted-foreground"
                        title={reviewSummary}
                      >
                        {reviewSummary}
                      </div>
                    </td>
                    <td className="whitespace-nowrap py-3 pr-4 tabular-nums text-foreground">
                      {view.waitedMinutes != null ? (
                        <>
                          {view.waitedMinutes}m
                          <span className="ml-1 text-[11px] text-muted-foreground">
                            / {view.targetMinutes}m
                          </span>
                        </>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="py-3 pr-5">
                      <div className="text-xs font-semibold text-foreground">
                        {confidence == null ? "Pending" : `${Math.round(confidence * 100)}%`}
                      </div>
                    </td>
                  </motion.tr>
                );
              })}
            </AnimatePresence>
          </tbody>
        </table>
      </div>
    </div>
  );
}
