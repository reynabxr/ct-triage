from __future__ import annotations

from .review_graph import build_review_graph, review_clinical_urgency
from .review_schema import ClinicalUrgencyMessage
from .router_schema import CaseMessage


def review_case(case: CaseMessage) -> ClinicalUrgencyMessage:
    return review_clinical_urgency(case)
