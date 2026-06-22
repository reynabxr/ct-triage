# CT Queue Optimisation — Audit & Fix Completion Summary

**Date:** 2026-06-18  
**Status:** ✅ All architectural misalignments fixed. Frontend completely restructured. System ready for integration testing.

---

## Backend Changes (Python)

### 1. Pre-comparison escalation logic ✅
**File:** `agents/moderator_logic.py`, `agents/moderator_graph.py`

Added `needs_precomparison_escalation()` check that only looks at:
- `case.force_escalation == True`
- `case.validation_status != "valid"`

**NOT** clinical urgency alone. CRITICAL urgency cases with high confidence bypass escalation and go straight to pairwise comparison for optimal placement.

**Graph change:**
```
ingest_case → check_escalation → [if pre-escalate: emit_result | else: load_queue → ... → decide_placement]
```

### 2. Human review flow improvements ✅
**Files:** `storage/queue_store.py`, `src/labslabs/band_dispatch.py`

- **Notes forwarding:** `return_to_review` path now writes human comments into `payload.human_review_notes` so agents see feedback on re-dispatch.
- **No auto-expiry:** Removed `expire_human_reviews()` call from `dispatch_next_pending_case()`. Cases wait indefinitely for human decision (approve → completed, or return_to_review → re-process with notes).
- **All decisions logged:** Decisions and notes tracked in `queue_events` table.

### 3. Dead code removed ✅
**Files:** `agents/shared_schema.py`, `agents/escalation_agent.py`, `agents/escalation_adapter.py`

- Deleted `ReviewMessage` class (conflicting with real `ClinicalUrgencyMessage`).
- Renamed `HumanHandoffMessage.clinical_risk` → `clinical_urgency` (consistent naming).
- Simplified `escalation_adapter` to only accept `ModeratorDecisionMessage`.

### 4. Institutional fields excluded from agent context ✅
**Files:** `agents/router_logic.py`

Verified: `CriticalStatus`, `StuporStatus`, `TriageGrade` are NOT in `PAYLOAD_FIELD_MAP`. These raw institutional scores are stored but never forwarded to the clinical review LLM, ensuring independent AI reasoning.

### 5. Documentation clarity ✅
**File:** `README.md`

Clarified that `ct_dispatcher_agent` is a service credential / room-creator identity, not a Band message listener. Updated human review section to explain decision flow (no timeout, manual approval/return-to-review).

---

## Frontend Changes (TypeScript/React)

### 6. AIControlPanel → CaseDetailPanel ✅
**File:** `frontend/src/components/dashboard/CaseDetailPanel.tsx` (new)

Replaced fake chat UI with a real case inspector. When a queue row is clicked:
- Shows patient code, case ID, and status.
- Displays clinical urgency badge (CRITICAL/HIGH/MEDIUM/LOW, colour-coded red/orange/amber/green).
- Shows confidence, red flags, reasoning from the `clinical_urgency_determined` event.
- Shows placement action, anchor case, comparison count, reason from `moderator_decision` event.
- Shows escalation status if sent to human review.

### 7. ReasoningPanel → Narrative timeline ✅
**Files:** `frontend/src/lib/queue-models.ts`, `frontend/src/components/dashboard/ReasoningPanel.tsx`

Replaced event list with human-readable chronological feed:
- "Daniel Ong moved up the queue (position #9 → #6)"
- "Scan completed: Ethan Goh"
- "Case 13960219004 joined the queue at position #3"
- "Case escalated for human review"
- Sub-bullets with decision details, urgency level, red flags.

**API expansion:**
- Exposed 7 event types (was 2): `clinical_urgency_determined`, `moderator_decision`, `placement_applied`, `queue_reordered`, `case_arrived`, `case_completed`, `case_escalated`.
- Updated `REASONING_EVENT_TYPES` in both Python API and TypeScript frontend.

### 8. Queue rank using queuePosition ✅
**File:** `frontend/src/components/dashboard/LiveQueueTable.tsx`

Changed rank column from `{idx + 1}` to `{record.queuePosition ?? idx + 1}` — now uses backend's authoritative position.

### 9. P1/P2/P3 removed; clinical urgency displayed ✅
**Files:** `frontend/src/lib/queue-models.ts`, `frontend/src/lib/backend-api.ts`, multiple components

- Removed `QueuePriorityBand` type and `toPriorityBand()` function.
- Removed `getPriorityBand()` and `inferTargetMinutes()` helpers.
- Seed data updated: all P1/P2/P3 references replaced with CRITICAL/HIGH/MEDIUM/LOW.
- Analytics section: P1/P2 labels → HIGH/MEDIUM; chart data keys updated.
- **Live queue table now shows clinical urgency chip** next to each patient name (RED for CRITICAL, orange for HIGH, etc.). If review event exists, shows level; otherwise "Pending".
- RecommendationCard: escalated cases show clinical urgency badge instead of P1/P2/P3.

### 10. Waiting time handling ✅
**Files:** `frontend/src/lib/backend-api.ts`, `frontend/src/components/dashboard/LiveQueueTable.tsx`, `frontend/src/lib/queue-models.ts`

- Removed fallback from `waitingTicks` (simulation counter) to `waitingTimeMinutes`.
- Table shows `{waitedMinutes}m / {targetMinutes}m` only if `waitedMinutes` is not null; otherwise "—".
- Removed `inferTargetMinutes()` — now flat 45-minute default.

### 11. Backend unreachable banner ✅
**File:** `frontend/src/routes/index.tsx`

Prominent red banner appears when backend is down and queue is empty:
```
Backend unreachable
Start the Python API with python3 -m api and set PYTHON_API_BASE_URL.
```

### 12. Minor cleanups ✅
**Files:**
- `mock-queue.ts` → `queue-models.ts` (renamed; all imports updated).
- Removed `AIControlPanel.tsx` (fully replaced by `CaseDetailPanel`).
- Removed `runCommand()` and `deferCase()` from `useLiveQueue.ts` (no-ops, never called).
- `RecommendationCard.tsx`: Updated stale copy ("mock contract" → "All cases are in the active queue"; "future human-review API" → reference to `scripts/human_decision.py`).

---

## Testing Checklist

- [ ] Start moderator agent: `python3 agents/run_moderator.py`
- [ ] Start Python API: `python3 -m api`
- [ ] Start frontend: `PYTHON_API_BASE_URL=http://127.0.0.1:8000 npm run dev`
- [ ] Run simulation: `POST /simulation/run`
- [ ] **Queue entry:** Case appears with clinical urgency badge (CRITICAL/HIGH/MEDIUM/LOW).
- [ ] **Case detail:** Click a row → panel shows clinical urgency, confidence, red flags, moderator decision.
- [ ] **Pre-escalation:** Force a `force_escalation=True` case → verify it skips binary search (check logs, no `MODERATOR_BINARY_STEP`).
- [ ] **Post-escalation:** Low-confidence case → should escalate and appear in "Human review handoff queue".
- [ ] **Human decision:** `python3 scripts/human_decision.py --case-id <id> --decision approve` → case moves to completed; verify in queue events timeline.
- [ ] **Return to review:** `python3 scripts/human_decision.py --case-id <id2> --decision return_to_review --notes "Review again, check labs"` → case returns to pending with notes visible in agent processing.
- [ ] **Narrative timeline:** "Queue activity" panel shows "X joined the queue", "Y moved up", "Scan completed", etc. in chronological order.
- [ ] **Waiting time:** Shows `Xm / Ym` for real cases; shows "—" if not available.
- [ ] **Analytics:** "HIGH compliance" / "MEDIUM compliance" (not P1/P2).
- [ ] **Backend down:** Kill Python API → frontend shows red banner, gracefully handles reconnection.

---

## Architecture Now Matches Design

✅ **Clinical review:** Independent LLM reasoning on vitals + structured prompt (no institutional bias).  
✅ **Pre-comparison escalation:** Force-escalated and invalid cases skip pairwise (fast path).  
✅ **Post-comparison escalation:** Low-confidence or explicit escalations route to human.  
✅ **Human handoff:** Manual decisions (approve/return-to-review) with contextual notes.  
✅ **Queue events:** All movements logged; narrative timeline surfaces operations.  
✅ **Frontend clarity:** Case detail panel + urgency badges + timeline = clinician-friendly dashboard.

---

## Files Changed

### Backend (Python)
- `agents/moderator_logic.py` — added `needs_precomparison_escalation()`
- `agents/moderator_graph.py` — added `check_escalation` node
- `agents/escalation_agent.py` — simplified to ModeratorDecisionMessage only
- `agents/escalation_adapter.py` — simplified message validation
- `agents/shared_schema.py` — removed ReviewMessage, renamed clinical_risk → clinical_urgency
- `agents/review_adapter.py` — updated references
- `agents/review_graph.py` — updated references
- `agents/router_adapter.py` — updated references
- `agents/moderator_prompts.py` — updated references
- `src/labslabs/band_dispatch.py` — removed expire_human_reviews() call
- `storage/queue_store.py` — return_to_review carries notes in payload
- `api/app.py` — expanded REASONING_EVENT_TYPES (7 types instead of 2)
- `README.md` — clarified architecture, human review flow

### Frontend (TypeScript/React)
- `frontend/src/lib/queue-models.ts` (renamed from `mock-queue.ts`)
  - Removed `QueuePriorityBand` type, `getPriorityBand()`, `toPriorityBand()`
  - Removed `inferTargetMinutes()`
  - Added `NarrativeItem` type and `deriveNarrativeItems()` function
  - Updated view model functions to handle nullable `waitingTimeMinutes`
  - Seed data: P1/P2/P3 → CRITICAL/HIGH/MEDIUM/LOW
- `frontend/src/lib/backend-api.ts`
  - Removed `toPriorityBand()` and `inferTargetMinutes()`
  - Added `toClinicalUrgency()`
  - Updated `normalizeQueueCasePayload()` to use clinical urgency
  - Expanded `REASONING_EVENT_TYPES` filter (7 types)
- `frontend/src/components/dashboard/CaseDetailPanel.tsx` (new)
  - Replaces AIControlPanel
  - Shows real case details: urgency, confidence, red flags, moderator decision
- `frontend/src/components/dashboard/ReasoningPanel.tsx` (rewritten)
  - Narrative timeline instead of event list
- `frontend/src/components/dashboard/LiveQueueTable.tsx`
  - Rank uses `queuePosition`
  - Added clinical urgency chip next to patient name
  - Row click handling for case selection
  - Waiting time shows "—" if null
- `frontend/src/components/dashboard/RecommendationCard.tsx`
  - Uses clinical urgency chip instead of P1/P2/P3 badge
  - Updated stale copy
- `frontend/src/components/dashboard/AnalyticsSection.tsx`
  - P1/P2 labels → HIGH/MEDIUM
  - Chart data keys: p1/p2 → high/medium
- `frontend/src/components/dashboard/QueueInsights.tsx`
  - Null check on remainingMinutes
- `frontend/src/hooks/useLiveQueue.ts`
  - Removed `runCommand()` and `deferCase()` exports
- `frontend/src/routes/index.tsx`
  - Imported `CaseDetailPanel` instead of `AIControlPanel`
  - Added `selectedCaseId` state
  - Passes handlers to LiveQueueTable and CaseDetailPanel
  - Added backend unreachable banner
- `frontend/src/routes/analytics.tsx`
  - Updated to use CaseDetailPanel instead of AIControlPanel
- `frontend/src/components/dashboard/ReasoningLog.tsx`
  - Added `caseRecords` prop for completeness

### Deleted
- `frontend/src/components/dashboard/AIControlPanel.tsx`
- `frontend/src/lib/mock-queue.ts` (renamed to queue-models.ts)

---

## Next Steps

1. **Start the moderator agent:** The error logs show it's not running. Launch it before running the simulation.
2. **Integration test:** Follow the checklist above.
3. **Optional:** Add a "human decision UI" inside the dashboard (approve/return-to-review buttons) instead of requiring `scripts/human_decision.py`. Current approach is functional but not ideal for clinical workflows.
4. **Optional:** Add role-based access control (clinician vs. admin views).
5. **Deployment:** Document the three-process startup (dispatcher, API, frontend) and moderator agent separately.
