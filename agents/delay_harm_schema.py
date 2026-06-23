from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TimeSensitivity = Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
ScanWindow = Literal[
    "within 15 minutes",
    "within 1 hour",
    "within 4 hours",
    "within 24 hours",
]


class DelayHarmAssessmentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_type: Literal["delay_harm_assessment"] = "delay_harm_assessment"
    case_id: str
    patient_code: str
    delay_harm_score: float = Field(ge=0.0, le=1.0)
    time_sensitivity: TimeSensitivity
    recommended_scan_window: ScanWindow
    reasoning_summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_next_route: Literal["moderator"] = "moderator"
