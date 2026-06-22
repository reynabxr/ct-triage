from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CaseMessage(BaseModel):
    message_type: str = Field(default="case")
    case_id: str
    patient_code: str
    triage_code: str
    age: int | None = None
    gender: str | None = None
    chief_complaint_code: str | None = None
    chief_complaint_description: str | None = None
    pain_grade: int | None = None
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    pulse_rate: int | None = None
    respiratory_rate: int | None = None
    spo2: int | None = None
    avpu: str | None = None
    urgency_score: int
    waiting_time_minutes: int | None = None
    missing_fields: list[str] = Field(default_factory=list)
    validation_status: Literal["valid", "invalid"]
    queue_rank: int | None = None
    priority_score: float | None = None
    force_escalation: bool = False


class NormalizedCase(BaseModel):
    case_id: str | None = None
    patient_code: str | None = None
    triage_code: str | None = None
    age: int | None = None
    gender: str | None = None
    chief_complaint_code: str | None = None
    chief_complaint_description: str | None = None
    pain_grade: int | None = None
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    pulse_rate: int | None = None
    respiratory_rate: int | None = None
    spo2: int | None = None
    avpu: str | None = None
    urgency_score: int
    waiting_time_minutes: int | None = None
    missing_fields: list[str] = Field(default_factory=list)
    validation_status: Literal["valid", "invalid"]
    queue_rank: int | None = None
    priority_score: float | None = None
    force_escalation: bool = False


class RouterDecision(BaseModel):
    case_id: str | None = None
    should_route: bool
    validation_status: Literal["valid", "invalid"]
    missing_fields: list[str] = Field(default_factory=list)
    reason: str


class QueueTrigger(BaseModel):
    message_type: str = Field(default="queue_trigger")
    case_id: str | None = None
    payload: dict[str, object] | None = None
    case_payload: dict[str, object] | None = None
