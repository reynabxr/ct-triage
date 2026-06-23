from __future__ import annotations

from .delay_harm_graph import assess_delay_harm
from .delay_harm_schema import DelayHarmAssessmentMessage
from .router_schema import CaseMessage


def run_delay_harm_assessment(case: CaseMessage) -> DelayHarmAssessmentMessage:
    return assess_delay_harm(case)
