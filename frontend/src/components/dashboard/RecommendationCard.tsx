import { useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, Loader2, RotateCcw, ShieldAlert } from "lucide-react";
import type { ClinicalUrgencyLevel, EscalatedCaseViewModel } from "@/lib/queue-models";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

type HumanDecision = "approve" | "return_to_review";

const urgencyChipClass = (level: ClinicalUrgencyLevel) => {
  switch (level) {
    case "CRITICAL": return "border-risk-critical text-risk-critical";
    case "HIGH": return "border-orange-400 text-orange-600";
    case "MEDIUM": return "border-amber-400 text-amber-600";
    case "LOW": return "border-border text-muted-foreground";
  }
};

export function RecommendationCard({
  cases,
  pendingDecisions,
  onSubmitDecision,
}: {
  cases: EscalatedCaseViewModel[];
  pendingDecisions: Record<string, HumanDecision | undefined>;
  onSubmitDecision: (caseId: string, decision: HumanDecision, notes?: string) => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  const [selectedCase, setSelectedCase] = useState<EscalatedCaseViewModel | null>(null);

  const submitDecision = async (caseId: string, decision: HumanDecision, notes?: string) => {
    setError(null);
    try {
      await onSubmitDecision(caseId, decision, notes);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to submit human decision");
    }
  };

  if (cases.length === 0) {
    return (
      <div className="relative overflow-hidden rounded-xl border border-border bg-surface shadow-soft">
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/40 to-transparent" />
        <div className="flex min-h-[132px] items-center gap-4 p-5">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-risk-stable/10 text-risk-stable">
            <ShieldAlert className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-base font-semibold tracking-tight text-foreground">No escalated cases</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Human review queue is clear.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <section className="relative overflow-hidden rounded-xl border border-border bg-surface shadow-soft">
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/40 to-transparent" />
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3.5">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-risk-critical">
            <AlertTriangle className="h-3.5 w-3.5" />
            Human review
          </div>
          <h2 className="mt-1 text-base font-semibold tracking-tight text-foreground">
            {cases.length} case{cases.length === 1 ? "" : "s"} awaiting decision
          </h2>
        </div>
        <div className="rounded-lg border border-border bg-surface-elevated/60 px-3 py-1.5 text-right">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Escalated</div>
          <div className="text-lg font-semibold tabular-nums text-risk-critical">{cases.length}</div>
        </div>
      </div>

      {error && (
        <div className="border-b border-risk-critical/20 bg-risk-critical-soft px-5 py-2 text-sm text-risk-critical">
          {error}
        </div>
      )}

      <div className="divide-y divide-border">
        {cases.map((item) => {
          const pendingDecision = pendingDecisions[item.caseId];
          const isPending = Boolean(pendingDecision);

          return (
            <article key={item.caseId} className="grid gap-3 px-5 py-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="truncate text-sm font-semibold text-foreground">{item.displayName}</h3>
                  {item.clinicalUrgency && (
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${urgencyChipClass(item.clinicalUrgency)}`}>
                      {item.clinicalUrgency}
                    </span>
                  )}
                  <span className="rounded-full bg-risk-critical-soft px-2 py-0.5 text-[10px] font-medium text-risk-critical">
                    Review
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span>{item.patientCode}</span>
                  <span>{item.scanLabel}</span>
                  <span className="flex items-center gap-1">
                    <Clock3 className="h-3 w-3" />
                    {item.humanDueAtLabel}
                  </span>
                  <span>{Math.round(item.confidenceLevel * 100)}% confidence</span>
                </div>
                <button
                  onClick={() => setSelectedCase(item)}
                  className="mt-2 block max-w-full text-left text-sm leading-snug text-muted-foreground hover:text-foreground transition-colors line-clamp-2 underline decoration-dashed decoration-muted-foreground hover:decoration-foreground"
                  title="Click to view full details"
                >
                  {item.escalationReason}
                </button>
              </div>

              <div className="flex shrink-0 flex-wrap gap-2 lg:justify-end">
                <Button
                  onClick={() => void submitDecision(item.caseId, "approve")}
                  disabled={isPending}
                  size="sm"
                  className="gap-2"
                >
                  {pendingDecision === "approve" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4" />
                  )}
                  {pendingDecision === "approve" ? "Approving..." : "Approve"}
                </Button>
                <ReturnToReviewDialog
                  caseItem={item}
                  disabled={isPending}
                  isPending={pendingDecision === "return_to_review"}
                  onSubmit={(notes) => submitDecision(item.caseId, "return_to_review", notes)}
                />
              </div>
            </article>
          );
        })}
      </div>

      <Dialog open={selectedCase !== null} onOpenChange={(open) => !open && setSelectedCase(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Case details</DialogTitle>
          </DialogHeader>
          {selectedCase && (
            <div className="space-y-4">
              <div>
                <div className="text-sm font-medium text-muted-foreground mb-1">Case</div>
                <div className="text-lg font-semibold text-foreground">{selectedCase.displayName}</div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Patient Code</div>
                  <div className="text-foreground">{selectedCase.patientCode}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Scan Type</div>
                  <div className="text-foreground">{selectedCase.scanLabel}</div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Clinical Urgency</div>
                  <div className="text-foreground">{selectedCase.clinicalUrgency || "N/A"}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Confidence</div>
                  <div className="text-foreground">{Math.round(selectedCase.confidenceLevel * 100)}%</div>
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-muted-foreground mb-1">Summary</div>
                <p className="text-foreground text-sm leading-relaxed">{selectedCase.summaryText}</p>
              </div>
              <div>
                <div className="text-sm font-medium text-muted-foreground mb-1">Escalation Reason</div>
                <p className="text-foreground text-sm leading-relaxed">{selectedCase.escalationReason}</p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Human Review Due</div>
                  <div className="text-foreground">{selectedCase.humanDueAtLabel}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Last Updated</div>
                  <div className="text-foreground">{selectedCase.updatedAtLabel}</div>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}

function ReturnToReviewDialog({
  caseItem,
  disabled,
  isPending,
  onSubmit,
}: {
  caseItem: EscalatedCaseViewModel;
  disabled: boolean;
  isPending: boolean;
  onSubmit: (notes?: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [notes, setNotes] = useState("");

  const submit = async () => {
    await onSubmit(notes);
    setNotes("");
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button disabled={disabled} variant="outline" size="sm" className="gap-2">
          {isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RotateCcw className="h-4 w-4" />
          )}
          {isPending ? "Returning..." : "Return"}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Return case to review</DialogTitle>
          <DialogDescription>
            Add optional context for {caseItem.displayName}. The notes will be included when the case re-enters review.
          </DialogDescription>
        </DialogHeader>
        <Textarea
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Optional notes for the review agents"
          className="min-h-[96px]"
        />
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={isPending}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void submit()} disabled={isPending} className="gap-2">
            {isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {isPending ? "Returning..." : "Return to review"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
