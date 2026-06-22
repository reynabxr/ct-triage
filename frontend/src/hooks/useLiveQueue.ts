import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { EscalatedCaseViewModel, QueueCaseRecord, QueueEventRecord } from "@/lib/queue-models";
import { deriveEscalatedCaseViewModel } from "@/lib/queue-models";

interface QueueApiResponse {
  activeQueue: QueueCaseRecord[];
  escalatedCases: QueueCaseRecord[];
  allCases: QueueCaseRecord[];
  summary: {
    activeCount: number;
    escalatedCount: number;
    latestQueueVersion: number | null;
    currentTick: number | null;
  };
}

interface ReasoningEventsApiResponse {
  events: QueueEventRecord[];
}

interface SimulationStatusResponse {
  run_id?: string | null;
  status?: string;
  total_rows?: number;
  completed_rows?: number;
  current_case_id?: string | null;
  current_row_number?: number | null;
  message?: string | null;
  departures?: number;
  speed_multiplier?: number;
}

const QUEUE_ENDPOINT = "/api/queue";
const REASONING_EVENTS_ENDPOINT = "/api/reasoning-events";
const SIMULATION_RUN_ENDPOINT = "/api/simulation/run";
const SIMULATION_STATUS_ENDPOINT = "/api/simulation/status";
const SIMULATION_RESET_ENDPOINT = "/api/simulation/reset";
const SIMULATION_SPEED_ENDPOINT = "/api/simulation/speed";
const HUMAN_DECISION_ENDPOINT = "/api/human-decisions";
type HumanDecision = "approve" | "return_to_review";

const parseJson = async <T>(response: Response): Promise<T> => {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
};

const buildEscalatedCases = (
  escalatedRecords: QueueCaseRecord[],
  queueEvents: QueueEventRecord[],
): EscalatedCaseViewModel[] => {
  const latestModeratorByCaseId = new Map<string, QueueEventRecord>();
  const latestReviewByCaseId = new Map<string, QueueEventRecord>();

  for (const event of queueEvents) {
    if (!event.caseId) continue;
    if (event.eventType === "moderator_decision" && !latestModeratorByCaseId.has(event.caseId)) {
      latestModeratorByCaseId.set(event.caseId, event);
      continue;
    }
    if (
      event.eventType === "clinical_urgency_determined" &&
      !latestReviewByCaseId.has(event.caseId)
    ) {
      latestReviewByCaseId.set(event.caseId, event);
    }
  }

  return escalatedRecords
    .map((record) => {
      const moderatorEvent = latestModeratorByCaseId.get(record.caseId);
      const reviewEvent = latestReviewByCaseId.get(record.caseId);
      const moderatorDetails = moderatorEvent?.details ?? {};
      const reviewDetails = reviewEvent?.details ?? {};
      const confidenceSource = moderatorEvent ? moderatorDetails : reviewDetails;
      const urgencySource = moderatorEvent ? moderatorDetails : reviewDetails;
      const view = deriveEscalatedCaseViewModel(record);

      return {
        ...view,
        urgencyScore:
          typeof urgencySource.urgency_score === "number"
            ? urgencySource.urgency_score
            : view.urgencyScore,
        confidenceLevel:
          typeof confidenceSource.confidence === "number"
            ? confidenceSource.confidence
            : view.confidenceLevel,
        escalationReason:
          typeof moderatorDetails.reason_summary === "string"
            ? moderatorDetails.reason_summary
            : moderatorEvent
              ? "Moderator decision recorded without summary."
              : typeof reviewDetails.reasoning_summary === "string"
                ? `${reviewDetails.reasoning_summary} Moderator review pending.`
                : "Moderator review pending.",
      };
    })
    .sort((a, b) => a.caseId.localeCompare(b.caseId));
};

export const useLiveQueue = () => {
  const [caseRecords, setCaseRecords] = useState<QueueCaseRecord[]>([]);
  const [queueEvents, setQueueEvents] = useState<QueueEventRecord[]>([]);
  const [fastMode, setFastMode] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [simulationPending, setSimulationPending] = useState(false);
  const [humanDecisionPending, setHumanDecisionPending] = useState<Record<string, HumanDecision | undefined>>({});
  const [simulationStatus, setSimulationStatus] = useState<SimulationStatusResponse>({ status: "idle" });
  const refreshInFlight = useRef(false);
  const initialized = useRef(false);

  const refresh = useCallback(async () => {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;

    try {
      const [queuePayload, reasoningPayload, statusPayload] = await Promise.all([
        fetch(QUEUE_ENDPOINT, { headers: { accept: "application/json" } }).then((response) =>
          parseJson<QueueApiResponse>(response),
        ),
        fetch(REASONING_EVENTS_ENDPOINT, { headers: { accept: "application/json" } }).then(
          (response) => parseJson<ReasoningEventsApiResponse>(response),
        ),
        fetch(SIMULATION_STATUS_ENDPOINT, { headers: { accept: "application/json" } }).then((response) =>
          parseJson<SimulationStatusResponse>(response),
        ),
      ]);

      setCaseRecords(queuePayload.allCases);
      setQueueEvents(reasoningPayload.events);
      setSimulationStatus(statusPayload);
      setFastMode((statusPayload.speed_multiplier ?? 1) > 1);
      setLoadError(null);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load live queue data";
      setLoadError(message);
    } finally {
      setIsLoading(false);
      refreshInFlight.current = false;
    }
  }, []);

  useEffect(() => {
    const initialize = async () => {
      if (!initialized.current) {
        initialized.current = true;
        try {
          const statusPayload = await fetch(SIMULATION_STATUS_ENDPOINT, {
            headers: { accept: "application/json" },
          }).then((response) => parseJson<SimulationStatusResponse>(response));
          setSimulationStatus(statusPayload);
          setFastMode((statusPayload.speed_multiplier ?? 1) > 1);

          if (statusPayload.status !== "running" && statusPayload.status !== "stopping") {
            await fetch(SIMULATION_RESET_ENDPOINT, {
              method: "POST",
              headers: { accept: "application/json" },
            }).then((response) => parseJson<SimulationStatusResponse>(response));
          }
        } catch (error) {
          const message = error instanceof Error ? error.message : "Failed to initialize live queue";
          setLoadError(message);
        }
      }
      await refresh();
    };

    void initialize();

    const interval = window.setInterval(() => {
      void refresh();
    }, fastMode ? 2000 : 5000);

    return () => {
      window.clearInterval(interval);
    };
  }, [fastMode, refresh]);

  const queue = useMemo(
    () =>
      caseRecords
        .filter((record) => record.status === "pending" || record.status === "routed" || record.status === "reviewed")
        .sort(
          (a, b) =>
            (a.queuePosition ?? Number.MAX_SAFE_INTEGER) - (b.queuePosition ?? Number.MAX_SAFE_INTEGER),
        ),
    [caseRecords],
  );

  const escalatedCases = useMemo(
    () => buildEscalatedCases(caseRecords.filter((record) => record.status === "escalated"), queueEvents),
    [caseRecords, queueEvents],
  );

  const explainCase = useCallback(
    (caseId: string) => {
      const record = caseRecords.find((candidate) => candidate.caseId === caseId);
      if (!record) return "Case not found.";

      const reviewEvent = queueEvents.find(
        (event) => event.caseId === caseId && event.eventType === "clinical_urgency_determined",
      );
      const moderatorEvent = queueEvents.find(
        (event) => event.caseId === caseId && event.eventType === "moderator_decision",
      );

      const reviewSummary =
        typeof reviewEvent?.details.reasoning_summary === "string"
          ? reviewEvent.details.reasoning_summary
          : "Review reasoning is not available yet.";
      const moderatorSummary =
        typeof moderatorEvent?.details.reason_summary === "string"
          ? moderatorEvent.details.reason_summary
          : "Moderator reasoning is not available yet.";

      return `${record.caseId} (${record.patientCode ?? "unknown patient"})\nReview: ${reviewSummary}\nModerator: ${moderatorSummary}`;
    },
    [caseRecords, queueEvents],
  );


  const startSimulation = useCallback(async () => {
    if (simulationPending || simulationStatus.status === "running" || simulationStatus.status === "stopping") {
      return;
    }

    setSimulationPending(true);
    try {
      const statusPayload = await fetch(SIMULATION_RUN_ENDPOINT, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          limit: 9,
          arrival_gap_seconds: fastMode ? 1.5 : 4,
          start_delay_seconds: 0,
          top_leave_after_seconds: fastMode ? 4 : 12,
        }),
      }).then((response) => parseJson<SimulationStatusResponse>(response));
      setSimulationStatus(statusPayload);
      await refresh();
      setLoadError(null);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to start simulation";
      setLoadError(message);
      throw error;
    } finally {
      setSimulationPending(false);
    }
  }, [fastMode, refresh, simulationPending, simulationStatus.status]);

  const toggleSpeed = useCallback(async () => {
    const nextFastMode = !fastMode;
    setFastMode(nextFastMode);

    try {
      const statusPayload = await fetch(SIMULATION_SPEED_ENDPOINT, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ speed_multiplier: nextFastMode ? 3 : 1 }),
      }).then((response) => parseJson<SimulationStatusResponse>(response));
      setSimulationStatus(statusPayload);
      await refresh();
    } catch (error) {
      setFastMode(fastMode);
      const message = error instanceof Error ? error.message : "Failed to update simulation speed";
      setLoadError(message);
    }
  }, [fastMode, refresh]);

  const submitHumanDecision = useCallback(
    async (caseId: string, decision: HumanDecision, notes?: string) => {
      setHumanDecisionPending((current) => ({ ...current, [caseId]: decision }));
      try {
        await fetch(HUMAN_DECISION_ENDPOINT, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            case_id: caseId,
            decision,
            notes: notes?.trim() ? notes.trim() : undefined,
          }),
        }).then((response) => parseJson<{ result: unknown }>(response));
        await refresh();
        setLoadError(null);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Failed to submit human decision";
        setLoadError(message);
        throw error;
      } finally {
        setHumanDecisionPending((current) => {
          const next = { ...current };
          delete next[caseId];
          return next;
        });
      }
    },
    [refresh],
  );

  return {
    caseRecords,
    queue,
    escalatedCases,
    queueEvents,
    isLoading,
    loadError,
    refresh,
    explainCase,
    startSimulation,
    simulationPending,
    simulationStatus,
    fastMode,
    toggleSpeed,
    humanDecisionPending,
    submitHumanDecision,
  };
};
