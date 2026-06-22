from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from storage.db import get_connection, get_db_path, init_db
from storage.queue_store import apply_human_decision
from .simulation import get_status as get_simulation_status
from .simulation import reset_simulation
from .simulation import reset_to_empty_queue
from .simulation import set_speed_multiplier
from .simulation import start_run as start_simulation_run
from .simulation import stop_run as stop_simulation_run


ACTIVE_QUEUE_STATUSES = ("pending", "routed", "reviewed")
REASONING_EVENT_TYPES = (
    "clinical_urgency_determined",
    "moderator_decision",
    "placement_applied",
    "case_arrived",
    "case_completed",
    "case_escalated",
    "queue_reordered",
    "rank_changed",
    "human_decision_applied",
)


app = FastAPI(
    title="LabsLabs Queue API",
    version="0.1.0",
    description="Read-only API for the CT triage queue and agent reasoning log.",
)


@app.on_event("startup")
def reset_demo_state_on_startup() -> None:
    init_db()
    reset_to_empty_queue()

# Safe default for local development; the frontend still proxies through its own server.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SimulationRunRequest(BaseModel):
    row_numbers: list[int] | None = None
    arrival_gap_seconds: float = Field(default=5.0, ge=0.0, le=120.0)
    start_delay_seconds: float = Field(default=0.0, ge=0.0, le=120.0)
    top_leave_after_seconds: float = Field(default=12.0, ge=0.0, le=300.0)
    limit: int = Field(default=9, ge=1, le=50)


class SimulationSpeedRequest(BaseModel):
    speed_multiplier: float = Field(default=1.0, ge=0.25, le=8.0)


class HumanDecisionRequest(BaseModel):
    case_id: str
    decision: Literal["approve", "return_to_review"]
    notes: str | None = None


def _parse_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def _current_tick(connection: Any) -> int:
    row = connection.execute(
        "SELECT COALESCE(current_tick, 0) AS current_tick FROM queue_state WHERE id = 1"
    ).fetchone()
    return int(row["current_tick"]) if row is not None else 0


def _latest_queue_version(connection: Any) -> int:
    row = connection.execute(
        """
        SELECT MAX(version) AS latest_queue_version
        FROM (
            SELECT COALESCE(MAX(queue_version), 0) AS version FROM cases
            UNION ALL
            SELECT COALESCE(MAX(queue_version), 0) AS version FROM queue_events
            UNION ALL
            SELECT COALESCE(queue_version, 0) AS version FROM queue_state WHERE id = 1
        )
        """
    ).fetchone()
    return int(row["latest_queue_version"]) if row and row["latest_queue_version"] is not None else 0


def _row_to_case_record(row: Any, *, current_tick: int) -> dict[str, Any]:
    payload = _parse_json_value(row["payload"])
    enqueue_tick = row["enqueue_tick"]
    waiting_ticks = None
    if enqueue_tick is not None:
        waiting_ticks = max(0, current_tick - int(enqueue_tick))

    return {
        "case_id": row["case_id"],
        "patient_code": row["patient_code"],
        "status": row["status"],
        "priority_score": row["priority_score"],
        "queue_position": row["queue_rank"],
        "previous_position": row["previous_rank"],
        "rank_change": row["rank_change"],
        "queue_version": row["queue_version"],
        "arrival_seq": row["arrival_seq"],
        "enqueue_tick": row["enqueue_tick"],
        "start_tick": row["start_tick"],
        "completion_tick": row["completion_tick"],
        "waiting_ticks": waiting_ticks,
        "current_tick": current_tick,
        "payload": payload,
        "human_due_at": row["human_due_at"],
        "human_status": row["human_status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _list_cases(
    *,
    statuses: tuple[str, ...] | None = None,
    case_id: str | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        current_tick = _current_tick(connection)
        conditions: list[str] = []
        params: list[Any] = []

        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            conditions.append(f"status IN ({placeholders})")
            params.extend(statuses)
        if case_id:
            conditions.append("case_id = ?")
            params.append(case_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = connection.execute(
            f"""
            SELECT
                case_id,
                patient_code,
                status,
                priority_score,
                queue_rank,
                previous_rank,
                rank_change,
                queue_version,
                arrival_seq,
                enqueue_tick,
                start_tick,
                completion_tick,
                payload,
                human_due_at,
                human_status,
                created_at,
                updated_at
            FROM cases
            {where_clause}
            ORDER BY
                CASE WHEN queue_rank IS NULL THEN 1 ELSE 0 END ASC,
                queue_rank ASC,
                updated_at DESC,
                case_id ASC
            """,
            tuple(params),
        ).fetchall()

    return [_row_to_case_record(row, current_tick=current_tick) for row in rows]


def _list_reasoning_events(
    *,
    case_id: str | None = None,
    limit: int = 200,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        params: list[Any] = list(REASONING_EVENT_TYPES)
        placeholders = ", ".join("?" for _ in REASONING_EVENT_TYPES)
        query = f"""
            SELECT
                event_id,
                event_type,
                case_id,
                queue_version,
                simulation_tick,
                affected_case_ids,
                details,
                created_at
            FROM queue_events
            WHERE event_type IN ({placeholders})
        """
        if case_id:
            query += " AND case_id = ?"
            params.append(case_id)
        query += " ORDER BY created_at DESC, event_id DESC LIMIT ?"
        params.append(limit)
        rows = connection.execute(query, tuple(params)).fetchall()

    events: list[dict[str, Any]] = []
    for row in rows:
        events.append(
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "case_id": row["case_id"],
                "queue_version": row["queue_version"],
                "simulation_tick": row["simulation_tick"],
                "affected_case_ids": _parse_json_value(row["affected_case_ids"]) or [],
                "details": _parse_json_value(row["details"]) or {},
                "created_at": row["created_at"],
            }
        )
    return events


def _dashboard_summary(db_path: Path | None = None) -> dict[str, Any]:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        current_tick = _current_tick(connection)
        latest_queue_version = _latest_queue_version(connection)
        active_count = connection.execute(
            f"SELECT COUNT(*) AS count FROM cases WHERE status IN ({', '.join('?' for _ in ACTIVE_QUEUE_STATUSES)})",
            ACTIVE_QUEUE_STATUSES,
        ).fetchone()["count"]
        escalated_count = connection.execute(
            "SELECT COUNT(*) AS count FROM cases WHERE status = 'escalated'"
        ).fetchone()["count"]

    return {
        "active_count": int(active_count),
        "escalated_count": int(escalated_count),
        "latest_queue_version": latest_queue_version,
        "current_tick": current_tick,
    }


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "LabsLabs Queue API", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health() -> dict[str, Any]:
    path = init_db()
    return {"ok": True, "db_path": str(path)}


@app.get("/queue")
def get_queue(case_id: str | None = None) -> dict[str, Any]:
    active_queue = _list_cases(statuses=ACTIVE_QUEUE_STATUSES, case_id=case_id)
    escalated_cases = _list_cases(statuses=("escalated",), case_id=case_id)
    all_cases = [*active_queue, *escalated_cases]
    summary = _dashboard_summary()
    return {
        "active_queue": active_queue,
        "escalated_cases": escalated_cases,
        "all_cases": all_cases,
        "summary": summary,
    }


@app.get("/reasoning-events")
def get_reasoning_events(
    case_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    return {"events": _list_reasoning_events(case_id=case_id, limit=limit)}


@app.get("/dashboard-summary")
def get_dashboard_summary() -> dict[str, Any]:
    return _dashboard_summary()


@app.post("/human-decisions")
def create_human_decision(request: HumanDecisionRequest) -> dict[str, Any]:
    result = apply_human_decision(
        request.case_id,
        decision=request.decision,
        notes=request.notes,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Case {request.case_id} is not awaiting human review.",
        )
    return {"result": result}


@app.get("/simulation/status")
def simulation_status() -> dict[str, Any]:
    return get_simulation_status()


@app.post("/simulation/run")
def run_simulation(request: SimulationRunRequest) -> dict[str, Any]:
    return start_simulation_run(
        row_numbers=request.row_numbers,
        arrival_gap_seconds=request.arrival_gap_seconds,
        start_delay_seconds=request.start_delay_seconds,
        top_leave_after_seconds=request.top_leave_after_seconds,
        limit=request.limit,
    )


@app.post("/simulation/stop")
def stop_simulation() -> dict[str, Any]:
    return stop_simulation_run()


@app.post("/simulation/reset")
def reset_simulation_state() -> dict[str, Any]:
    return reset_simulation()


@app.post("/simulation/speed")
def update_simulation_speed(request: SimulationSpeedRequest) -> dict[str, Any]:
    return set_speed_multiplier(request.speed_multiplier)
