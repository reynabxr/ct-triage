# CT Band Multi-Agent Proof

This workflow uses SQLite as the queue and case-state store while Band remains the coordination layer.

One Band room represents one CT case. The agents do not call each other directly. Each step posts a structured JSON message back into the same room and updates the SQLite record.

## Agents

- `ct_dispatcher_agent`: opens the next pending case in a fresh Band room.
- `ct_router_agent`: plain Python agent that loads and normalizes the case, preserves `case_id` and `patient_code`, computes provisional urgency metadata, marks pending cases `routed`, and sends structured `case` JSON to the review agent.
- `ct_review_agent`: LangGraph agent that reviews the incoming case on its own and emits structured clinical urgency signals, with optional LLM refinement for urgency, confidence, red flags, and the short reasoning summary.
- `ct_moderator_agent`: LangGraph agent that receives the reviewed case plus clinical urgency result, loads queue context, performs nearby comparisons, and emits a structured moderator decision, with optional LLM ownership of the final placement and escalation choice.
- `ct_escalation_agent`: receives moderator decisions that need human review, marks the case `escalated`, and publishes a human handoff packet with explicit choices.

## Review Logic

`ct_review_agent` receives the structured `message_type: "case"` JSON from the router. It does not chat with the user, does not invent missing data, does not compare cases, and does not decide final queue placement or human escalation.

The review graph is:

```text
ingest_case
assess_red_flags
assess_physiologic_instability
assess_missingness
synthesize_urgency
emit_structured_result
```

The agent uses the chief complaint description when present, coded chart fields, vitals, AVPU, age, router-provided missing fields, and provisional urgency metadata to produce clinical urgency signals. It treats complaint codes as coded identifiers unless a supported description is present.

The review LLM, when enabled, can refine:

- `clinical_urgency`
- `confidence`
- `red_flags`
- `missing_information`
- `reasoning_summary`

The review LLM should keep the reasoning simple and brief. It sees only the
structured case JSON, not a deterministic rule summary. Missingness should be
clinically meaningful only for identity fields such as missing `patient_code`
or `case_id`; routine absent vitals or chart fields should not be treated as
concerning by themselves.

The queue engine remains responsible for queue recomputation and rank-change persistence. The review agent does not write queue positions to SQLite.

After producing `clinical_urgency`, the review agent forwards a `moderator_input` packet containing both the original `case` and the `clinical_urgency` result to `ct_moderator_agent`.

## Moderator Logic

`ct_moderator_agent` receives `message_type: "moderator_input"` and runs the queue-aware moderation workflow. It loads the current pending queue from SQLite, performs binary-search comparisons against nearby queue neighbors, and passes the case, clinical urgency, queue context, and comparison history into the moderator LLM. Pairwise comparison is limited to nearby cases above and below the proposed insertion point.

The pairwise comparator still performs the binary-search comparisons between
the new case and nearby queue cases. The comparator and the moderator LLM see
only the structured case and queue context, not deterministic rank heuristics
or insertion hints. The final moderator LLM decides the placement action,
anchor case, whether human review is needed, and the short reason summary. The
queue engine only applies that decision deterministically.

The moderator emits a `moderator_decision` JSON packet:

```json
{
  "message_type": "moderator_decision",
  "case_id": "13960219003",
  "patient_code": "9608665.0",
  "clinical_urgency": "HIGH",
  "confidence": 0.84,
  "placement_action": "insert_before",
  "anchor_case_id": "13960219005",
  "comparison_count": 2,
  "needs_human_review": false,
  "reason_summary": "clinical_urgency=HIGH; confidence=0.84; placement_action=insert_before; comparisons=2",
  "recommended_next_route": "queue_engine_apply",
  "comparison_history": [],
  "queue_snapshot": []
}
```

If `needs_human_review` is true, `ct_moderator_agent` sends the moderator decision to `ct_escalation_agent`, which remains responsible for human handoff formatting. Otherwise the moderator decision is stored as the final result and the queue engine applies the requested placement deterministically.

Example review output:

```json
{
  "message_type": "clinical_urgency",
  "case_id": "13960219003",
  "patient_code": "9608665.0",
  "clinical_urgency": "HIGH",
  "confidence": 0.84,
  "red_flags": ["low_spo2", "abnormal_avpu"],
  "missing_information": ["patient_code"],
  "reasoning_summary": "urgency=HIGH; urgency_score=8; red_flags=low_spo2,abnormal_avpu; missing=patient_code",
  "recommended_next_route": "moderator"
}
```

Cases that need human review are sent to `ct_escalation_agent`. The handoff packet marks the case as escalated and records the due time. Human intervention is applied out of band:

```bash
python3 scripts/human_decision.py 13960219003 approve
python3 scripts/human_decision.py 13960219003 return_to_review --notes "Needs another look"
```

Overdue human reviews can be expired manually:

```bash
python3 scripts/expire_human_reviews.py
```

## SQLite Workflow

Database schema:

```sql
CREATE TABLE cases (
    case_id TEXT PRIMARY KEY,
    patient_code TEXT,
    status TEXT,
    payload TEXT,
    final_result TEXT,
    created_at TEXT,
    updated_at TEXT,
    priority_score REAL,
    queue_rank INTEGER,
    previous_rank INTEGER,
    rank_change INTEGER,
    queue_version INTEGER,
    manual_priority_override REAL,
    human_packet TEXT,
    human_status TEXT,
    human_due_at TEXT,
    human_decision TEXT,
    human_decision_notes TEXT,
    human_decided_at TEXT
);
```

The database also includes a `queue_events` audit table for queue
recomputation events, clinical urgency decisions, moderator decisions, and
queue placement application events.

Status values:

```text
pending
routed
reviewed
escalated
completed
```

## Environment

Required:

```bash
THENVOI_WS_URL=...
THENVOI_REST_URL=...
```

Optional:

```bash
CASES_DB_PATH=/absolute/path/to/cases.db
CT_REVIEW_MODEL=deepseek-v4-flash
AIML_API_KEY=...
AIML_BASE_URL=https://api.aimlapi.com/v1
CT_REVIEW_USE_LLM=1
CT_HUMAN_REVIEW_TIMEOUT_MINUTES=15
```

Band credentials must be available through the Band SDK config loader for these names:

```text
ct_dispatcher_agent
ct_router_agent
ct_review_agent
ct_moderator_agent
ct_escalation_agent
```

Optional mention overrides:

```bash
CT_ROUTER_MENTION=@ct_router_agent
CT_REVIEW_MENTION=@ct_review_agent
CT_MODERATOR_MENTION=@ct_moderator_agent
CT_ESCALATION_MENTION=@ct_escalation_agent
```

## Setup

Create the database and seed the sample cases:

```bash
python3 scripts/create_db.py
python3 -m storage.seed_cases
```

## Run

Start each process in a separate terminal:

```bash
python3 -m agents.run_router
python3 -m agents.run_review
python3 -m agents.run_moderator
python3 -m agents.run_escalation
```

Process one queued case:

```bash
python3 scripts/process_next_case.py
```

Or enqueue a mock case and immediately hand the current top pending case into Band:

```bash
python3 scripts/mock_queue_flow.py enqueue --row-number 2 --dispatch-next
```

Replay helpers:

```bash
python3 scripts/reset_case.py 13960219002
python3 scripts/seed_one_case.py --case-id 13960219002
python3 scripts/seed_one_case.py --row-number 2
python3 scripts/seed_one_case.py --case-id 13960219002 --force-escalation
```

This proof creates a fresh Band room for each queued case it starts. The SQLite `case_id` is carried in the Band message payload, not in the Band `task_id` field. The dispatch script posts the `queue_trigger` automatically from the SQLite queue using a dedicated `ct_dispatcher_agent`, then the four workflow agents handle the rest.

`CT_REVIEW_USE_LLM` can be set to `0` to disable the optional AIML API / DeepSeek review refinement. When credentials are present, the review graph uses the LLM path by default and falls back to the deterministic path if the call fails.
`CT_MODERATOR_USE_LLM` can be set to `0` to disable the moderator-side LLM placement reasoning. When credentials are present, the moderator graph uses the LLM path by default and falls back to the deterministic path if the call fails.
`CT_HUMAN_REVIEW_TIMEOUT_MINUTES` sets the due time for a human decision. Overdue escalations are expired by `scripts/expire_human_reviews.py` and also when the dispatch bridge runs.
Human decisions are recorded by `scripts/human_decision.py`, so no human UUID is required.

## Test

Expected flow for the first seeded case:

1. Router posts a `case` JSON message mentioning `@ct_review_agent`.
2. Review assesses only that case and produces a structured `clinical_urgency` result, with the LLM optionally refining the urgency, confidence, red flags, and short reasoning.
3. Review sends a `moderator_input` JSON packet mentioning `@ct_moderator_agent`.
4. Moderator loads queue context, performs nearby pairwise comparisons, and asks the moderator LLM to choose placement and escalation.
5. If escalation is needed, Moderator sends the moderator decision to `ct_escalation_agent`.
6. Otherwise SQLite stores the moderator decision in `final_result`, and the queue engine applies the chosen placement deterministically.

The remaining seeded cases stay `pending` until `process_next_case.py` is run again.

To simulate arrivals and departures in real time, use:

```bash
python3 scripts/mock_queue_flow.py simulate --arrival-row-numbers 2,3,4 --arrival-gap-seconds 10 --top-leave-after-seconds 30
```

To expire overdue human reviews manually, use:

```bash
python3 scripts/expire_human_reviews.py
```

## Local Checks

Compile the changed workflow:

```bash
.venv/bin/python3 -m py_compile agents/review_agent.py agents/review_schema.py agents/review_graph.py agents/review_prompts.py agents/moderator_agent.py agents/moderator_schema.py agents/moderator_logic.py agents/moderator_graph.py agents/moderator_adapter.py agents/shared_schema.py agents/review_adapter.py agents/run_review.py agents/run_moderator.py agents/escalation_agent.py agents/escalation_adapter.py agents/run_escalation.py scripts/expire_human_reviews.py scripts/mock_queue_flow.py src/labslabs/band_dispatch.py storage/queue_store.py storage/db.py
```
