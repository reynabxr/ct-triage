from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .chief_complaint_chart import chief_complaint_description_for_code
from .router_schema import CaseMessage, NormalizedCase, QueueTrigger, RouterDecision
from .shared_schema import parse_json_object
from storage.queue_store import CaseRecord


PAYLOAD_FIELD_MAP = {
    "case_id": ("case_id", "triage_code"),
    "patient_code": ("patient_code", "PatientCode"),
    "triage_code": ("triage_code",),
    "age": ("age", "age_x"),
    "gender": ("gender", "gender_x"),
    "chief_complaint_code": ("chief_complaint_code", "ChiefComplaint"),
    "chief_complaint_description": (
        "chief_complaint_description",
        "ChiefComplaintDescription",
        "chief_complaint",
        "complaint_description",
    ),
    "pain_grade": ("pain_grade", "PainGrade"),
    "bp_systolic": ("bp_systolic", "BlooddpressurSystol"),
    "bp_diastolic": ("bp_diastolic", "BlooddpressurDiastol"),
    "pulse_rate": ("pulse_rate", "PulseRate"),
    "respiratory_rate": ("respiratory_rate", "RespiratoryRate"),
    "spo2": ("spo2", "O2Saturation"),
    "avpu": ("avpu", "AVPU"),
}

REQUIRED_ROUTE_FIELDS = ("case_id", "patient_code", "triage_code")
NUMERIC_FIELDS = {
    "age",
    "pain_grade",
    "bp_systolic",
    "bp_diastolic",
    "pulse_rate",
    "respiratory_rate",
    "spo2",
}
MENTION_PATTERN = re.compile(r"(?<!\S)@[A-Za-z0-9._/\-]+")


@dataclass(frozen=True)
class RouterInput:
    trigger: QueueTrigger | None
    payload: dict[str, Any] | None


def parse_router_input(content: str) -> RouterInput:
    cleaned = strip_band_mentions(content)
    try:
        payload = parse_json_object(cleaned)
    except ValueError:
        return RouterInput(trigger=None, payload=None)

    message_type = str(payload.get("message_type") or "").strip().lower()
    if message_type == "queue_trigger":
        trigger = QueueTrigger.model_validate(payload)
        direct_payload = _coerce_payload(trigger.payload) or _coerce_payload(
            trigger.case_payload
        )
        return RouterInput(trigger=trigger, payload=direct_payload)
    if message_type == "case":
        return RouterInput(trigger=None, payload=payload)
    return RouterInput(trigger=None, payload=None)


def strip_band_mentions(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = MENTION_PATTERN.sub("", line).strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines).strip()


def normalize_case_payload(
    payload: dict[str, Any],
    *,
    record: CaseRecord | None = None,
    now: datetime | None = None,
) -> NormalizedCase:
    normalized: dict[str, Any] = {}
    for target_field, source_fields in PAYLOAD_FIELD_MAP.items():
        value = _first_present(payload, source_fields)
        if target_field in NUMERIC_FIELDS:
            normalized[target_field] = _as_int_or_none(value)
        else:
            normalized[target_field] = _as_clean_string(value)

    normalized["case_id"] = normalized["case_id"] or normalized["triage_code"]
    normalized["triage_code"] = normalized["triage_code"] or normalized["case_id"]
    if not normalized.get("chief_complaint_description"):
        normalized["chief_complaint_description"] = chief_complaint_description_for_code(
            normalized.get("chief_complaint_code")
        )
    normalized["force_escalation"] = _as_bool(
        payload.get("force_escalation", False)
    )

    missing_fields = [
        field
        for field in PAYLOAD_FIELD_MAP
        if normalized.get(field) in (None, "")
    ]
    validation_status = (
        "valid"
        if all(normalized.get(field) not in (None, "") for field in REQUIRED_ROUTE_FIELDS)
        else "invalid"
    )
    normalized["urgency_score"] = compute_urgency_score(normalized)
    normalized["waiting_time_minutes"] = compute_waiting_time_minutes(
        payload,
        record=record,
        now=now,
    )
    normalized["missing_fields"] = missing_fields
    normalized["validation_status"] = validation_status
    return NormalizedCase.model_validate(normalized)


def build_router_decision(case: NormalizedCase) -> RouterDecision:
    if case.validation_status == "valid":
        return RouterDecision(
            case_id=case.case_id,
            should_route=True,
            validation_status=case.validation_status,
            missing_fields=case.missing_fields,
            reason="normalized case payload is valid for review routing",
        )
    return RouterDecision(
        case_id=case.case_id,
        should_route=False,
        validation_status=case.validation_status,
        missing_fields=case.missing_fields,
        reason="required routing fields are missing",
    )


def to_case_message(case: NormalizedCase) -> CaseMessage:
    if case.case_id is None or case.patient_code is None or case.triage_code is None:
        raise ValueError("Cannot create CaseMessage from invalid normalized case")
    return CaseMessage.model_validate(
        {
            "message_type": "case",
            **case.model_dump(),
        }
    )


def compute_urgency_score(case: dict[str, Any]) -> int:
    score = 0
    avpu = (case.get("avpu") or "").upper()
    pain_grade = case.get("pain_grade")
    bp_systolic = case.get("bp_systolic")
    pulse_rate = case.get("pulse_rate")
    respiratory_rate = case.get("respiratory_rate")
    spo2 = case.get("spo2")


    if avpu and avpu != "A":
        score += 2
    if pain_grade is not None:
        if pain_grade >= 7:
            score += 2
        elif pain_grade >= 4:
            score += 1
    if bp_systolic is not None and bp_systolic < 90:
        score += 2
    if pulse_rate is not None and (pulse_rate < 40 or pulse_rate >= 130):
        score += 2
    if respiratory_rate is not None and (
        respiratory_rate <= 8 or respiratory_rate >= 30
    ):
        score += 2
    if spo2 is not None:
        if spo2 < 92:
            score += 3
        elif spo2 < 95:
            score += 1

    return min(score, 15)


def compute_waiting_time_minutes(
    payload: dict[str, Any],
    *,
    record: CaseRecord | None = None,
    now: datetime | None = None,
) -> int | None:
    reference_now = now or datetime.now(timezone.utc)
    candidates = [
        payload.get("dispatched_at"),
        payload.get("queued_at"),
        payload.get("created_at"),
        record.created_at if record else None,
    ]
    for candidate in candidates:
        parsed = _parse_datetime(candidate)
        if parsed is None:
            continue
        delta_seconds = (reference_now - parsed).total_seconds()
        return max(0, int(delta_seconds // 60))
    return None


def parse_payload_text(text: str) -> dict[str, Any] | None:
    cleaned = strip_band_mentions(text)
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return parse_payload_text(value)
    return None


def _first_present(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _as_clean_string(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = strip_band_mentions(str(value)).strip()
    return cleaned or None


def _as_int_or_none(value: Any) -> int | None:
    cleaned = _as_clean_string(value)
    if not cleaned:
        return None
    return int(float(cleaned))


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
