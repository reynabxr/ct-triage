from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ClinicalUrgency = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class ClinicalUrgencyMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_type: Literal["clinical_urgency"] = "clinical_urgency"
    case_id: str
    patient_code: str
    clinical_urgency: ClinicalUrgency
    confidence: float = Field(ge=0.0, le=1.0)
    red_flags: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    reasoning_summary: str
    recommended_next_route: Literal["moderator"] = "moderator"
