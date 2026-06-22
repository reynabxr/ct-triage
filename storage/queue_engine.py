from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import get_connection, get_db_path, init_db

logger = logging.getLogger(__name__)

PAYLOAD_FIELD_MAP = {
    "case_id": ("case_id", "triage_code"),
    "patient_code": ("patient_code", "PatientCode"),
    "triage_code": ("triage_code",),
    "pain_grade": ("pain_grade", "PainGrade"),
    "spo2": ("spo2", "O2Saturation"),
    "avpu": ("avpu", "AVPU"),
    "urgency_score": ("urgency_score",),
    "waiting_time_minutes": ("waiting_time_minutes",),
    "manual_priority_override": ("manual_priority_override", "priority_override"),
}
NUMERIC_FIELDS = {
    "pain_grade",
    "spo2",
    "urgency_score",
    "waiting_time_minutes",
    "manual_priority_override",
}


@dataclass(frozen=True)
class PendingCase:
    case_id: str
    patient_code: str | None
    status: str
    payload: dict[str, Any]
    created_at: str
    updated_at: str
    priority_score: float | None
    queue_rank: int | None
    previous_rank: int | None
    rank_change: int | None
    queue_version: int | None
    arrival_seq: int | None
    enqueue_tick: int | None
    start_tick: int | None
    completion_tick: int | None
    manual_priority_override: float | None


def load_pending_cases(db_path: Path | None = None) -> list[PendingCase]:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        rows = connection.execute(
            """
            SELECT
                case_id,
                patient_code,
                status,
                payload,
                created_at,
                updated_at,
                priority_score,
                queue_rank,
                previous_rank,
                rank_change,
                queue_version,
                arrival_seq,
                enqueue_tick,
                start_tick,
                completion_tick,
                manual_priority_override
            FROM cases
            WHERE status = 'pending'
            ORDER BY created_at ASC, case_id ASC
            """
        ).fetchall()

    cases = [_row_to_pending_case(row) for row in rows]
    logger.info("QUEUE_CASES_LOADED pending_count=%s", len(cases))
    return cases


def compute_priority_score(case_row: PendingCase) -> float:
    normalized = _extract_priority_inputs(case_row)
    override = normalized["manual_priority_override"]
    if override is not None:
        return round(float(override), 3)

    score = 0.0
    score += float(normalized["urgency_score"] or 0) * 3.0

    spo2 = normalized["spo2"]
    if spo2 is not None:
        if spo2 < 90:
            score += 10.0
        elif spo2 < 92:
            score += 8.0
        elif spo2 < 95:
            score += 3.0

    avpu = (normalized["avpu"] or "").upper()
    if avpu and avpu != "A":
        score += 6.0

    pain_grade = normalized["pain_grade"]
    if pain_grade is not None:
        if pain_grade >= 8:
            score += 4.0
        elif pain_grade >= 5:
            score += 2.0

    waiting_time_minutes = normalized["waiting_time_minutes"] or 0
    score += min(waiting_time_minutes, 360) / 15.0

    score -= _missing_data_penalty(normalized)
    return round(score, 3)


def rank_pending_cases(cases: list[PendingCase]) -> list[dict[str, Any]]:
    ranked_cases: list[dict[str, Any]] = []
    for case in cases:
        priority_score = compute_priority_score(case)
        normalized = _extract_priority_inputs(case)
        ranked_cases.append(
            {
                "case_id": case.case_id,
                "patient_code": case.patient_code,
                "status": case.status,
                "created_at": case.created_at,
                "updated_at": case.updated_at,
                "previous_rank": case.queue_rank,
                "priority_score": priority_score,
                "priority_inputs": normalized,
            }
        )

    ranked_cases.sort(
        key=lambda case: (
            -case["priority_score"],
            -int(case["priority_inputs"]["urgency_score"] or 0),
            _sort_wait_minutes(case["priority_inputs"]["waiting_time_minutes"]),
            case["created_at"],
            case["case_id"],
        )
    )

    for index, case in enumerate(ranked_cases, start=1):
        previous_rank = case["previous_rank"]
        case["queue_rank"] = index
        case["rank_change"] = (
            None if previous_rank is None else previous_rank - index
        )
    return ranked_cases


def recompute_queue(
    *,
    db_path: Path | None = None,
    reason: str = "manual_recompute",
    trigger_case_id: str | None = None,
) -> dict[str, Any]:
    cases = load_pending_cases(db_path)
    old_ranks = {case.case_id: case.queue_rank for case in cases}
    ranked_cases = rank_pending_cases(cases)
    new_ranks = {case["case_id"]: case["queue_rank"] for case in ranked_cases}
    affected_cases = get_affected_cases(old_ranks, new_ranks)

    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        queue_version = _next_queue_version(connection)
        for case in cases:
            _log_event(
                connection,
                queue_version=queue_version,
                event_type="case_loaded",
                case_id=case.case_id,
                details={
                    "status": case.status,
                    "current_rank": case.queue_rank,
                },
            )
        update_case_ranks(
            ranked_cases,
            queue_version=queue_version,
            connection=connection,
        )
        _log_event(
            connection,
            queue_version=queue_version,
            event_type="queue_recomputed",
            case_id=trigger_case_id,
            details={
                "reason": reason,
                "pending_count": len(ranked_cases),
                "affected_count": len(affected_cases),
            },
        )
        for case_id in affected_cases:
            updated_case = next(
                case for case in ranked_cases if case["case_id"] == case_id
            )
            _log_event(
                connection,
                queue_version=queue_version,
                event_type="rank_changed",
                case_id=case_id,
                details={
                    "reason": reason,
                    "previous_rank": old_ranks.get(case_id),
                    "queue_rank": updated_case["queue_rank"],
                    "rank_change": updated_case["rank_change"],
                    "priority_score": updated_case["priority_score"],
                },
            )
        if affected_cases:
            _log_event(
                connection,
                queue_version=queue_version,
                event_type="affected_cases",
                case_id=trigger_case_id,
                details={
                    "reason": reason,
                    "case_ids": affected_cases,
                },
            )
        connection.commit()

    logger.info(
        "QUEUE_RECOMPUTED version=%s pending_count=%s affected_count=%s trigger_case_id=%s reason=%s",
        queue_version,
        len(ranked_cases),
        len(affected_cases),
        trigger_case_id or "none",
        reason,
    )
    return {
        "queue_version": queue_version,
        "pending_count": len(ranked_cases),
        "affected_cases": affected_cases,
        "queue": ranked_cases,
    }


def enqueue_case(
    *,
    case_id: str,
    patient_code: str | None = None,
    payload: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Add a case to the simulated active queue without using real timestamps."""
    init_db(db_path)
    now = _now()
    with get_connection(db_path or get_db_path()) as connection:
        simulation_tick = _advance_tick(connection)
        arrival_seq = _next_arrival_seq(connection)
        queue_version = _next_queue_version(connection)
        tail_position = _active_queue_count(connection) + 1
        payload_json = json.dumps(payload or {}, sort_keys=True)
        connection.execute(
            """
            INSERT INTO cases (
                case_id,
                patient_code,
                status,
                payload,
                final_result,
                created_at,
                updated_at,
                priority_score,
                previous_rank,
                queue_rank,
                rank_change,
                queue_version,
                arrival_seq,
                enqueue_tick,
                start_tick,
                completion_tick
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                patient_code = excluded.patient_code,
                status = excluded.status,
                payload = excluded.payload,
                final_result = excluded.final_result,
                updated_at = excluded.updated_at,
                priority_score = excluded.priority_score,
                previous_rank = excluded.previous_rank,
                queue_rank = excluded.queue_rank,
                rank_change = excluded.rank_change,
                queue_version = excluded.queue_version,
                arrival_seq = excluded.arrival_seq,
                enqueue_tick = excluded.enqueue_tick,
                start_tick = excluded.start_tick,
                completion_tick = excluded.completion_tick
            """,
            (
                case_id,
                patient_code,
                "pending",
                payload_json,
                None,
                now,
                now,
                None,
                None,
                tail_position,
                None,
                queue_version,
                arrival_seq,
                simulation_tick,
                simulation_tick if tail_position == 1 else None,
                None,
            ),
        )
        _set_queue_version(connection, queue_version)
        _log_event(
            connection,
            queue_version=queue_version,
            event_type="case_arrived",
            case_id=case_id,
            affected_case_ids=[case_id],
            simulation_tick=simulation_tick,
            details={
                "arrival_seq": arrival_seq,
                "enqueue_tick": simulation_tick,
                "queue_position": tail_position,
                "source": "human_review_return" if (payload or {}).get("human_review_decision") == "return_to_review" else "simulation",
                "human_review_notes": (payload or {}).get("human_review_notes"),
            },
        )
        connection.commit()
    logger.info(
        "QUEUE_CASE_ARRIVED case_id=%s arrival_seq=%s enqueue_tick=%s position=%s version=%s",
        case_id,
        arrival_seq,
        simulation_tick,
        tail_position,
        queue_version,
    )
    return {
        "case_id": case_id,
        "arrival_seq": arrival_seq,
        "enqueue_tick": simulation_tick,
        "queue_position": tail_position,
        "queue_version": queue_version,
    }


def apply_placement_decision(
    *,
    decision: dict[str, Any] | None = None,
    case_id: str | None = None,
    case_payload: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Apply a moderator placement decision deterministically to the queue."""
    init_db(db_path)
    decision_payload = dict(decision or {})
    resolved_case_id = case_id or _decision_case_id(decision_payload)
    placement_action = _decision_placement_action(decision_payload)
    if placement_action == "go_to_top":
        return insert_at_top(
            case_id=resolved_case_id,
            decision=decision_payload,
            case_payload=case_payload,
            db_path=db_path,
        )
    if placement_action == "insert_before":
        return insert_before(
            case_id=resolved_case_id,
            anchor_case_id=_decision_anchor_case_id(decision_payload),
            decision=decision_payload,
            case_payload=case_payload,
            db_path=db_path,
        )
    if placement_action == "insert_after":
        return insert_after(
            case_id=resolved_case_id,
            anchor_case_id=_decision_anchor_case_id(decision_payload),
            decision=decision_payload,
            case_payload=case_payload,
            db_path=db_path,
        )
    if placement_action == "go_to_bottom":
        return insert_at_bottom(
            case_id=resolved_case_id,
            decision=decision_payload,
            case_payload=case_payload,
            db_path=db_path,
        )
    if placement_action == "hold_and_escalate":
        return mark_hold_or_escalation(
            case_id=resolved_case_id,
            decision=decision_payload,
            case_payload=case_payload,
            db_path=db_path,
        )
    raise ValueError(f"Unsupported placement_action={placement_action}")


def complete_top_case(
    *,
    final_result: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    """Complete and remove only the case currently at queue position 1."""
    init_db(db_path)
    now = _now()
    with get_connection(db_path or get_db_path()) as connection:
        top_row = connection.execute(
            """
            SELECT case_id, queue_rank
            FROM cases
            WHERE status = 'pending'
            ORDER BY queue_rank ASC, arrival_seq ASC, case_id ASC
            LIMIT 1
            """
        ).fetchone()
        if top_row is None:
            return None

        case_id = str(top_row["case_id"])
        if int(top_row["queue_rank"] or 0) != 1:
            raise ValueError(f"Top active case has invalid queue_position={top_row['queue_rank']}")

        simulation_tick = _advance_tick(connection)
        queue_version = _next_queue_version(connection)
        connection.execute(
            """
            UPDATE cases
            SET status = ?,
                final_result = ?,
                previous_rank = queue_rank,
                queue_rank = NULL,
                rank_change = NULL,
                queue_version = ?,
                completion_tick = ?,
                updated_at = ?
            WHERE case_id = ?
            """,
            (
                "completed",
                final_result,
                queue_version,
                simulation_tick,
                now,
                case_id,
            ),
        )
        remaining_ids = _active_case_ids(connection)
        affected_case_ids = _apply_active_order(
            connection,
            remaining_ids,
            queue_version=queue_version,
            simulation_tick=simulation_tick,
            updated_at=now,
        )
        _set_queue_version(connection, queue_version)
        _log_event(
            connection,
            queue_version=queue_version,
            event_type="queue_version_incremented",
            case_id=case_id,
            affected_case_ids=affected_case_ids,
            simulation_tick=simulation_tick,
            details={
                "reason": "case_completed",
                "new_queue_version": queue_version,
            },
        )
        _log_event(
            connection,
            queue_version=queue_version,
            event_type="case_completed",
            case_id=case_id,
            affected_case_ids=affected_case_ids,
            simulation_tick=simulation_tick,
            details={
                "completion_tick": simulation_tick,
                "completed_position": 1,
            },
        )
        if affected_case_ids:
            _log_event(
                connection,
                queue_version=queue_version,
                event_type="queue_reordered",
                case_id=case_id,
                affected_case_ids=affected_case_ids,
                simulation_tick=simulation_tick,
                details={"reason": "case_completed"},
            )
        connection.commit()

    logger.info(
        "QUEUE_TOP_COMPLETED case_id=%s affected_case_ids=%s version=%s tick=%s",
        case_id,
        affected_case_ids,
        queue_version,
        simulation_tick,
    )
    return {
        "queue_version": queue_version,
        "simulation_tick": simulation_tick,
        "case_id": case_id,
        "affected_case_ids": affected_case_ids,
        "queue_snapshot": get_queue_snapshot(db_path=db_path),
    }


def insert_at_top(
    *,
    case_id: str,
    decision: dict[str, Any],
    case_payload: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    return _apply_queue_placement(
        case_id=case_id,
        placement_action="go_to_top",
        anchor_case_id=None,
        decision=decision,
        case_payload=case_payload,
        db_path=db_path,
    )


def insert_before(
    *,
    case_id: str,
    anchor_case_id: str | None,
    decision: dict[str, Any],
    case_payload: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    return _apply_queue_placement(
        case_id=case_id,
        placement_action="insert_before",
        anchor_case_id=anchor_case_id,
        decision=decision,
        case_payload=case_payload,
        db_path=db_path,
    )


def insert_after(
    *,
    case_id: str,
    anchor_case_id: str | None,
    decision: dict[str, Any],
    case_payload: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    return _apply_queue_placement(
        case_id=case_id,
        placement_action="insert_after",
        anchor_case_id=anchor_case_id,
        decision=decision,
        case_payload=case_payload,
        db_path=db_path,
    )


def insert_at_bottom(
    *,
    case_id: str,
    decision: dict[str, Any],
    case_payload: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    return _apply_queue_placement(
        case_id=case_id,
        placement_action="go_to_bottom",
        anchor_case_id=None,
        decision=decision,
        case_payload=case_payload,
        db_path=db_path,
    )


def mark_hold_or_escalation(
    *,
    case_id: str,
    decision: dict[str, Any],
    case_payload: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    init_db(db_path)
    now = _now()
    with get_connection(db_path or get_db_path()) as connection:
        simulation_tick = _advance_tick(connection)
        queue_version = _next_queue_version(connection)
        case_row = _load_case_row(connection, case_id)
        if case_row is None and case_payload is None:
            raise ValueError(f"case_id={case_id} does not exist and no case_payload was provided")

        case_data = case_payload or _case_payload_from_row(case_row)
        patient_code = _resolve_patient_code(case_data, case_row)
        payload_json = json.dumps(case_data, sort_keys=True)
        active_ids = _active_case_ids(connection)
        case_was_active = case_id in active_ids
        previous_rank = case_row["queue_rank"] if case_row is not None else None

        if case_row is None:
            arrival_seq = _next_arrival_seq(connection)
            connection.execute(
                """
                INSERT INTO cases (
                    case_id,
                    patient_code,
                    status,
                    payload,
                    final_result,
                    created_at,
                    updated_at,
                    priority_score,
                    previous_rank,
                    queue_rank,
                    rank_change,
                    queue_version,
                    arrival_seq,
                    enqueue_tick,
                    start_tick,
                    completion_tick,
                    human_packet,
                    human_status,
                    human_due_at,
                    human_decision,
                    human_decision_notes,
                    human_decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    patient_code,
                    "escalated",
                    payload_json,
                    None,
                    now,
                    now,
                    None,
                    previous_rank,
                    None,
                    None,
                    queue_version,
                    arrival_seq,
                    simulation_tick,
                    None,
                    None,
                    json.dumps(decision, sort_keys=True),
                    "pending",
                    None,
                    None,
                    None,
                    None,
                ),
            )
        else:
            arrival_seq = (
                int(case_row["arrival_seq"]) if case_row["arrival_seq"] is not None else _next_arrival_seq(connection)
            )
            enqueue_tick = (
                int(case_row["enqueue_tick"]) if case_row["enqueue_tick"] is not None else simulation_tick
            )
            connection.execute(
                """
                UPDATE cases
                SET patient_code = ?,
                    status = 'escalated',
                    payload = ?,
                    final_result = NULL,
                    previous_rank = ?,
                    queue_rank = NULL,
                    rank_change = NULL,
                    queue_version = ?,
                    arrival_seq = ?,
                    enqueue_tick = ?,
                    completion_tick = NULL,
                    human_packet = ?,
                    human_status = 'pending',
                    human_due_at = NULL,
                    human_decision = NULL,
                    human_decision_notes = NULL,
                    human_decided_at = NULL,
                    updated_at = ?
                WHERE case_id = ?
                """,
                (
                    patient_code,
                    payload_json,
                    previous_rank,
                    queue_version,
                    arrival_seq,
                    enqueue_tick,
                    json.dumps(decision, sort_keys=True),
                    now,
                    case_id,
                ),
            )

        affected_case_ids: list[str] = []
        if case_was_active:
            remaining_ids = [active_case_id for active_case_id in active_ids if active_case_id != case_id]
            affected_case_ids = recompute_positions(
                connection,
                remaining_ids,
                queue_version=queue_version,
                simulation_tick=simulation_tick,
                updated_at=now,
            )

        _set_queue_version(connection, queue_version)
        _log_event(
            connection,
            queue_version=queue_version,
            event_type="queue_version_incremented",
            case_id=case_id,
            simulation_tick=simulation_tick,
            details={"new_queue_version": queue_version, "decision_payload": decision},
        )
        _log_event(
            connection,
            queue_version=queue_version,
            event_type="case_held",
            case_id=case_id,
            affected_case_ids=affected_case_ids,
            simulation_tick=simulation_tick,
            details={
                "decision_payload": decision,
                "previous_rank": previous_rank,
                "status": "escalated",
            },
        )
        _log_event(
            connection,
            queue_version=queue_version,
            event_type="case_escalated",
            case_id=case_id,
            affected_case_ids=affected_case_ids,
            simulation_tick=simulation_tick,
            details={
                "decision_payload": decision,
                "previous_rank": previous_rank,
                "status": "escalated",
            },
        )
        if case_was_active:
            _log_event(
                connection,
                queue_version=queue_version,
                event_type="queue_reordered",
                case_id=case_id,
                affected_case_ids=affected_case_ids,
                simulation_tick=simulation_tick,
                details={"placement_action": "hold_and_escalate", "decision_payload": decision},
            )
        connection.commit()

    logger.info(
        "QUEUE_CASE_HELD case_id=%s affected_case_ids=%s version=%s tick=%s",
        case_id,
        affected_case_ids,
        queue_version,
        simulation_tick,
    )
    return {
        "queue_version": queue_version,
        "simulation_tick": simulation_tick,
        "case_id": case_id,
        "queue_position": None,
        "affected_case_ids": affected_case_ids,
        "placement_action": "hold_and_escalate",
        "queue_snapshot": get_queue_snapshot(db_path=db_path),
    }


def recompute_positions(
    connection: Any,
    ordered_case_ids: list[str],
    *,
    queue_version: int,
    simulation_tick: int,
    updated_at: str,
) -> list[str]:
    return _apply_active_order(
        connection,
        ordered_case_ids,
        queue_version=queue_version,
        simulation_tick=simulation_tick,
        updated_at=updated_at,
    )


def update_case_ranks(
    ranked_cases: list[dict[str, Any]],
    *,
    queue_version: int,
    connection: Any | None = None,
    db_path: Path | None = None,
) -> None:
    owns_connection = connection is None
    if owns_connection:
        init_db(db_path)
        connection = get_connection(db_path or get_db_path())

    try:
        for case in ranked_cases:
            connection.execute(
                """
                UPDATE cases
                SET priority_score = ?,
                    previous_rank = queue_rank,
                    queue_rank = ?,
                    rank_change = ?,
                    queue_version = ?,
                    updated_at = ?
                WHERE case_id = ?
                """,
                (
                    case["priority_score"],
                    case["queue_rank"],
                    case["rank_change"],
                    queue_version,
                    _now(),
                    case["case_id"],
                ),
            )
        if owns_connection:
            connection.commit()
    finally:
        if owns_connection:
            connection.close()


def get_queue_snapshot(
    case_id: str | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    init_db(db_path)
    query = """
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
            created_at,
            updated_at
        FROM cases
        WHERE status = 'pending'
    """
    params: tuple[Any, ...] = ()
    if case_id is not None:
        query += " AND case_id = ?"
        params = (case_id,)
    query += " ORDER BY queue_rank ASC, created_at ASC, case_id ASC"

    with get_connection(db_path or get_db_path()) as connection:
        current_tick = _current_tick(connection)
        rows = connection.execute(query, params).fetchall()
    return [_snapshot_row(row, current_tick) for row in rows]


def get_case_queue_context(
    case_id: str,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        row = connection.execute(
            """
            SELECT
                case_id,
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
                updated_at
            FROM cases
            WHERE case_id = ?
            """,
            (case_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def get_affected_cases(
    old_ranks: dict[str, int | None],
    new_ranks: dict[str, int | None],
) -> list[str]:
    affected_case_ids: list[str] = []
    for case_id in sorted(set(old_ranks) | set(new_ranks)):
        if old_ranks.get(case_id) == new_ranks.get(case_id):
            continue
        affected_case_ids.append(case_id)
    return affected_case_ids


def advance_tick(db_path: Path | None = None) -> int:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        simulation_tick = _advance_tick(connection)
        connection.commit()
    return simulation_tick


def _snapshot_row(row: Any, current_tick: int) -> dict[str, Any]:
    item = dict(row)
    queue_position = item.get("queue_rank")
    previous_position = item.get("previous_rank")
    enqueue_tick = item.get("enqueue_tick")
    item["queue_position"] = queue_position
    item["previous_position"] = previous_position
    item["waiting_ticks"] = (
        None if enqueue_tick is None else max(0, current_tick - int(enqueue_tick))
    )
    item["current_tick"] = current_tick
    return item


def _placement_position_from_anchor(
    *,
    active_case_ids: list[str],
    placement_action: str,
    anchor_case_id: str | None,
) -> int:
    if placement_action == "go_to_top":
        return 1
    if placement_action == "go_to_bottom":
        return len(active_case_ids) + 1
    if placement_action == "hold_and_escalate":
        raise ValueError("hold_and_escalate cannot be applied to the queue")
    if anchor_case_id is None:
        raise ValueError(f"placement_action={placement_action} requires anchor_case_id")
    if anchor_case_id not in active_case_ids:
        raise ValueError(f"anchor_case_id={anchor_case_id} is not active in the queue")

    anchor_index = active_case_ids.index(anchor_case_id)
    if placement_action == "insert_before":
        return anchor_index + 1
    if placement_action == "insert_after":
        return anchor_index + 2
    raise ValueError(f"Unsupported placement_action={placement_action}")


def _placement_position_from_decision(
    *,
    active_case_ids: list[str],
    placement_action: str,
    anchor_case_id: str | None,
) -> int:
    if placement_action == "go_to_top":
        return 1
    if placement_action == "go_to_bottom":
        return len(active_case_ids) + 1
    if placement_action == "hold_and_escalate":
        raise ValueError("hold_and_escalate cannot be applied to the queue")
    return _placement_position_from_anchor(
        active_case_ids=active_case_ids,
        placement_action=placement_action,
        anchor_case_id=anchor_case_id,
    )


def _normalize_placement_decision(decision: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(decision)
    normalized["placement_action"] = _decision_placement_action(normalized)
    case_id = normalized.get("case_id")
    if case_id is not None:
        normalized["case_id"] = str(case_id)
    anchor_case_id = normalized.get("anchor_case_id")
    if anchor_case_id not in (None, ""):
        normalized["anchor_case_id"] = str(anchor_case_id)
    else:
        normalized["anchor_case_id"] = None
    return normalized


def _decision_case_id(decision: dict[str, Any]) -> str:
    case_id = decision.get("case_id")
    if case_id is None:
        raise ValueError("placement decision is missing case_id")
    return str(case_id)


def _decision_placement_action(decision: dict[str, Any]) -> str:
    placement_action = decision.get("placement_action")
    if placement_action is None:
        raise ValueError("placement decision is missing placement_action")
    return str(placement_action)


def _decision_anchor_case_id(decision: dict[str, Any]) -> str | None:
    anchor_case_id = decision.get("anchor_case_id")
    return None if anchor_case_id in (None, "") else str(anchor_case_id)


def _require_anchor_case_id(anchor_case_id: str | None) -> str:
    if anchor_case_id is None:
        raise ValueError("placement_action requires anchor_case_id")
    return anchor_case_id


def _load_case_row(connection: Any, case_id: str) -> Any | None:
    return connection.execute(
        """
        SELECT
            case_id,
            patient_code,
            status,
            payload,
            queue_rank,
            previous_rank,
            arrival_seq,
            enqueue_tick,
            start_tick,
            completion_tick
        FROM cases
        WHERE case_id = ?
        """,
        (case_id,),
    ).fetchone()


def _case_payload_from_row(case_row: Any | None) -> dict[str, Any]:
    if case_row is None:
        return {}
    payload = case_row["payload"]
    if payload in (None, ""):
        return {}
    return json.loads(payload)


def _resolve_patient_code(case_payload: dict[str, Any], case_row: Any | None) -> str | None:
    for key in ("patient_code", "PatientCode"):
        value = case_payload.get(key)
        if value not in (None, ""):
            return str(value)
    if case_row is not None and case_row["patient_code"] not in (None, ""):
        return str(case_row["patient_code"])
    return None


def _apply_queue_placement(
    *,
    case_id: str,
    placement_action: str,
    anchor_case_id: str | None,
    decision: dict[str, Any],
    case_payload: dict[str, Any] | None,
    db_path: Path | None,
) -> dict[str, Any]:
    init_db(db_path)
    now = _now()
    with get_connection(db_path or get_db_path()) as connection:
        simulation_tick = _advance_tick(connection)
        queue_version = _next_queue_version(connection)
        case_row = _load_case_row(connection, case_id)
        if case_row is not None and case_row["status"] == "completed":
            raise ValueError(f"case_id={case_id} is completed and cannot be repositioned")

        active_ids = _active_case_ids(connection)
        case_data = case_payload or _case_payload_from_row(case_row)
        if not case_data:
            raise ValueError(f"case_id={case_id} has no payload available for queue placement")
        patient_code = _resolve_patient_code(case_data, case_row)
        payload_json = json.dumps(case_data, sort_keys=True)
        case_inserted = _ensure_pending_case_record(
            connection,
            case_id=case_id,
            case_row=case_row,
            patient_code=patient_code,
            payload_json=payload_json,
            simulation_tick=simulation_tick,
            updated_at=now,
        )

        eligible_anchor_ids = [
            active_case_id for active_case_id in active_ids if active_case_id != case_id
        ]
        target_position = _placement_position_from_decision(
            active_case_ids=eligible_anchor_ids,
            placement_action=placement_action,
            anchor_case_id=anchor_case_id,
        )
        bounded_position = max(1, min(target_position, len(eligible_anchor_ids) + 1))
        ordered_case_ids = list(eligible_anchor_ids)
        ordered_case_ids.insert(bounded_position - 1, case_id)
        changed_case_ids = _apply_active_order(
            connection,
            ordered_case_ids,
            queue_version=queue_version,
            simulation_tick=simulation_tick,
            updated_at=now,
        )
        affected_case_ids = [
            affected_case_id
            for affected_case_id in changed_case_ids
            if affected_case_id != case_id
        ]

        _set_queue_version(connection, queue_version)
        from_rank = int(case_row["queue_rank"]) if case_row is not None and case_row["queue_rank"] is not None else None
        _log_event(
            connection,
            queue_version=queue_version,
            event_type="placement_applied",
            case_id=case_id,
            affected_case_ids=affected_case_ids,
            simulation_tick=simulation_tick,
            details={
                "placement_action": placement_action,
                "anchor_case_id": anchor_case_id,
                "requested_position": target_position,
                "applied_position": bounded_position,
                "from_rank": from_rank,
                "decision_payload": decision,
            },
        )
        if case_inserted:
            _log_event(
                connection,
                queue_version=queue_version,
                event_type="case_inserted",
                case_id=case_id,
                affected_case_ids=[case_id],
                simulation_tick=simulation_tick,
                details={
                    "queue_position": bounded_position,
                    "placement_action": placement_action,
                    "decision_payload": decision,
                },
            )
        if affected_case_ids:
            _log_event(
                connection,
                queue_version=queue_version,
                event_type="queue_reordered",
                case_id=case_id,
                affected_case_ids=affected_case_ids,
                simulation_tick=simulation_tick,
                details={
                    "placement_action": placement_action,
                    "anchor_case_id": anchor_case_id,
                    "decision_payload": decision,
                },
            )
        _log_event(
            connection,
            queue_version=queue_version,
            event_type="queue_version_incremented",
            case_id=case_id,
            affected_case_ids=affected_case_ids,
            simulation_tick=simulation_tick,
            details={
                "new_queue_version": queue_version,
                "decision_payload": decision,
            },
        )
        connection.commit()

    logger.info(
        "QUEUE_PLACEMENT_APPLIED case_id=%s placement_action=%s requested_position=%s affected_case_ids=%s version=%s tick=%s",
        case_id,
        placement_action,
        target_position,
        affected_case_ids,
        queue_version,
        simulation_tick,
    )
    return {
        "queue_version": queue_version,
        "simulation_tick": simulation_tick,
        "case_id": case_id,
        "queue_position": bounded_position,
        "affected_case_ids": affected_case_ids,
        "placement_action": placement_action,
        "anchor_case_id": anchor_case_id,
        "queue_snapshot": get_queue_snapshot(db_path=db_path),
    }


def _ensure_pending_case_record(
    connection: Any,
    *,
    case_id: str,
    case_row: Any | None,
    patient_code: str | None,
    payload_json: str,
    simulation_tick: int,
    updated_at: str,
) -> bool:
    if case_row is None:
        arrival_seq = _next_arrival_seq(connection)
        connection.execute(
            """
            INSERT INTO cases (
                case_id,
                patient_code,
                status,
                payload,
                final_result,
                created_at,
                updated_at,
                priority_score,
                previous_rank,
                queue_rank,
                rank_change,
                queue_version,
                arrival_seq,
                enqueue_tick,
                start_tick,
                completion_tick,
                human_packet,
                human_status,
                human_due_at,
                human_decision,
                human_decision_notes,
                human_decided_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                patient_code,
                "pending",
                payload_json,
                None,
                updated_at,
                updated_at,
                None,
                None,
                None,
                None,
                None,
                arrival_seq,
                simulation_tick,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ),
        )
        return True

    existing_arrival_seq = case_row["arrival_seq"]
    arrival_seq = int(existing_arrival_seq) if existing_arrival_seq is not None else _next_arrival_seq(connection)
    existing_enqueue_tick = case_row["enqueue_tick"]
    enqueue_tick = int(existing_enqueue_tick) if existing_enqueue_tick is not None else simulation_tick
    connection.execute(
        """
        UPDATE cases
        SET patient_code = ?,
            status = 'pending',
            payload = ?,
            final_result = NULL,
            updated_at = ?,
            arrival_seq = ?,
            enqueue_tick = ?,
            completion_tick = NULL,
            human_packet = NULL,
            human_status = NULL,
            human_due_at = NULL,
            human_decision = NULL,
            human_decision_notes = NULL,
            human_decided_at = NULL
        WHERE case_id = ?
        """,
        (
            patient_code,
            payload_json,
            updated_at,
            arrival_seq,
            enqueue_tick,
            case_id,
        ),
    )
    return case_row["status"] != "pending"


def _active_case_ids(connection: Any) -> list[str]:
    rows = connection.execute(
        """
        SELECT case_id
        FROM cases
        WHERE status = 'pending'
        ORDER BY queue_rank ASC, arrival_seq ASC, case_id ASC
        """
    ).fetchall()
    return [str(row["case_id"]) for row in rows]


def _active_queue_count(connection: Any) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS active_count FROM cases WHERE status = 'pending'"
    ).fetchone()
    return int(row["active_count"])


def _apply_active_order(
    connection: Any,
    ordered_case_ids: list[str],
    *,
    queue_version: int,
    simulation_tick: int,
    updated_at: str,
) -> list[str]:
    old_positions = _active_positions(connection)
    affected_case_ids: list[str] = []
    for index, case_id in enumerate(ordered_case_ids, start=1):
        old_position = old_positions.get(case_id)
        rank_change = None if old_position is None else old_position - index
        start_tick = simulation_tick if index == 1 else None
        if old_position != index:
            affected_case_ids.append(case_id)
        connection.execute(
            """
            UPDATE cases
            SET previous_rank = ?,
                queue_rank = ?,
                rank_change = ?,
                queue_version = ?,
                start_tick = COALESCE(start_tick, ?),
                updated_at = ?
            WHERE case_id = ?
            """,
            (
                old_position,
                index,
                rank_change,
                queue_version,
                start_tick,
                updated_at,
                case_id,
            ),
        )
    return affected_case_ids


def _active_positions(connection: Any) -> dict[str, int | None]:
    rows = connection.execute(
        """
        SELECT case_id, queue_rank
        FROM cases
        WHERE status = 'pending'
        """
    ).fetchall()
    return {
        str(row["case_id"]): (
            int(row["queue_rank"]) if row["queue_rank"] is not None else None
        )
        for row in rows
    }


def _current_tick(connection: Any) -> int:
    row = connection.execute(
        "SELECT current_tick FROM queue_state WHERE id = 1"
    ).fetchone()
    return int(row["current_tick"]) if row is not None else 0


def _advance_tick(connection: Any) -> int:
    current_tick = _current_tick(connection) + 1
    connection.execute(
        "UPDATE queue_state SET current_tick = ? WHERE id = 1",
        (current_tick,),
    )
    return current_tick


def _next_arrival_seq(connection: Any) -> int:
    row = connection.execute(
        "SELECT arrival_seq FROM queue_state WHERE id = 1"
    ).fetchone()
    arrival_seq = (int(row["arrival_seq"]) if row is not None else 0) + 1
    connection.execute(
        "UPDATE queue_state SET arrival_seq = ? WHERE id = 1",
        (arrival_seq,),
    )
    return arrival_seq


def _set_queue_version(connection: Any, queue_version: int) -> None:
    connection.execute(
        "UPDATE queue_state SET queue_version = ? WHERE id = 1",
        (queue_version,),
    )


def _row_to_pending_case(row: Any) -> PendingCase:
    return PendingCase(
        case_id=row["case_id"],
        patient_code=row["patient_code"],
        status=row["status"],
        payload=json.loads(row["payload"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        priority_score=row["priority_score"],
        queue_rank=row["queue_rank"],
        previous_rank=row["previous_rank"],
        rank_change=row["rank_change"],
        queue_version=row["queue_version"],
        arrival_seq=row["arrival_seq"],
        enqueue_tick=row["enqueue_tick"],
        start_tick=row["start_tick"],
        completion_tick=row["completion_tick"],
        manual_priority_override=row["manual_priority_override"],
    )


def _extract_priority_inputs(case_row: PendingCase) -> dict[str, Any]:
    payload = case_row.payload
    normalized: dict[str, Any] = {}
    for field_name, keys in PAYLOAD_FIELD_MAP.items():
        value = _first_present(payload, keys)
        if field_name == "manual_priority_override" and case_row.manual_priority_override is not None:
            value = case_row.manual_priority_override
        elif field_name == "waiting_time_minutes" and value is None:
            value = _compute_waiting_time_minutes(payload, case_row.created_at)
        elif field_name == "urgency_score" and value is None:
            value = _compute_urgency_score(payload)
        if field_name in NUMERIC_FIELDS:
            normalized[field_name] = _as_number(value)
        else:
            normalized[field_name] = _as_clean_string(value)

    normalized["waiting_time_minutes"] = (
        int(normalized["waiting_time_minutes"])
        if normalized["waiting_time_minutes"] is not None
        else _compute_waiting_time_minutes(payload, case_row.created_at)
    )
    normalized["urgency_score"] = (
        int(normalized["urgency_score"])
        if normalized["urgency_score"] is not None
        else _compute_urgency_score(payload)
    )
    return normalized


def _compute_urgency_score(payload: dict[str, Any]) -> int:
    avpu = (_as_clean_string(_first_present(payload, PAYLOAD_FIELD_MAP["avpu"])) or "").upper()
    pain_grade = _as_number(_first_present(payload, PAYLOAD_FIELD_MAP["pain_grade"]))
    spo2 = _as_number(_first_present(payload, PAYLOAD_FIELD_MAP["spo2"]))

    score = 0
    if avpu and avpu != "A":
        score += 2
    if pain_grade is not None:
        if pain_grade >= 7:
            score += 2
        elif pain_grade >= 4:
            score += 1
    if spo2 is not None:
        if spo2 < 92:
            score += 3
        elif spo2 < 95:
            score += 1
    return min(score, 15)


def _compute_waiting_time_minutes(payload: dict[str, Any], created_at: str) -> int | None:
    direct_minutes = _as_number(payload.get("waiting_time_minutes"))
    if direct_minutes is not None:
        return max(0, int(direct_minutes))
    return None


def _missing_data_penalty(normalized: dict[str, Any]) -> float:
    penalty = 0.0
    if normalized.get("patient_code") in (None, ""):
        penalty += 20.0
    for field_name in ("urgency_score", "spo2", "avpu"):
        if normalized.get(field_name) in (None, ""):
            penalty += 1.5
    return penalty


def _next_queue_version(connection: Any) -> int:
    row = connection.execute(
        """
        SELECT MAX(version) + 1 AS next_version
        FROM (
            SELECT COALESCE(MAX(queue_version), 0) AS version FROM cases
            UNION ALL
            SELECT COALESCE(MAX(queue_version), 0) AS version FROM queue_events
            UNION ALL
            SELECT COALESCE(queue_version, 0) AS version FROM queue_state WHERE id = 1
        )
        """
    ).fetchone()
    return int(row["next_version"])


def _log_event(
    connection: Any,
    *,
    queue_version: int,
    event_type: str,
    case_id: str | None,
    details: dict[str, Any],
    affected_case_ids: list[str] | None = None,
    simulation_tick: int | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO queue_events (
            queue_version,
            event_type,
            case_id,
            affected_case_ids,
            simulation_tick,
            details,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            queue_version,
            event_type,
            case_id,
            json.dumps(affected_case_ids or []),
            simulation_tick,
            json.dumps(details, sort_keys=True),
            _now(),
        ),
    )


def _first_present(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _as_clean_string(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _as_number(value: Any) -> int | float | None:
    cleaned = _as_clean_string(value)
    if cleaned is None:
        return None
    number = float(cleaned)
    if number.is_integer():
        return int(number)
    return number


def _parse_datetime(value: Any) -> datetime | None:
    cleaned = _as_clean_string(value)
    if cleaned is None:
        return None
    candidate = cleaned.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sort_wait_minutes(waiting_time_minutes: Any) -> int:
    if waiting_time_minutes is None:
        return 0
    return -int(waiting_time_minutes)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
