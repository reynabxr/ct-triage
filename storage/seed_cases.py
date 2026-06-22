from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.db import REPO_ROOT, init_db
from storage.queue_store import insert_case

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CSV_PATH = REPO_ROOT / "data" / "input.csv"


def seed_cases(limit: int = 3, csv_path: Path = CSV_PATH) -> None:
    init_db()
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            if index >= limit:
                break
            case_id = (row.get("triage_code") or "").strip()
            patient_code = (row.get("PatientCode") or "").strip() or None
            if patient_code is None:
                logger.info("SKIPPED case_id=%s reason=missing_patient_code", case_id)
                continue
            insert_case(
                case_id=case_id,
                patient_code=patient_code,
                status="pending",
                payload=row,
            )
            logger.info("SEEDED case_id=%s status=pending", case_id)


if __name__ == "__main__":
    seed_cases()
