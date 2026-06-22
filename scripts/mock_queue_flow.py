from __future__ import annotations

import argparse
import csv
import json
import logging
import asyncio
import time

from _bootstrap import add_src_to_path

add_src_to_path()

from storage.db import REPO_ROOT, get_connection, init_db
from storage.queue_engine import complete_top_case
from storage.queue_engine import get_queue_snapshot
from storage.queue_store import get_next_pending_case, insert_case
from labslabs.band_dispatch import dispatch_case, dispatch_next_pending_case

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CSV_PATH = REPO_ROOT / "data" / "input.csv"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare and simulate a mock CT priority queue flow."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Reset the simulation to an empty queue.",
    )
    prepare_parser.add_argument(
        "--base-time",
        help="Deprecated; simulation queues use ticks instead of timestamps.",
    )
    prepare_parser.add_argument(
        "--spacing-minutes",
        type=int,
        default=7,
        help="Deprecated; simulation queues use ticks instead of timestamp spacing.",
    )

    enqueue_parser = subparsers.add_parser(
        "enqueue",
        help="Insert one CSV case into the mock queue.",
    )
    enqueue_parser.add_argument("--case-id", help="CSV triage_code to seed")
    enqueue_parser.add_argument(
        "--row-number",
        type=int,
        help="1-based data row in input.csv, excluding the header",
    )
    enqueue_parser.add_argument(
        "--arrived-minutes-ago",
        type=int,
        default=0,
        help="Deprecated; arrivals advance the simulation clock by one tick.",
    )
    enqueue_parser.add_argument(
        "--dispatch-next",
        action="store_true",
        help="After enqueueing, hand the current top pending case into Band.",
    )

    simulate_parser = subparsers.add_parser(
        "simulate",
        help="Run a timed queue simulation with arrivals and top-case departures.",
    )
    simulate_parser.add_argument(
        "--arrival-row-numbers",
        required=True,
        help="Comma-separated CSV row numbers to inject over time.",
    )
    simulate_parser.add_argument(
        "--arrival-gap-seconds",
        type=float,
        default=15.0,
        help="Seconds between incoming orders.",
    )
    simulate_parser.add_argument(
        "--top-leave-after-seconds",
        type=float,
        default=45.0,
        help="Seconds before the current top order leaves the queue.",
    )
    simulate_parser.add_argument(
        "--depart-result",
        default="simulated queue departure",
        help="Final result text stored when the top order leaves.",
    )

    dequeue_parser = subparsers.add_parser(
        "dequeue-top",
        help="Mark the top-ranked pending case as completed so the next case rises.",
    )
    dequeue_parser.add_argument(
        "--result",
        default="mock queue departure",
        help="Final result text stored for the departing case.",
    )

    subparsers.add_parser(
        "snapshot",
        help="Print the current ranked pending queue.",
    )

    subparsers.add_parser(
        "dispatch-next",
        help="Hand the current top pending case into Band without changing the queue.",
    )

    args = parser.parse_args()
    if args.command == "prepare":
        prepare_mock_queue(
            base_time=args.base_time,
            spacing_minutes=args.spacing_minutes,
        )
    elif args.command == "enqueue":
        enqueue_case(
            case_id=args.case_id,
            row_number=args.row_number,
            arrived_minutes_ago=args.arrived_minutes_ago,
            dispatch_next=args.dispatch_next,
        )
    elif args.command == "dequeue-top":
        dequeue_top_case(result=args.result)
    elif args.command == "snapshot":
        print_snapshot()
    elif args.command == "dispatch-next":
        asyncio.run(dispatch_next_pending_case())
    elif args.command == "simulate":
        simulate_queue(
            arrival_row_numbers=_parse_row_numbers(args.arrival_row_numbers),
            arrival_gap_seconds=args.arrival_gap_seconds,
            top_leave_after_seconds=args.top_leave_after_seconds,
            depart_result=args.depart_result,
        )


def prepare_mock_queue(
    *,
    base_time: str | None,
    spacing_minutes: int,
) -> None:
    init_db()
    with get_connection() as connection:
        connection.execute(
            """
            DELETE FROM cases
            WHERE patient_code IS NULL OR TRIM(patient_code) = ''
            """
        )
        connection.execute("DELETE FROM queue_events")
        connection.execute(
            """
            UPDATE queue_state
            SET current_tick = 0,
                arrival_seq = 0,
                queue_version = 0
            WHERE id = 1
            """
        )
        connection.execute(
            """
            UPDATE cases
            SET status = 'completed',
                final_result = NULL,
                queue_rank = NULL,
                previous_rank = NULL,
                rank_change = NULL,
                queue_version = NULL,
                priority_score = NULL,
                arrival_seq = NULL,
                enqueue_tick = NULL,
                start_tick = NULL,
                completion_tick = NULL
            """
        )
        connection.commit()
    logger.info(
        "MOCK_PREPARED pending_count=%s simulation_clock=ticks",
        0,
    )
    print_snapshot()


def enqueue_case(
    *,
    case_id: str | None,
    row_number: int | None,
    arrived_minutes_ago: int,
    dispatch_next: bool,
) -> str:
    if bool(case_id) == bool(row_number):
        raise SystemExit("Provide exactly one of --case-id or --row-number")

    row = _load_row(case_id=case_id, row_number=row_number)
    patient_code = (row.get("PatientCode") or "").strip() or None
    if not patient_code:
        raise SystemExit("Selected CSV row has no patient id and cannot enter the mock queue")

    insert_case(
        case_id=(row.get("triage_code") or "").strip(),
        patient_code=patient_code,
        status="pending",
        payload=row,
        final_result=None,
    )
    logger.info(
        "MOCK_ENQUEUED case_id=%s patient_code=%s arrived_minutes_ago=%s",
        row.get("triage_code"),
        patient_code,
        arrived_minutes_ago,
    )
    print_snapshot()
    if dispatch_next:
        asyncio.run(dispatch_case((row.get("triage_code") or "").strip()))
    return (row.get("triage_code") or "").strip()


def dequeue_top_case(*, result: str) -> None:
    pending_case = get_next_pending_case()
    if pending_case is None:
        logger.info("No pending cases are available to dequeue.")
        return

    complete_top_case(final_result=result)
    logger.info(
        "MOCK_DEQUEUED case_id=%s patient_code=%s",
        pending_case.case_id,
        pending_case.patient_code,
    )
    print_snapshot()


def simulate_queue(
    *,
    arrival_row_numbers: list[int],
    arrival_gap_seconds: float,
    top_leave_after_seconds: float,
    depart_result: str,
) -> None:
    if not arrival_row_numbers:
        raise SystemExit("Provide at least one arrival row number")

    prepare_mock_queue(base_time=None, spacing_minutes=0)
    last_departure = time.monotonic()
    for index, row_number in enumerate(arrival_row_numbers):
        if index > 0:
            time.sleep(arrival_gap_seconds)
        queued_case_id = enqueue_case(
            case_id=None,
            row_number=row_number,
            arrived_minutes_ago=0,
            dispatch_next=False,
        )
        asyncio.run(dispatch_case(queued_case_id))

        now = time.monotonic()
        if now - last_departure >= top_leave_after_seconds:
            dequeue_top_case(result=depart_result)
            asyncio.run(dispatch_next_pending_case())
            last_departure = time.monotonic()

    time.sleep(top_leave_after_seconds)
    dequeue_top_case(result=depart_result)
    asyncio.run(dispatch_next_pending_case())


def print_snapshot() -> None:
    snapshot = get_queue_snapshot()
    logger.info("QUEUE_SNAPSHOT\n%s", json.dumps(snapshot, indent=2))


def _load_row(*, case_id: str | None, row_number: int | None) -> dict[str, str]:
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            if case_id and (row.get("triage_code") or "").strip() == case_id:
                return row
            if row_number and index == row_number:
                return row
    target = case_id if case_id else str(row_number)
    raise SystemExit(f"CSV row not found for selector: {target}")


def _parse_row_numbers(raw_value: str) -> list[int]:
    row_numbers: list[int] = []
    for part in raw_value.split(","):
        cleaned = part.strip()
        if not cleaned:
            continue
        row_numbers.append(int(cleaned))
    return row_numbers


if __name__ == "__main__":
    main()
