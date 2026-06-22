import { Stethoscope } from "lucide-react";
import type { ClinicalUrgencyLevel, QueueCaseRecord, QueueEventRecord } from "@/lib/queue-models";

const urgencyColor: Record<ClinicalUrgencyLevel, string> = {
  CRITICAL: "text-risk-critical bg-risk-critical-soft",
  HIGH: "text-orange-700 bg-orange-100",
  MEDIUM: "text-amber-700 bg-amber-100",
  LOW: "text-risk-stable bg-risk-stable/10",
};

export function CaseDetailPanel({
  selectedCaseId,
  caseRecords,
  queueEvents,
}: {
  selectedCaseId: string | null;
  caseRecords: QueueCaseRecord[];
  queueEvents: QueueEventRecord[];
}) {
  const record = selectedCaseId
    ? caseRecords.find((r) => r.caseId === selectedCaseId) ?? null
    : null;

  const reviewEvent = selectedCaseId
    ? queueEvents.find(
        (e) => e.caseId === selectedCaseId && e.eventType === "clinical_urgency_determined",
      ) ?? null
    : null;

  const moderatorEvent = selectedCaseId
    ? queueEvents.find(
        (e) => e.caseId === selectedCaseId && e.eventType === "moderator_decision",
      ) ?? null
    : null;

  return (
    <div className="flex h-full flex-col rounded-2xl border border-border bg-surface shadow-soft">
      <div className="flex items-center gap-2.5 border-b border-border px-4 py-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Stethoscope className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold tracking-tight text-foreground">Case Detail</div>
          <div className="text-[11px] text-muted-foreground">
            {record ? `Patient ${record.patientCode}` : "Select a case from the queue"}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {!record ? (
          <div className="flex h-full items-center justify-center text-center">
            <p className="text-sm text-muted-foreground">
              Click a row in the queue to see AI reasoning for that case.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <Section title="Patient">
              <Row label="Patient ID" value={record.patientCode ?? "—"} />
              <Row label="Case ID" value={record.caseId} />
              <Row label="Status" value={record.status} />
            </Section>

            <Section title="Clinical review">
              {reviewEvent ? (
                <>
                  <UrgencyRow urgency={reviewEvent.details.clinical_urgency as ClinicalUrgencyLevel | undefined} />
                  <Row
                    label="Confidence"
                    value={
                      typeof reviewEvent.details.confidence === "number"
                        ? `${Math.round(reviewEvent.details.confidence * 100)}%`
                        : "—"
                    }
                  />
                  <RedFlagRow redFlags={reviewEvent.details.red_flags} />
                  <Row
                    label="Reasoning"
                    value={
                      typeof reviewEvent.details.reasoning_summary === "string"
                        ? reviewEvent.details.reasoning_summary
                        : "—"
                    }
                    multiline
                  />
                </>
              ) : (
                <p className="text-xs text-muted-foreground">Review pending…</p>
              )}
            </Section>

            <Section title="Moderator decision">
              {moderatorEvent ? (
                <>
                  <Row
                    label="Placement"
                    value={
                      typeof moderatorEvent.details.placement_action === "string"
                        ? moderatorEvent.details.placement_action.replace(/_/g, " ")
                        : "—"
                    }
                  />
                  {moderatorEvent.details.anchor_case_id && (
                    <Row label="Anchor case" value={String(moderatorEvent.details.anchor_case_id)} />
                  )}
                  <Row
                    label="Comparisons"
                    value={
                      typeof moderatorEvent.details.comparison_count === "number"
                        ? String(moderatorEvent.details.comparison_count)
                        : "—"
                    }
                  />
                  <Row
                    label="Summary"
                    value={
                      typeof moderatorEvent.details.reason_summary === "string"
                        ? moderatorEvent.details.reason_summary
                        : "—"
                    }
                    multiline
                  />
                  {moderatorEvent.details.needs_human_review === true && (
                    <div className="mt-1 rounded-md bg-risk-critical-soft px-2.5 py-1.5 text-xs font-medium text-risk-critical">
                      Escalated for human review
                    </div>
                  )}
                </>
              ) : (
                <p className="text-xs text-muted-foreground">Moderator decision pending…</p>
              )}
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </div>
      <div className="space-y-1 rounded-xl border border-border bg-surface-elevated/50 px-3 py-2.5">
        {children}
      </div>
    </div>
  );
}

function Row({ label, value, multiline }: { label: string; value: string; multiline?: boolean }) {
  return (
    <div className={multiline ? "space-y-1.5" : "flex items-baseline justify-between gap-2"}>
      <span className="text-[11px] text-muted-foreground shrink-0">{label}</span>
      <span className={`text-[12px] text-foreground ${multiline ? "" : "text-right"}`}>{value}</span>
    </div>
  );
}

function UrgencyRow({ urgency }: { urgency: ClinicalUrgencyLevel | undefined }) {
  if (!urgency) return <Row label="Urgency" value="—" />;
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[11px] text-muted-foreground shrink-0">Urgency</span>
      <span className={`rounded px-2 py-0.5 text-[11px] font-semibold ${urgencyColor[urgency]}`}>
        {urgency}
      </span>
    </div>
  );
}

function RedFlagRow({ redFlags }: { redFlags: unknown }) {
  const flags = Array.isArray(redFlags) ? (redFlags as string[]) : [];
  if (flags.length === 0) return null;
  return (
    <div className="space-y-0.5">
      <span className="text-[11px] text-muted-foreground">Red flags</span>
      <div className="flex flex-wrap gap-1 pt-0.5">
        {flags.map((flag) => (
          <span
            key={flag}
            className="rounded bg-risk-critical-soft px-1.5 py-0.5 text-[10px] text-risk-critical"
          >
            {flag.replace(/_/g, " ")}
          </span>
        ))}
      </div>
    </div>
  );
}
