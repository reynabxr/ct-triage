from __future__ import annotations

import argparse
import csv
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from _bootstrap import add_src_to_path

add_src_to_path()

from agents.pairwise_comparator import (
    PairwiseCase,
    PairwiseComparator,
    PairwiseDecision,
    find_insertion_index,
    is_directionally_consistent,
    pairwise_llm_available,
)
from agents.router_logic import normalize_case_payload, to_case_message
from storage.db import REPO_ROOT, get_connection, init_db
from storage.queue_engine import get_queue_snapshot
from storage.queue_store import get_case, insert_case

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CSV_PATH = REPO_ROOT / "data" / "input.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run standalone pairwise CT queue comparisons.")
    parser.add_argument(
        "--offline-stub",
        action="store_true",
        help="Use a deterministic local stub instead of the configured LLM provider.",
    )
    parser.add_argument(
        "--db-path",
        help="Optional SQLite path. Defaults to the configured DB for live queue mode.",
    )
    parser.add_argument(
        "--queue-row-numbers",
        default="2,3,4",
        help="CSV row numbers used to seed a fallback simulated queue when the live queue is empty.",
    )
    parser.add_argument(
        "--new-row-number",
        type=int,
        default=5,
        help="CSV row number used as the arriving case in fallback mode.",
    )
    args = parser.parse_args()

    comparator = PairwiseComparator(
        decision_provider=_offline_stub_decision if args.offline_stub else None
    )
    db_path = Path(args.db_path).expanduser().resolve() if args.db_path else None

    if not args.offline_stub and not pairwise_llm_available():
        raise SystemExit(
            "No AIML_API_KEY or OPENAI_API_KEY found. Re-run with --offline-stub or provide credentials."
        )

    harness = load_harness_cases(
        db_path=db_path,
        queue_row_numbers=_parse_row_numbers(args.queue_row_numbers),
        new_row_number=args.new_row_number,
    )

    results = run_harness(
        queue_cases=harness["queue_cases"],
        new_case=harness["new_case"],
        comparator=comparator,
        source=harness["source"],
    )
    print(json.dumps(results, indent=2))


def load_harness_cases(
    *,
    db_path: Path | None,
    queue_row_numbers: list[int],
    new_row_number: int,
) -> dict[str, Any]:
    live_queue_cases = _load_queue_cases_from_db(db_path=db_path)
    if live_queue_cases:
        used_case_ids = {case.case_id for case in live_queue_cases}
        new_case = _build_case_from_csv_row(_first_available_row_number(used_case_ids))
        return {
            "source": "live_queue",
            "queue_cases": live_queue_cases,
            "new_case": new_case,
        }

    with tempfile.TemporaryDirectory(prefix="pairwise-harness-") as temp_dir:
        temp_db_path = Path(temp_dir) / "cases.db"
        init_db(temp_db_path)
        for row_number in queue_row_numbers:
            row = _read_csv_row(row_number)
            insert_case(
                case_id=(row.get("triage_code") or "").strip(),
                patient_code=_patient_code(row),
                status="pending",
                payload=row,
                db_path=temp_db_path,
            )
        queue_cases = _load_queue_cases_from_db(db_path=temp_db_path)
        new_case = _build_case_from_csv_row(new_row_number)
        return {
            "source": "fallback_csv_simulation",
            "queue_cases": queue_cases,
            "new_case": new_case,
        }


def run_harness(
    *,
    queue_cases: list[PairwiseCase],
    new_case: PairwiseCase,
    comparator: PairwiseComparator,
    source: str,
) -> dict[str, Any]:
    if len(queue_cases) < 2:
        raise ValueError("Harness requires at least two queued cases")

    case_b = queue_cases[0]
    case_c = queue_cases[1]
    new_vs_b = comparator.compare(new_case, case_b)
    b_vs_new = comparator.compare(case_b, new_case)
    new_vs_c = comparator.compare(new_case, case_c)
    c_vs_new = comparator.compare(case_c, new_case)

    insertion = find_insertion_index(
        new_case=new_case,
        ordered_queue=queue_cases,
        comparator=comparator,
    )
    cycle_check = _three_case_cycle_check(
        comparator=comparator,
        case_a=new_case,
        case_b=case_b,
        case_c=case_c,
    )

    return {
        "source": source,
        "new_case_id": new_case.case_id,
        "queue_case_ids": [case.case_id for case in queue_cases],
        "comparisons": {
            "A_vs_B": _comparison_payload(new_case.case_id, case_b.case_id, new_vs_b),
            "B_vs_A": _comparison_payload(case_b.case_id, new_case.case_id, b_vs_new),
            "A_vs_C": _comparison_payload(new_case.case_id, case_c.case_id, new_vs_c),
            "C_vs_A": _comparison_payload(case_c.case_id, new_case.case_id, c_vs_new),
        },
        "consistency_checks": {
            "A_vs_B_directional_flip_ok": is_directionally_consistent(new_vs_b, b_vs_new),
            "A_vs_C_directional_flip_ok": is_directionally_consistent(new_vs_c, c_vs_new),
            "three_case_cycle_detected": cycle_check,
        },
        "binary_search_probe": {
            "suggested_insertion_index": insertion.insertion_index,
            "suggested_queue_position": insertion.insertion_index + 1,
            "compared_case_ids": insertion.compared_case_ids,
            "steps": [
                {
                    "midpoint": step.midpoint,
                    "existing_case_id": step.existing_case_id,
                    "existing_queue_position": step.existing_queue_position,
                    "chosen_patient": step.chosen_patient,
                    "reasoning": step.reasoning,
                }
                for step in insertion.steps
            ],
        },
    }


def _comparison_payload(left_case_id: str, right_case_id: str, decision: PairwiseDecision) -> dict[str, Any]:
    winning_case_id = left_case_id if decision.chosen_patient == "A" else right_case_id
    return {
        "chosen_patient": decision.chosen_patient,
        "winning_case_id": winning_case_id,
        "reasoning": decision.reasoning,
        "confidence": decision.confidence,
    }


def _three_case_cycle_check(
    *,
    comparator: PairwiseComparator,
    case_a: PairwiseCase,
    case_b: PairwiseCase,
    case_c: PairwiseCase,
) -> bool:
    a_vs_b = comparator.compare(case_a, case_b)
    b_vs_c = comparator.compare(case_b, case_c)
    c_vs_a = comparator.compare(case_c, case_a)

    a_before_b = a_vs_b.chosen_patient == "A"
    b_before_c = b_vs_c.chosen_patient == "A"
    c_before_a = c_vs_a.chosen_patient == "A"
    return a_before_b and b_before_c and c_before_a


def _load_queue_cases_from_db(*, db_path: Path | None) -> list[PairwiseCase]:
    init_db(db_path)
    queue_snapshot = get_queue_snapshot(db_path=db_path)
    queue_cases: list[PairwiseCase] = []
    for item in queue_snapshot:
        record = get_case(str(item["case_id"]), db_path=db_path)
        if record is None:
            continue
        normalized = normalize_case_payload(record.payload, record=record)
        case_message = to_case_message(normalized)
        queue_cases.append(
            PairwiseCase.model_validate(
                {
                    **case_message.model_dump(),
                    "waiting_ticks": item.get("waiting_ticks"),
                    "queue_position": item.get("queue_position"),
                }
            )
        )
    return queue_cases


def _build_case_from_csv_row(row_number: int) -> PairwiseCase:
    row = _read_csv_row(row_number)
    normalized = normalize_case_payload(row)
    case_message = to_case_message(normalized)
    return PairwiseCase.model_validate(
        {
            **case_message.model_dump(),
            "waiting_ticks": 0,
            "queue_position": None,
        }
    )


def _read_csv_row(row_number: int) -> dict[str, Any]:
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            if index == row_number:
                return row
    raise ValueError(f"CSV row {row_number} not found in {CSV_PATH}")


def _first_available_row_number(used_case_ids: set[str]) -> int:
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            case_id = (row.get("triage_code") or "").strip()
            patient_code = _patient_code(row)
            if case_id and patient_code and case_id not in used_case_ids:
                return index
    raise ValueError("No CSV row available for a new arriving case")


def _patient_code(row: dict[str, Any]) -> str | None:
    patient_code = (row.get("PatientCode") or "").strip()
    return patient_code or None


def _parse_row_numbers(value: str) -> list[int]:
    rows = [int(part.strip()) for part in value.split(",") if part.strip()]
    if len(rows) < 2:
        raise ValueError("Provide at least two queue row numbers")
    return rows


def _offline_stub_decision(case_a: PairwiseCase, case_b: PairwiseCase) -> dict[str, Any]:
    score_a = _offline_case_score(case_a)
    score_b = _offline_case_score(case_b)
    if score_a == score_b:
        waiting_a = int(case_a.waiting_ticks or 0)
        waiting_b = int(case_b.waiting_ticks or 0)
        chosen = "A" if waiting_a >= waiting_b else "B"
    else:
        chosen = "A" if score_a > score_b else "B"
    logger.info(
        "PAIRWISE_OFFLINE_STUB case_a_id=%s case_b_id=%s score_a=%s score_b=%s chosen=%s",
        case_a.case_id,
        case_b.case_id,
        score_a,
        score_b,
        chosen,
    )
    return {
        "chosen_patient": chosen,
        "reasoning": "The chosen patient has more concerning instability or higher immediate acuity signals.",
        "confidence": 0.75,
    }


def _offline_case_score(case: PairwiseCase) -> int:
    score = int(case.urgency_score or 0)
    if case.critical_status == 1:
        score += 5
    if case.stupor_status not in (None, 0):
        score += 4
    if (case.avpu or "").strip().upper() in {"V", "P", "U"}:
        score += 4
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
    if case.age is not None and case.age >= 75:
        score += 1
    return score


if __name__ == "__main__":
    main()
