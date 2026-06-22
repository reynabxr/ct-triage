from __future__ import annotations

import argparse
import csv
import json
import logging
import tempfile
from pathlib import Path

from _bootstrap import add_src_to_path

add_src_to_path()

from agents.moderator_graph import moderate_case
from agents.pairwise_comparator import PairwiseCase, PairwiseComparator
from agents.review_agent import review_case
from agents.router_logic import normalize_case_payload, to_case_message
from storage.db import REPO_ROOT, init_db
from storage.queue_engine import apply_placement_decision, complete_top_case, get_queue_snapshot
from storage.queue_store import get_case, insert_case, mark_reviewed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CSV_PATH = REPO_ROOT / "data" / "input.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Test moderator binary-search queue insertion.")
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
        "--offline-stub",
        action="store_true",
        help="Use a deterministic pairwise stub instead of the configured model provider.",
    )
    parser.add_argument(
        "--complete-top",
        action="store_true",
        help="After applying the moderator decision, complete the current top case.",
    )
    args = parser.parse_args()

    comparator = PairwiseComparator(
        decision_provider=_offline_stub_decision if args.offline_stub else None
    )

    with tempfile.TemporaryDirectory(prefix="moderator-harness-") as temp_dir:
        db_path = Path(temp_dir) / "cases.db"
        init_db(db_path)
        queue_rows = _parse_row_numbers(args.queue_row_numbers)
        for row_number in queue_rows:
            row = _read_csv_row(row_number)
            insert_case(
                case_id=(row.get("triage_code") or "").strip(),
                patient_code=(row.get("PatientCode") or "").strip() or None,
                status="pending",
                payload=row,
                db_path=db_path,
            )

        new_row = _read_csv_row(args.new_row_number)
        case_id = (new_row.get("triage_code") or "").strip()
        patient_code = (new_row.get("PatientCode") or "").strip() or None
        insert_case(
            case_id=case_id,
            patient_code=patient_code,
            status="pending",
            payload=new_row,
            db_path=db_path,
        )
        mark_reviewed(case_id, db_path=db_path)

        record = get_case(case_id, db_path=db_path)
        if record is None:
            raise ValueError(f"Unable to load new case {case_id}")
        case = to_case_message(normalize_case_payload(record.payload, record=record))
        clinical = review_case(case)

        before_snapshot = get_queue_snapshot(db_path=db_path)
        decision = moderate_case(
            case,
            clinical,
            db_path=db_path,
            comparator=comparator,
        )
        applied = None
        if not decision.needs_human_review:
            applied = apply_placement_decision(
                case_id=case.case_id,
                decision=decision.model_dump(),
                case_payload=case.model_dump(),
                db_path=db_path,
            )
        completed = None
        if args.complete_top:
            completed = complete_top_case(db_path=db_path)
        after_snapshot = get_queue_snapshot(db_path=db_path)

        print(
            json.dumps(
                {
                    "before_queue": before_snapshot,
                    "moderator_decision": decision.model_dump(),
                    "queue_apply_result": applied,
                    "queue_completion_result": completed,
                    "after_queue": after_snapshot,
                },
                indent=2,
            )
        )


def _parse_row_numbers(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def _read_csv_row(row_number: int) -> dict[str, str]:
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            if index == row_number:
                return row
    raise ValueError(f"CSV row {row_number} not found")


def _offline_stub_decision(case_a: PairwiseCase, case_b: PairwiseCase) -> dict[str, object]:
    score_a = _offline_case_score(case_a)
    score_b = _offline_case_score(case_b)
    chosen = "A" if score_a >= score_b else "B"
    return {
        "chosen_patient": chosen,
        "reasoning": "The chosen patient has more concerning instability or higher immediate acuity signals.",
        "confidence": 0.75,
    }


def _offline_case_score(case: PairwiseCase) -> int:
    score = int(case.urgency_score or 0)
    if case.spo2 is not None and case.spo2 < 92:
        score += 4
    if case.bp_systolic is not None and case.bp_systolic < 90:
        score += 3
    if case.respiratory_rate is not None and (
        case.respiratory_rate <= 8 or case.respiratory_rate >= 30
    ):
        score += 3
    if case.pulse_rate is not None and (case.pulse_rate < 40 or case.pulse_rate >= 130):
        score += 2
    if (case.avpu or "").strip().upper() in {"V", "P", "U"}:
        score += 4
    if case.age is not None and case.age >= 75:
        score += 1
    return score


if __name__ == "__main__":
    main()
