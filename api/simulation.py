from __future__ import annotations

import asyncio
import csv
import json
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from storage.db import REPO_ROOT, get_connection
from storage.queue_engine import complete_top_case
from storage.queue_store import insert_case

SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from labslabs.band_dispatch import dispatch_case


CSV_PATH = REPO_ROOT / "data" / "input.csv"


@dataclass
class SimulationStatus:
    run_id: str | None = None
    status: str = "idle"
    total_rows: int = 0
    completed_rows: int = 0
    current_case_id: str | None = None
    current_row_number: int | None = None
    message: str | None = None
    started_at: float | None = None
    updated_at: float | None = None
    row_numbers: list[int] | None = None
    departures: int = 0
    speed_multiplier: float = 1.0


_lock = threading.RLock()
_stop_event = threading.Event()
_worker: threading.Thread | None = None
_status = SimulationStatus()
_speed_multiplier = 1.0


def get_status() -> dict[str, Any]:
    with _lock:
        return asdict(_status)


def set_speed_multiplier(value: float) -> dict[str, Any]:
    global _speed_multiplier
    clamped = max(0.25, min(8.0, float(value)))
    with _lock:
        _speed_multiplier = clamped
        _status.speed_multiplier = clamped
        _status.updated_at = time.time()
        if _status.status == "running":
            _status.message = f"Simulation speed set to {clamped:.2f}x."
        return asdict(_status)


def stop_run() -> dict[str, Any]:
    global _status
    with _lock:
        if _worker is None or not _worker.is_alive():
            _status.status = "idle"
            _status.message = "No simulation is running."
            _status.updated_at = time.time()
            return asdict(_status)
        _stop_event.set()
        _status.status = "stopping"
        _status.message = "Stop requested."
        _status.updated_at = time.time()
        return asdict(_status)


def start_run(
    *,
    row_numbers: list[int] | None = None,
    arrival_gap_seconds: float = 5.0,
    start_delay_seconds: float = 0.0,
    top_leave_after_seconds: float = 12.0,
    limit: int = 3,
) -> dict[str, Any]:
    global _worker, _status

    with _lock:
        if _worker is not None and _worker.is_alive():
            raise RuntimeError("A simulation is already running.")

        reset_to_empty_queue()
        selected_row_numbers = row_numbers or _default_row_numbers(limit=limit)
        if not selected_row_numbers:
            raise RuntimeError("No runnable CSV rows were found.")

        _stop_event.clear()
        _status = SimulationStatus(
            run_id=str(uuid.uuid4()),
            status="running",
            total_rows=len(selected_row_numbers),
            completed_rows=0,
            current_case_id=None,
            current_row_number=None,
            message="Simulation started.",
            started_at=time.time(),
            updated_at=time.time(),
            row_numbers=selected_row_numbers,
            speed_multiplier=_speed_multiplier,
        )

        _worker = threading.Thread(
            target=_run,
            kwargs={
                "row_numbers": selected_row_numbers,
                "arrival_gap_seconds": arrival_gap_seconds,
                "start_delay_seconds": start_delay_seconds,
                "top_leave_after_seconds": top_leave_after_seconds,
            },
            daemon=False,
        )
        _worker.start()
        return asdict(_status)


def _run(
    *,
    row_numbers: list[int],
    arrival_gap_seconds: float,
    start_delay_seconds: float,
    top_leave_after_seconds: float,
) -> None:
    global _status
    try:
        if start_delay_seconds > 0:
            time.sleep(start_delay_seconds)

        last_departure_time = time.monotonic()
        for index, row_number in enumerate(row_numbers, start=1):
            if _stop_event.is_set():
                with _lock:
                    _status.status = "stopped"
                    _status.message = "Simulation stopped."
                    _status.updated_at = time.time()
                return

            row = _load_row(row_number)
            case_id = (row.get("triage_code") or "").strip()
            patient_code = (row.get("PatientCode") or "").strip() or None
            if not case_id or not patient_code:
                with _lock:
                    _status.completed_rows = index
                    _status.current_row_number = row_number
                    _status.message = f"Skipped row {row_number} because it has no patient code."
                    _status.updated_at = time.time()
                continue

            insert_case(
                case_id=case_id,
                patient_code=patient_code,
                status="pending",
                payload=row,
                final_result=None,
            )
            inserted_queue_version = _case_queue_version(case_id)
            with _lock:
                _status.current_case_id = case_id
                _status.current_row_number = row_number
                _status.message = f"Inserted case {case_id}; handing off to Band."
                _status.completed_rows = index - 1
                _status.updated_at = time.time()

            asyncio.run(dispatch_case(case_id))
            _wait_for_case_workflow_completion(
                case_id=case_id,
                inserted_queue_version=inserted_queue_version,
            )

            with _lock:
                _status.completed_rows = index
                _status.message = f"Placed case {case_id} after review and moderator evaluation."
                _status.updated_at = time.time()

            if index < len(row_numbers) and arrival_gap_seconds > 0:
                _sleep_for_next_arrival(delay_seconds=arrival_gap_seconds)

        while _has_active_cases():
            if _stop_event.is_set():
                with _lock:
                    _status.status = "stopped"
                    _status.message = "Simulation stopped."
                    _status.updated_at = time.time()
                return
            last_departure_time = _sleep_until_next_arrival(
                delay_seconds=top_leave_after_seconds,
                last_departure_time=last_departure_time,
                top_leave_after_seconds=top_leave_after_seconds,
            )

        with _lock:
            _status.status = "completed"
            _status.message = "Simulation complete. Queue is now empty. Ready to start a new simulation."
            _status.updated_at = time.time()
    except Exception as exc:  # pragma: no cover - defensive
        with _lock:
            _status.status = "failed"
            _status.message = str(exc)
            _status.updated_at = time.time()


def _default_row_numbers(*, limit: int) -> list[int]:
    row_numbers: list[int] = []
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            case_id = (row.get("triage_code") or "").strip()
            patient_code = (row.get("PatientCode") or "").strip()
            if not case_id or not patient_code:
                continue
            row_numbers.append(index)
            if len(row_numbers) >= limit:
                break
    return row_numbers


def _case_queue_version(case_id: str) -> int:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COALESCE(queue_version, 0) AS queue_version
            FROM cases
            WHERE case_id = ?
            """,
            (case_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError(f"Case not found after insert: {case_id}")
    return int(row["queue_version"] or 0)


def reset_to_empty_queue() -> None:
    global _status
    with get_connection() as connection:
        connection.execute("DELETE FROM queue_events")
        connection.execute("DELETE FROM cases")
        connection.execute(
            """
            UPDATE queue_state
            SET current_tick = 0,
                arrival_seq = 0,
                queue_version = 0
            WHERE id = 1
            """
        )
        connection.commit()
    with _lock:
        _status = SimulationStatus(speed_multiplier=_speed_multiplier, updated_at=time.time())


def reset_simulation() -> dict[str, Any]:
    with _lock:
        if _worker is not None and _worker.is_alive():
            raise RuntimeError("Cannot reset while a simulation is running.")
    reset_to_empty_queue()
    return get_status()


def _has_active_cases() -> bool:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM cases
            WHERE status IN ('pending', 'routed', 'reviewed')
            """
        ).fetchone()
    return bool(row and row["count"])


def _effective_delay(delay_seconds: float) -> float:
    with _lock:
        speed_multiplier = _speed_multiplier
    if delay_seconds <= 0:
        return 0.0
    return delay_seconds / max(0.25, speed_multiplier)


def _sleep_until_next_arrival(
    *,
    delay_seconds: float,
    last_departure_time: float,
    top_leave_after_seconds: float,
) -> float:
    effective_delay = _effective_delay(delay_seconds)
    if effective_delay <= 0:
        return _maybe_depart_top_case(
            last_departure_time=last_departure_time,
            top_leave_after_seconds=top_leave_after_seconds,
        )

    end_time = time.monotonic() + effective_delay
    departure_time = last_departure_time
    while time.monotonic() < end_time:
        if _stop_event.is_set():
            return departure_time
        departure_time = _maybe_depart_top_case(
            last_departure_time=departure_time,
            top_leave_after_seconds=top_leave_after_seconds,
        )
        time.sleep(min(0.5, max(0.0, end_time - time.monotonic())))
    return _maybe_depart_top_case(
        last_departure_time=departure_time,
        top_leave_after_seconds=top_leave_after_seconds,
    )


def _sleep_for_next_arrival(*, delay_seconds: float) -> None:
    effective_delay = _effective_delay(delay_seconds)
    if effective_delay <= 0:
        return

    end_time = time.monotonic() + effective_delay
    while time.monotonic() < end_time:
        if _stop_event.is_set():
            return
        time.sleep(min(0.5, max(0.0, end_time - time.monotonic())))


def _wait_for_case_workflow_completion(
    *,
    case_id: str,
    inserted_queue_version: int,
    timeout_seconds: float = 120.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _stop_event.is_set():
            raise RuntimeError("Simulation stopped while waiting for case workflow completion.")

        placement = _load_case_placement_event(
            case_id=case_id,
            inserted_queue_version=inserted_queue_version,
        )
        if placement is not None:
            with _lock:
                _status.message = (
                    f"Case {case_id} placement recorded as {placement['event_type']} "
                    f"(queue v{placement['queue_version']})."
                )
                _status.updated_at = time.time()
            return

        with _lock:
            _status.message = f"Waiting for review and moderator placement for case {case_id}..."
            _status.updated_at = time.time()
        time.sleep(0.5)

    raise RuntimeError(
        f"Timed out waiting for review and moderator placement for case {case_id}."
    )


def _load_case_placement_event(
    *,
    case_id: str,
    inserted_queue_version: int,
) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT event_type, queue_version, details, created_at
            FROM queue_events
            WHERE case_id = ?
              AND event_type IN ('placement_applied', 'case_escalated')
              AND COALESCE(queue_version, 0) > ?
            ORDER BY created_at DESC, event_id DESC
            LIMIT 1
            """,
            (case_id, inserted_queue_version),
        ).fetchone()
    if row is None:
        return None
    details = row["details"]
    if isinstance(details, str) and details.strip():
        try:
            details = json.loads(details)
        except json.JSONDecodeError:
            pass
    return {
        "event_type": row["event_type"],
        "queue_version": int(row["queue_version"] or 0),
        "details": details,
        "created_at": row["created_at"],
    }


def _maybe_depart_top_case(*, last_departure_time: float, top_leave_after_seconds: float) -> float:
    global _status
    if top_leave_after_seconds <= 0:
        return last_departure_time
    now = time.monotonic()
    if now - last_departure_time < top_leave_after_seconds:
        return last_departure_time

    result = complete_top_case(final_result="simulated queue departure")
    if result is None:
        return now

    with _lock:
        _status.departures += 1
        _status.message = f"Top case {result['case_id']} left the queue."
        _status.updated_at = time.time()
    return now


def _load_row(row_number: int) -> dict[str, str]:
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            if index == row_number:
                return row
    raise RuntimeError(f"CSV row not found: {row_number}")
