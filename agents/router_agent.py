from __future__ import annotations

import csv
from io import StringIO
from typing import Any

from .router_logic import normalize_case_payload, to_case_message
from .shared_schema import CaseMessage


CSV_COLUMNS = [
    "triage_code",
    "PatientCode",
    "age_x",
    "gender_x",
    "ChiefComplaint",
    "PainGrade",
    "CriticalStatus",
    "StuporStatus",
    "BlooddpressurSystol",
    "BlooddpressurDiastol",
    "PulseRate",
    "RespiratoryRate",
    "O2Saturation",
    "AVPU",
    "TriageGrade",
]


def parse_case_csv_row(row_text: str) -> CaseMessage:
    values = next(csv.reader(StringIO(row_text.strip())))
    if len(values) != len(CSV_COLUMNS):
        raise ValueError(
            f"Expected {len(CSV_COLUMNS)} CSV fields, received {len(values)}"
        )

    row = dict(zip(CSV_COLUMNS, values, strict=True))
    return case_message_from_payload(row)


def case_message_from_payload(row: dict[str, Any]) -> CaseMessage:
    normalized = normalize_case_payload(row)
    return to_case_message(normalized)


def _empty_to_none(value: str) -> str | None:
    value = str(value).strip()
    return value or None


def _as_str(value: Any) -> str:
    return str(value).strip()


def _as_int(value: Any) -> int | None:
    value = str(value).strip()
    if not value:
        return None
    return int(float(value))


def _as_bool(value: Any) -> bool:
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "yes", "y"}
