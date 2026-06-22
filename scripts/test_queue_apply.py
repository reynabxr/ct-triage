from __future__ import annotations

import argparse
import csv
import json
import logging
import tempfile
from pathlib import Path

from _bootstrap import add_src_to_path

add_src_to_path()

from storage.db import REPO_ROOT, get_connection, init_db
from storage.queue_engine import apply_placement_decision, complete_top_case, get_queue_snapshot
from storage.queue_store import insert_case

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CSV_PATH = REPO_ROOT / "data" / "input.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise deterministic queue placement application.")
    parser.add_argument(
        "--queue-row-numbers",
        default="2,3,4",
        help="Comma-separated CSV rows used to seed the existing queue.",
    )
    parser.add_argument(
        "--new-row-number",
        type=int,
        default=5,
        help="CSV row used as the incoming case.",
    )
    parser.add_argument(
        "--placement-action",
        required=True,
        choices=("go_to_top", "insert_before", "insert_after", "go_to_bottom", "hold_and_escalate"),
        help="Moderator placement action to apply.",
    )
    parser.add_argument(
        "--anchor-row-number",
        type=int,
        help="CSV row number of the anchor case in the seeded queue for before/after inserts.",
    )
    parser.add_argument(
        "--complete-top",
        action="store_true",
        help="After applying the placement, complete the current top pending case.",
    )
    args = parser.parse_args()

    queue_row_numbers = _parse_row_numbers(args.queue_row_numbers)
    with tempfile.TemporaryDirectory(prefix="queue-apply-harness-") as temp_dir:
        db_path = Path(temp_dir) / "cases.db"
        init_db(db_path)
        for row_number in queue_row_numbers:
            row = _read_csv_row(row_number)
            insert_case(
                case_id=(row.get("triage_code") or "").strip(),
                patient_code=(row.get("PatientCode") or "").strip() or None,
                status="pending",
                payload=row,
                db_path=db_path,
            )

        new_row = _read_csv_row(args.new_row_number)
        new_case_id = (new_row.get("triage_code") or "").strip()
        decision = {
            "case_id": new_case_id,
            "placement_action": args.placement_action,
            "reason_summary": "queue apply harness",
        }
        if args.anchor_row_number is not None:
            anchor_row = _read_csv_row(args.anchor_row_number)
            decision["anchor_case_id"] = (anchor_row.get("triage_code") or "").strip()

        before_snapshot = get_queue_snapshot(db_path=db_path)
        apply_result = apply_placement_decision(
            decision=decision,
            case_payload=new_row,
            db_path=db_path,
        )
        completion_result = None
        if args.complete_top:
            completion_result = complete_top_case(
                final_result="queue apply harness completion",
                db_path=db_path,
            )
        after_snapshot = get_queue_snapshot(db_path=db_path)
        with get_connection(db_path) as connection:
            queue_events = connection.execute(
                """
                SELECT event_type, case_id, affected_case_ids, simulation_tick, details
                FROM queue_events
                ORDER BY event_id ASC
                """
            ).fetchall()

        print(
            json.dumps(
                {
                    "before_queue": before_snapshot,
                    "apply_result": apply_result,
                    "completion_result": completion_result,
                    "after_queue": after_snapshot,
                    "queue_events": [dict(row) for row in queue_events],
                },
                indent=2,
            )
        )


def _parse_row_numbers(raw_value: str) -> list[int]:
    return [int(part.strip()) for part in raw_value.split(",") if part.strip()]


def _read_csv_row(row_number: int) -> dict[str, str]:
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            if index == row_number:
                return row
    raise ValueError(f"CSV row {row_number} not found")


if __name__ == "__main__":
    main()
