import { motion } from "framer-motion";
import { GitBranch, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "@tanstack/react-router";
import { Input } from "@/components/ui/input";
import {
  deriveQueueEventViewModel,
  type EventAffectedMovement,
  type QueueCaseRecord,
  type QueueEventRecord,
} from "@/lib/queue-models";

const eventTypeLabel = (eventType: string) =>
  eventType.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());

const normalizeSearchValue = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");

const matchesPatientSearch = (
  entry: ReturnType<typeof deriveQueueEventViewModel>,
  search: string,
) => {
  const patientName = entry.patientName ?? "";
  const patientCode = entry.patientCode ?? "";
  const normalizedSearch = search.toLowerCase();
  const compactSearch = normalizeSearchValue(search);
  const affectedMovements = entry.affectedMovements ?? [];

  return (
    `${patientName} ${patientCode}`.toLowerCase().includes(normalizedSearch) ||
    normalizeSearchValue(patientName).includes(compactSearch) ||
    normalizeSearchValue(patientCode).includes(compactSearch) ||
    affectedMovements.some((movement) => matchesAffectedMovementSearch(movement, search))
  );
};

const matchesAffectedMovementSearch = (movement: EventAffectedMovement, search: string) => {
  const normalizedSearch = search.toLowerCase();
  const compactSearch = normalizeSearchValue(search);
  const affectedPatient = `${movement.patientName} ${movement.patientCode}`;

  return (
    affectedPatient.toLowerCase().includes(normalizedSearch) ||
    normalizeSearchValue(movement.patientName).includes(compactSearch) ||
    normalizeSearchValue(movement.patientCode).includes(compactSearch)
  );
};

const matchesAffectedMovementPatient = (
  movement: EventAffectedMovement,
  patientCode?: string,
  patientName?: string,
) => {
  const matchesCode = patientCode ? movement.patientCode === patientCode : false;
  const matchesName = patientName
    ? movement.patientName.toLowerCase() === patientName.toLowerCase()
    : false;
  return matchesCode || matchesName;
};

const matchesEntryPatient = (
  entry: ReturnType<typeof deriveQueueEventViewModel>,
  patientCode?: string,
  patientName?: string,
) => {
  const matchesCode = patientCode ? entry.patientCode === patientCode : false;
  const matchesName = patientName
    ? entry.patientName?.toLowerCase() === patientName.toLowerCase()
    : false;
  const matchesAffected = (entry.affectedMovements ?? []).some((movement) =>
    matchesAffectedMovementPatient(movement, patientCode, patientName),
  );

  return matchesCode || matchesName || matchesAffected;
};

const affectedRankChange = (movement: EventAffectedMovement) =>
  `#${movement.fromRank} -> #${movement.toRank}`;

export function ReasoningLog({
  entries,
  caseRecords: _caseRecords,
  caseId,
  patientCode,
  patientName,
  eventId,
}: {
  entries: QueueEventRecord[];
  caseRecords?: QueueCaseRecord[];
  caseId?: string;
  patientCode?: string;
  patientName?: string;
  eventId?: string;
}) {
  const itemRefs = useRef<Record<string, HTMLLIElement | null>>({});
  const [patientSearch, setPatientSearch] = useState("");
  const eventEntries = useMemo(() => entries.map((entry) => deriveQueueEventViewModel(entry)), [entries]);
  const hasFilter = Boolean(caseId || patientCode || patientName || eventId);
  const exactMode = Boolean(eventId);

  const patientEntries = useMemo(() => {
    if (!hasFilter) return eventEntries;

    return eventEntries.filter((entry) => {
      const matchesPatient =
        (caseId ? entry.caseId === caseId : false) || matchesEntryPatient(entry, patientCode, patientName);

      if (eventId) {
        return entry.id === eventId && (!caseId && !patientCode && !patientName ? true : matchesPatient);
      }

      return matchesPatient;
    });
  }, [caseId, eventEntries, eventId, hasFilter, patientCode, patientName]);

  const selectedEntry = useMemo(() => {
    if (!patientEntries.length) return undefined;
    if (eventId) {
      return patientEntries.find((entry) => entry.id === eventId);
    }
    return patientEntries[0];
  }, [eventId, patientEntries]);

  useEffect(() => {
    if (!selectedEntry) return;
    const node = itemRefs.current[selectedEntry.id];
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [selectedEntry]);

  const baseVisibleEntries = exactMode
    ? selectedEntry
      ? [selectedEntry]
      : []
    : hasFilter
      ? patientEntries
      : eventEntries;

  const normalizedPatientSearch = patientSearch.trim().toLowerCase();
  const visibleEntries =
    exactMode || !normalizedPatientSearch
      ? baseVisibleEntries
      : baseVisibleEntries.filter((entry) => matchesPatientSearch(entry, normalizedPatientSearch));

  return (
    <div className="rounded-2xl border border-border bg-surface p-4 shadow-soft">
      <div className="flex items-center gap-3 border-b border-border pb-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-info-soft text-info">
          <GitBranch className="h-4 w-4" />
        </div>
        <div>
          <div className="text-lg font-semibold tracking-tight text-foreground">Reasoning Log</div>
          <div className="text-[12px] text-muted-foreground">
            Full activity history — assessments, placements, and position changes
          </div>
        </div>
      </div>

      {hasFilter && (
        <div className="mt-3 rounded-md border border-border bg-background px-3 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-medium text-foreground">
                {exactMode ? "Showing specific event" : "Activity log for this patient"}
              </div>
              <div className="text-[13px] text-muted-foreground">
                <span>{patientName || "Unknown patient"}</span>
                {caseId ? (
                  <span className="ml-2 inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                    {caseId}
                  </span>
                ) : null}
                {patientCode ? (
                  <span className="ml-2 inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                    {patientCode}
                  </span>
                ) : null}
              </div>
            </div>
          </div>

          {exactMode && patientCode && patientName && (
            <div className="mt-2">
              <Link
                to="/reasoning"
                search={{ caseId, patientCode, patientName, eventId: undefined }}
                className="text-[12px] font-medium text-primary hover:underline"
              >
                View full reasoning log for this patient
              </Link>
            </div>
          )}
        </div>
      )}

      {!exactMode && (
        <div className="mt-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={patientSearch}
              onChange={(event) => setPatientSearch(event.target.value)}
              placeholder="Search patient name or code"
              className="h-9 pl-9 text-sm"
            />
          </div>
          {normalizedPatientSearch && (
            <div className="mt-1 text-[12px] text-muted-foreground">
              {visibleEntries.length} matching log {visibleEntries.length === 1 ? "entry" : "entries"}
            </div>
          )}
        </div>
      )}

      <ol className="mt-4 space-y-3 overflow-y-auto max-h-[70vh]">
        {visibleEntries.map((entry) => {
          const isSelected = selectedEntry?.id === entry.id;
          const isSearchMatch = normalizedPatientSearch && matchesPatientSearch(entry, normalizedPatientSearch);
          const isRoutePatientMatch = matchesEntryPatient(entry, patientCode, patientName);
          const isPatientMatch = isSearchMatch || isRoutePatientMatch;

          return (
            <motion.li
              key={entry.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              ref={(element) => {
                itemRefs.current[entry.id] = element;
              }}
              className={`rounded-md border p-3 ${
                isSelected || isPatientMatch
                  ? "border-primary bg-primary/10 ring-1 ring-primary/30"
                  : "border-border bg-background"
              }`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-foreground">{entry.title}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <div className="inline-flex rounded-full border border-border bg-surface px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                      {eventTypeLabel(entry.eventType)}
                    </div>
                    {entry.patientCode ? (
                      <div className="inline-flex rounded-full border border-border bg-background px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                        {entry.patientCode}
                      </div>
                    ) : null}
                    {isPatientMatch ? (
                      <div className="inline-flex rounded-full bg-primary px-2 py-0.5 text-[11px] font-medium text-primary-foreground">
                        Match
                      </div>
                    ) : null}
                  </div>
                </div>
                <div className="text-[11px] text-muted-foreground tabular-nums">
                  {entry.timestamp.toLocaleString()}
                </div>
              </div>

              {entry.why.length > 0 && (
                <div className="mt-2 text-[13px] text-muted-foreground">
                  <div className="font-medium text-[12px] text-foreground">Why this changed</div>
                  <ul className="mt-1 list-inside list-disc pl-3">
                    {entry.why.map((reason, reasonIndex) => (
                      <li key={reasonIndex}>{reason}</li>
                    ))}
                  </ul>
                </div>
              )}

              {entry.effect.length > 0 && (
                <div className="mt-2">
                  <div className="font-medium text-[12px] text-foreground">
                    {entry.eventType === "rank_changed" || entry.eventType === "placement_applied"
                      ? "Position change"
                      : "What changed"}
                  </div>
                  <div className="mt-1 space-y-1">
                    {entry.effect.map((effect, effectIndex) => (
                      <div
                        key={effectIndex}
                        className="rounded px-2 py-1 text-[12px] bg-info-soft/40 text-info font-medium"
                      >
                        {effect}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {entry.queueState.length > 0 && (
                <div className="mt-2 text-[12px] text-muted-foreground">
                  <div className="font-medium text-[12px] text-foreground">Queue context</div>
                  <ul className="mt-1 list-inside list-disc pl-3">
                    {entry.queueState.map((state, stateIndex) => (
                      <li key={stateIndex}>{state}</li>
                    ))}
                  </ul>
                </div>
              )}

              {entry.affectedMovements && entry.affectedMovements.length > 0 && (
                <div className="mt-3">
                  <div className="font-medium text-[12px] text-foreground">Affected patients</div>
                  <div className="mt-1 space-y-1.5">
                    {entry.affectedMovements.map((movement) => {
                      const movementMatch =
                        (normalizedPatientSearch && matchesAffectedMovementSearch(movement, normalizedPatientSearch)) ||
                        matchesAffectedMovementPatient(movement, patientCode, patientName);

                      return (
                        <div
                          key={`${entry.id}-${movement.caseId}-${movement.fromRank}-${movement.toRank}`}
                          className={`rounded-md border px-2.5 py-2 ${
                            movementMatch
                              ? "border-primary bg-primary/10 ring-1 ring-primary/30"
                              : "border-border bg-surface"
                          }`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className="text-[12px] font-medium text-foreground">
                                  {movement.patientName}
                                </span>
                                {movementMatch ? (
                                  <span className="rounded-full bg-primary px-1.5 py-0.5 text-[10px] font-medium text-primary-foreground">
                                    Match
                                  </span>
                                ) : null}
                              </div>
                              <div className="font-mono text-[10.5px] text-muted-foreground">
                                {movement.patientCode}
                              </div>
                            </div>
                            <div className="rounded bg-info-soft/50 px-2 py-1 text-[11.5px] font-medium text-info">
                              {affectedRankChange(movement)}
                            </div>
                          </div>
                          <div className="mt-1 text-[12px] text-muted-foreground">
                            {movement.reason}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </motion.li>
          );
        })}
      </ol>
    </div>
  );
}

export default ReasoningLog;
