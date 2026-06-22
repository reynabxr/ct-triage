from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

from _bootstrap import add_src_to_path

add_src_to_path()

from storage.db import REPO_ROOT
from storage.queue_store import get_case, insert_case

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CSV_PATH = REPO_ROOT / "data" / "input.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed one case into SQLite.")
    parser.add_argument(
        "--case-id",
        help="CSV triage_code to seed",
    )
    parser.add_argument(
        "--row-number",
        type=int,
        help="1-based data row number in input.csv, excluding the header",
    )
    parser.add_argument(
        "--force-escalation",
        action="store_true",
        help="Store force_escalation=true in the queued payload",
    )
    args = parser.parse_args()

    if bool(args.case_id) == bool(args.row_number):
        raise SystemExit("Provide exactly one of --case-id or --row-number")

    row = _load_row(case_id=args.case_id, row_number=args.row_number)
    if args.force_escalation:
        row["force_escalation"] = "true"
    case_id = (row.get("triage_code") or "").strip()
    patient_code = (row.get("PatientCode") or "").strip() or None
    insert_case(
        case_id=case_id,
        patient_code=patient_code,
        status="pending",
        payload=row,
        final_result=None,
    )

    stored_case = get_case(case_id)
    logger.info(
        "CASE_READBACK case_id=%s status=%s patient_code=%s",
        stored_case.case_id,
        stored_case.status,
        stored_case.patient_code,
    )


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


if __name__ == "__main__":
    main()
