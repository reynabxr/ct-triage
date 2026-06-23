from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .delay_harm_schema import DelayHarmAssessmentMessage
from .review_schema import ClinicalUrgency
from .review_schema import ClinicalUrgencyMessage
from .router_schema import CaseMessage

PlacementAction = Literal[
    "go_to_top",
    "insert_before",
    "insert_after",
    "go_to_bottom",
    "hold_and_escalate",
]
NextRoute = Literal["queue_engine_apply", "ct_escalation_agent"]


class QueueContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    patient_code: str | None = None
    queue_position: int
    waiting_ticks: int | None = None


class ComparisonStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    midpoint_index: int
    lower_index: int
    upper_index: int
    existing_case_id: str
    existing_queue_position: int
    chosen_patient: Literal["A", "B"]
    reasoning: str


class ModeratorPlacementDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_type: Literal["moderator_placement_decision"] = "moderator_placement_decision"
    placement_action: PlacementAction
    anchor_case_id: str | None = None
    needs_human_review: bool
    reason_summary: str


class ModeratorDecisionMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_type: Literal["moderator_decision"] = "moderator_decision"
    case_id: str
    patient_code: str
    clinical_urgency: ClinicalUrgency
    confidence: float = Field(ge=0.0, le=1.0)
    placement_action: PlacementAction
    anchor_case_id: str | None = None
    comparison_count: int = Field(ge=0)
    needs_human_review: bool
    reason_summary: str
    recommended_next_route: NextRoute
    comparison_history: list[ComparisonStep] = Field(default_factory=list)
    queue_snapshot: list[QueueContextItem] = Field(default_factory=list)


class ModeratorInputMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_type: Literal["moderator_input"] = "moderator_input"
    case: CaseMessage
    clinical_urgency: ClinicalUrgencyMessage
    queue_snapshot: list[QueueContextItem] | None = None
    delay_harm: DelayHarmAssessmentMessage | None = None
