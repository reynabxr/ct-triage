from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from .moderator_schema import ModeratorDecisionMessage
from .shared_schema import HumanHandoffMessage


def create_human_handoff(
    decision: ModeratorDecisionMessage,
) -> HumanHandoffMessage:
    return HumanHandoffMessage(
        case_id=decision.case_id,
        patient_code=decision.patient_code,
        clinical_urgency=decision.clinical_urgency,
        confidence=decision.confidence,
        queue_action=decision.placement_action,
        queue_assessment="NEEDS_HUMAN_REVIEW",
        reason=decision.reason_summary,
        summary=decision.reason_summary,
        due_at=None,
    )


def _human_due_at() -> str | None:
    raw_timeout = os.getenv("CT_HUMAN_REVIEW_TIMEOUT_MINUTES")
    if raw_timeout is None or not raw_timeout.strip():
        timeout_minutes = 15
    else:
        try:
            timeout_minutes = max(1, int(raw_timeout))
        except ValueError:
            timeout_minutes = 15
    if timeout_minutes <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(minutes=timeout_minutes)).isoformat()
