from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .db import get_connection, get_db_path, init_db

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaseRecord:
    case_id: str
    patient_code: str | None
    status: str
    payload: dict[str, Any]
    final_result: str | None
    created_at: str
    updated_at: str
    dispatch_requested_at: str | None
    dispatch_trigger_id: str | None
    dispatch_room_id: str | None


def insert_case(
    *,
    case_id: str,
    patient_code: str | None,
    status: str,
    payload: dict[str, Any],
    final_result: str | None = None,
    db_path: Path | None = None,
) -> None:
    if status == "pending":
        from .queue_engine import enqueue_case

        enqueue_case(
            case_id=case_id,
            patient_code=patient_code,
            payload=payload,
            db_path=db_path,
        )
        return

    init_db(db_path)
    now = _now()
    with get_connection(db_path or get_db_path()) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO cases (
                case_id,
                patient_code,
                status,
                payload,
                final_result,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                patient_code,
                status,
                json.dumps(payload),
                final_result,
                now,
                now,
            ),
        )
        connection.commit()


def get_next_pending_case(db_path: Path | None = None) -> CaseRecord | None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        row = connection.execute(
            """
            SELECT
                case_id,
                patient_code,
                status,
                payload,
                final_result,
                created_at,
                updated_at,
                dispatch_requested_at,
                dispatch_trigger_id,
                dispatch_room_id
            FROM cases
            WHERE status = 'pending'
              AND patient_code IS NOT NULL
              AND TRIM(patient_code) != ''
            ORDER BY
              CASE WHEN queue_rank IS NULL THEN 1 ELSE 0 END ASC,
              queue_rank ASC,
              created_at ASC,
              case_id ASC
            LIMIT 1
            """
        ).fetchone()
    return _row_to_case_record(row)


def get_case(case_id: str, db_path: Path | None = None) -> CaseRecord | None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        row = connection.execute(
            """
            SELECT
                case_id,
                patient_code,
                status,
                payload,
                final_result,
                created_at,
                updated_at,
                dispatch_requested_at,
                dispatch_trigger_id,
                dispatch_room_id
            FROM cases
            WHERE case_id = ?
            """,
            (case_id,),
        ).fetchone()
    return _row_to_case_record(row)


def claim_case_dispatch(
    case_id: str,
    *,
    trigger_id: str,
    requested_at: str,
    room_id: str | None = None,
    db_path: Path | None = None,
) -> bool:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        result = connection.execute(
            """
            UPDATE cases
            SET dispatch_requested_at = ?,
                dispatch_trigger_id = ?,
                dispatch_room_id = ?,
                updated_at = ?
            WHERE case_id = ?
              AND status = 'pending'
              AND dispatch_requested_at IS NULL
            """,
            (
                requested_at,
                trigger_id,
                room_id,
                requested_at,
                case_id,
            ),
        )
        connection.commit()
        return result.rowcount > 0


def bind_case_dispatch_room(
    case_id: str,
    *,
    trigger_id: str,
    room_id: str,
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        connection.execute(
            """
            UPDATE cases
            SET dispatch_room_id = ?,
                updated_at = ?
            WHERE case_id = ?
              AND dispatch_trigger_id = ?
            """,
            (room_id, _now(), case_id, trigger_id),
        )
        connection.commit()


def release_case_dispatch_claim(
    case_id: str,
    *,
    trigger_id: str | None = None,
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    query = """
        UPDATE cases
        SET dispatch_requested_at = NULL,
            dispatch_trigger_id = NULL,
            dispatch_room_id = NULL,
            updated_at = ?
        WHERE case_id = ?
    """
    params: list[Any] = [_now(), case_id]
    if trigger_id is not None:
        query += " AND dispatch_trigger_id = ?"
        params.append(trigger_id)
    with get_connection(db_path or get_db_path()) as connection:
        connection.execute(query, tuple(params))
        connection.commit()


def get_shared_room_id(db_path: Path | None = None) -> str | None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        row = connection.execute(
            "SELECT shared_room_id FROM queue_state WHERE id = 1"
        ).fetchone()
    if row is None:
        return None
    value = row["shared_room_id"]
    if value is None:
        return None
    room_id = str(value).strip()
    return room_id or None


def set_shared_room_id(room_id: str, db_path: Path | None = None) -> None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        connection.execute(
            """
            UPDATE queue_state
            SET shared_room_id = ?
            WHERE id = 1
            """,
            (room_id,),
        )
        connection.commit()


def clear_shared_room_id(db_path: Path | None = None) -> None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        connection.execute(
            """
            UPDATE queue_state
            SET shared_room_id = NULL
            WHERE id = 1
            """
        )
        connection.commit()


def mark_routed(case_id: str, db_path: Path | None = None) -> None:
    _update_status(case_id, "routed", db_path=db_path)


def mark_reviewed(case_id: str, db_path: Path | None = None) -> None:
    _update_status(case_id, "reviewed", db_path=db_path)


def mark_escalated(case_id: str, db_path: Path | None = None) -> None:
    _update_escalation(
        case_id,
        status="escalated",
        human_status="pending",
        db_path=db_path,
    )


def mark_escalated_with_handoff(
    case_id: str,
    *,
    handoff_packet: str,
    due_at: str | None = None,
    db_path: Path | None = None,
) -> None:
    _update_escalation(
        case_id,
        status="escalated",
        human_status="pending",
        handoff_packet=handoff_packet,
        due_at=due_at,
        db_path=db_path,
    )


def mark_completed(
    case_id: str,
    final_result: str,
    db_path: Path | None = None,
) -> None:
    from .queue_engine import complete_top_case

    case_record = get_case(case_id, db_path=db_path)
    if case_record is not None and case_record.status == "pending":
        top_case = get_next_pending_case(db_path=db_path)
        if top_case is None:
            return
        if top_case.case_id != case_id:
            raise ValueError(
                f"Only the top queued case can complete; requested {case_id}, top is {top_case.case_id}"
            )
        top_result = complete_top_case(final_result=final_result, db_path=db_path)
        if top_result is None:
            return
        logger.info("CASE_COMPLETED case_id=%s", case_id)
        return

    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        connection.execute(
            """
            UPDATE cases
            SET status = ?, final_result = ?, updated_at = ?
            WHERE case_id = ?
            """,
            ("completed", final_result, _now(), case_id),
        )
        connection.commit()
    logger.info("CASE_COMPLETED case_id=%s", case_id)


def log_moderator_decision(
    case_id: str,
    *,
    decision: dict[str, Any],
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        connection.execute(
            """
            INSERT INTO queue_events (
                queue_version,
                event_type,
                case_id,
                details,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                None,
                "moderator_decision",
                case_id,
                json.dumps(decision),
                _now(),
            ),
        )
        connection.commit()
    logger.info("MODERATOR_DECISION_LOGGED case_id=%s", case_id)


def log_clinical_urgency(
    case_id: str,
    *,
    decision: dict[str, Any],
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        connection.execute(
            """
            INSERT INTO queue_events (
                queue_version,
                event_type,
                case_id,
                details,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                None,
                "clinical_urgency_determined",
                case_id,
                json.dumps(decision, sort_keys=True),
                _now(),
            ),
        )
        connection.commit()
    logger.info("CLINICAL_URGENCY_LOGGED case_id=%s", case_id)


def log_delay_harm_assessment(
    case_id: str,
    *,
    assessment: dict[str, Any],
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        connection.execute(
            """
            INSERT INTO queue_events (
                queue_version,
                event_type,
                case_id,
                details,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                None,
                "delay_harm_assessment",
                case_id,
                json.dumps(assessment, sort_keys=True),
                _now(),
            ),
        )
        connection.commit()
    logger.info("DELAY_HARM_ASSESSMENT_LOGGED case_id=%s", case_id)


def log_human_decision(
    connection: Any,
    *,
    case_id: str,
    decision: str,
    outcome: str,
    notes: str | None,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO queue_events (
            queue_version,
            event_type,
            case_id,
            affected_case_ids,
            details,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            None,
            "human_decision_applied",
            case_id,
            json.dumps([case_id]),
            json.dumps(
                {
                    "decision": decision,
                    "outcome": outcome,
                    "notes": notes,
                    "summary": f"Human decision applied: {decision.replace('_', ' ')}.",
                },
                sort_keys=True,
            ),
            created_at,
        ),
    )


def apply_human_decision(
    case_id: str,
    *,
    decision: str,
    notes: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    init_db(db_path)
    now = _now()
    with get_connection(db_path or get_db_path()) as connection:
        row = connection.execute(
            """
            SELECT case_id, patient_code, status, payload, human_packet, human_due_at
            FROM cases
            WHERE case_id = ?
            """,
            (case_id,),
        ).fetchone()
        if row is None:
            return None
        if row["status"] != "escalated":
            logger.info(
                "HUMAN_DECISION_SKIPPED case_id=%s status=%s",
                case_id,
                row["status"],
            )
            return None

        if decision == "approve":
            result = {
                "message_type": "human_decision_result",
                "case_id": case_id,
                "decision": decision,
                "outcome": "completed",
                "summary": f"Human approved escalated case {case_id}.",
                "notes": notes,
            }
            connection.execute(
                """
                UPDATE cases
                SET status = ?,
                    final_result = ?,
                    human_status = ?,
                    human_decision = ?,
                    human_decision_notes = ?,
                    human_decided_at = ?,
                    dispatch_requested_at = COALESCE(dispatch_requested_at, ?),
                    updated_at = ?
                WHERE case_id = ?
                """,
                (
                    "completed",
                    json.dumps(result),
                    "approved",
                    decision,
                    notes,
                    now,
                    now,
                    now,
                    case_id,
                ),
            )
            log_human_decision(
                connection,
                case_id=case_id,
                decision=decision,
                outcome="completed",
                notes=notes,
                created_at=now,
            )
            connection.commit()
            logger.info("HUMAN_DECISION_APPLIED case_id=%s decision=%s", case_id, decision)
            return result

        # return_to_review: reset to pending and carry notes into payload so agents see them
        existing_payload_row = connection.execute(
            "SELECT payload FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        updated_payload: dict[str, Any] = {}
        if existing_payload_row and existing_payload_row["payload"]:
            try:
                updated_payload = json.loads(existing_payload_row["payload"])
            except json.JSONDecodeError:
                pass
        if notes:
            updated_payload["human_review_notes"] = notes
        updated_payload["human_review_decision"] = decision
        updated_payload["human_review_returned_at"] = now

        result = {
            "message_type": "human_decision_result",
            "case_id": case_id,
            "decision": decision,
            "outcome": "returned_to_review",
            "summary": f"Human returned escalated case {case_id} to review.",
            "notes": notes,
        }
        connection.execute(
            """
            UPDATE cases
            SET final_result = NULL,
                human_status = ?,
                human_decision = ?,
                human_decision_notes = ?,
                human_decided_at = ?,
                updated_at = ?
            WHERE case_id = ?
            """,
            (
                "returned_to_review",
                decision,
                notes,
                now,
                now,
                case_id,
            ),
        )
        log_human_decision(
            connection,
            case_id=case_id,
            decision=decision,
            outcome="returned_to_review",
            notes=notes,
            created_at=now,
        )
        connection.commit()
    insert_case(
        case_id=case_id,
        patient_code=row["patient_code"],
        status="pending",
        payload=updated_payload,
        final_result=None,
        db_path=db_path,
    )
    logger.info("HUMAN_DECISION_APPLIED case_id=%s decision=%s", case_id, decision)
    return result


def expire_human_reviews(
    *,
    due_before: datetime | None = None,
    db_path: Path | None = None,
) -> list[str]:
    init_db(db_path)
    cutoff = due_before or datetime.now(timezone.utc)
    now = _now()
    expired: list[str] = []
    with get_connection(db_path or get_db_path()) as connection:
        rows = connection.execute(
            """
            SELECT case_id, human_due_at
            FROM cases
            WHERE status = 'escalated'
              AND COALESCE(human_status, 'pending') = 'pending'
              AND human_due_at IS NOT NULL
            """,
        ).fetchall()
        for row in rows:
            due_at = _parse_datetime(row["human_due_at"])
            if due_at is None or due_at > cutoff:
                continue
            case_id = row["case_id"]
            expired.append(case_id)
            result = {
                "message_type": "human_decision_result",
                "case_id": case_id,
                "decision": "approve",
                "outcome": "timed_out",
                "summary": f"Human decision timed out for case {case_id}.",
                "notes": "Timed out before human response",
            }
            connection.execute(
                """
                UPDATE cases
                SET status = ?,
                    final_result = ?,
                    human_status = ?,
                    human_decision = ?,
                    human_decision_notes = ?,
                    human_decided_at = ?,
                    dispatch_requested_at = COALESCE(dispatch_requested_at, ?),
                    updated_at = ?
                WHERE case_id = ?
                """,
                (
                    "completed",
                    json.dumps(result),
                    "timed_out",
                    "timeout",
                    "Timed out before human response",
                    now,
                    now,
                    now,
                    case_id,
                ),
            )
        connection.commit()
    return expired


def reset_case(case_id: str, db_path: Path | None = None) -> None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        connection.execute(
            """
            UPDATE cases
            SET status = ?,
                final_result = NULL,
                queue_rank = NULL,
                previous_rank = NULL,
                rank_change = NULL,
                queue_version = NULL,
                start_tick = NULL,
                completion_tick = NULL,
                dispatch_requested_at = NULL,
                dispatch_trigger_id = NULL,
                dispatch_room_id = NULL,
                updated_at = ?
            WHERE case_id = ?
            """,
            ("pending", _now(), case_id),
        )
        connection.commit()
    logger.info("CASE_RESET case_id=%s", case_id)


def update_case_payload(
    case_id: str,
    payload_updates: dict[str, Any],
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        row = connection.execute(
            "SELECT payload, patient_code FROM cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        if row is None:
            return

        payload = json.loads(row["payload"])
        payload.update(payload_updates)
        patient_code = (
            payload_updates.get("patient_code")
            or row["patient_code"]
        )
        connection.execute(
            """
            UPDATE cases
            SET payload = ?, patient_code = ?, updated_at = ?
            WHERE case_id = ?
            """,
            (json.dumps(payload), patient_code, _now(), case_id),
        )
        connection.commit()


def _update_status(case_id: str, status: str, db_path: Path | None = None) -> None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        connection.execute(
            """
            UPDATE cases
            SET status = ?, updated_at = ?
            WHERE case_id = ?
            """,
            (status, _now(), case_id),
        )
        connection.commit()


def _update_escalation(
    case_id: str,
    *,
    status: str,
    human_status: str | None,
    handoff_packet: str | None = None,
    due_at: str | None = None,
    db_path: Path | None = None,
) -> None:
    init_db(db_path)
    with get_connection(db_path or get_db_path()) as connection:
        connection.execute(
            """
            UPDATE cases
            SET status = ?,
                human_packet = COALESCE(?, human_packet),
                human_status = ?,
                human_due_at = COALESCE(?, human_due_at),
                human_decision = NULL,
                human_decision_notes = NULL,
                human_decided_at = NULL,
                dispatch_requested_at = COALESCE(dispatch_requested_at, ?),
                updated_at = ?
            WHERE case_id = ?
            """,
            (
                status,
                handoff_packet,
                human_status,
                due_at,
                _now(),
                _now(),
                case_id,
            ),
        )
        connection.commit()


def _row_to_case_record(row: Any) -> CaseRecord | None:
    if row is None:
        return None
    return CaseRecord(
        case_id=row["case_id"],
        patient_code=row["patient_code"],
        status=row["status"],
        payload=json.loads(row["payload"]),
        final_result=row["final_result"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        dispatch_requested_at=row["dispatch_requested_at"],
        dispatch_trigger_id=row["dispatch_trigger_id"],
        dispatch_room_id=row["dispatch_room_id"],
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
