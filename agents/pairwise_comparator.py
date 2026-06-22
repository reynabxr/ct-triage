from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from .pairwise_prompts import (
    PAIRWISE_COMPARISON_SYSTEM_PROMPT,
    pairwise_comparison_user_prompt,
)
from .shared_schema import parse_json_object

logger = logging.getLogger(__name__)


class PairwiseCase(BaseModel):
    model_config = ConfigDict(extra="ignore")

    case_id: str
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
    urgency_score: int | None = None
    waiting_ticks: int | None = None
    waiting_time_minutes: int | None = None
    queue_position: int | None = None
    missing_fields: list[str] = Field(default_factory=list)
    validation_status: str | None = None
    force_escalation: bool = False


class PairwiseDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chosen_patient: str
    reasoning: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    def model_post_init(self, __context: Any) -> None:
        self.chosen_patient = self.chosen_patient.strip().upper()
        self.reasoning = self.reasoning.strip()
        if self.chosen_patient not in {"A", "B"}:
            raise ValueError("chosen_patient must be 'A' or 'B'")
        if not self.reasoning:
            raise ValueError("reasoning must be non-empty")


DecisionProvider = Callable[[PairwiseCase, PairwiseCase], PairwiseDecision | dict[str, Any] | str]


@dataclass(frozen=True)
class BinarySearchStep:
    midpoint: int
    existing_case_id: str
    existing_queue_position: int | None
    chosen_patient: str
    reasoning: str


@dataclass(frozen=True)
class BinarySearchPlacement:
    insertion_index: int
    compared_case_ids: list[str]
    steps: list[BinarySearchStep]


class PairwiseComparator:
    def __init__(
        self,
        *,
        decision_provider: DecisionProvider | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._decision_provider = decision_provider
        self._model = model or pairwise_model_name()
        self._base_url = base_url or os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1")

    def compare(
        self,
        case_a: PairwiseCase | Mapping[str, Any],
        case_b: PairwiseCase | Mapping[str, Any],
    ) -> PairwiseDecision:
        normalized_a = case_a if isinstance(case_a, PairwiseCase) else PairwiseCase.model_validate(case_a)
        normalized_b = case_b if isinstance(case_b, PairwiseCase) else PairwiseCase.model_validate(case_b)
        logger.info(
            "PAIRWISE_COMPARE case_a_id=%s case_b_id=%s queue_a=%s queue_b=%s",
            normalized_a.case_id,
            normalized_b.case_id,
            normalized_a.queue_position,
            normalized_b.queue_position,
        )

        if self._decision_provider is not None:
            raw_result = self._decision_provider(normalized_a, normalized_b)
        else:
            raw_result = self._invoke_model(normalized_a, normalized_b)

        decision = self._parse_decision(raw_result)
        logger.info(
            "PAIRWISE_DECISION case_a_id=%s case_b_id=%s chosen_patient=%s reasoning=%s",
            normalized_a.case_id,
            normalized_b.case_id,
            decision.chosen_patient,
            decision.reasoning,
        )
        return decision

    def _parse_decision(self, raw_result: PairwiseDecision | dict[str, Any] | str) -> PairwiseDecision:
        if isinstance(raw_result, PairwiseDecision):
            return raw_result
        try:
            if isinstance(raw_result, str):
                payload = parse_json_object(raw_result)
            else:
                payload = raw_result
        except (ValueError, json.JSONDecodeError, TypeError):
            logger.exception("PAIRWISE_OUTPUT_PARSE_FAILED raw_result=%r", raw_result)
            raise

        try:
            return PairwiseDecision.model_validate(payload)
        except ValidationError:
            logger.exception("PAIRWISE_OUTPUT_SCHEMA_INVALID payload=%r", payload)
            raise

    def _invoke_model(self, case_a: PairwiseCase, case_b: PairwiseCase) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        api_key_value = os.getenv("AIML_API_KEY") or os.getenv("OPENAI_API_KEY")
        llm_kwargs: dict[str, Any] = {
            "model": self._model,
            "base_url": self._base_url,
            "temperature": 0,
        }
        if api_key_value:
            llm_kwargs["api_key"] = SecretStr(api_key_value)
        llm = ChatOpenAI(**llm_kwargs)
        response = llm.invoke(
            [
                SystemMessage(content=PAIRWISE_COMPARISON_SYSTEM_PROMPT),
                HumanMessage(
                    content=pairwise_comparison_user_prompt(
                        case_a=_model_input_payload(case_a),
                        case_b=_model_input_payload(case_b),
                    )
                ),
            ]
        )
        content = _message_text(response)
        if not content:
            logger.error("PAIRWISE_OUTPUT_EMPTY")
            raise ValueError("Model returned empty output")
        return content


def pairwise_model_name() -> str:
    return os.getenv("CT_PAIRWISE_MODEL", os.getenv("CT_REVIEW_MODEL", "deepseek-v4-flash"))


def pairwise_llm_available() -> bool:
    return bool(os.getenv("AIML_API_KEY") or os.getenv("OPENAI_API_KEY"))


def prefers_case_a(decision: PairwiseDecision) -> bool:
    return decision.chosen_patient == "A"


def is_directionally_consistent(
    forward: PairwiseDecision,
    reverse: PairwiseDecision,
) -> bool:
    return (
        (forward.chosen_patient == "A" and reverse.chosen_patient == "B")
        or (forward.chosen_patient == "B" and reverse.chosen_patient == "A")
    )


def find_insertion_index(
    *,
    new_case: PairwiseCase | Mapping[str, Any],
    ordered_queue: Sequence[PairwiseCase | Mapping[str, Any]],
    comparator: PairwiseComparator,
) -> BinarySearchPlacement:
    normalized_new = new_case if isinstance(new_case, PairwiseCase) else PairwiseCase.model_validate(new_case)
    normalized_queue = [
        item if isinstance(item, PairwiseCase) else PairwiseCase.model_validate(item)
        for item in ordered_queue
    ]

    low = 0
    high = len(normalized_queue)
    steps: list[BinarySearchStep] = []
    while low < high:
        midpoint = (low + high) // 2
        existing = normalized_queue[midpoint]
        decision = comparator.compare(normalized_new, existing)
        steps.append(
            BinarySearchStep(
                midpoint=midpoint,
                existing_case_id=existing.case_id,
                existing_queue_position=existing.queue_position,
                chosen_patient=decision.chosen_patient,
                reasoning=decision.reasoning,
            )
        )
        if prefers_case_a(decision):
            high = midpoint
        else:
            low = midpoint + 1

    return BinarySearchPlacement(
        insertion_index=low,
        compared_case_ids=[step.existing_case_id for step in steps],
        steps=steps,
    )


def _message_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text", "")))
        return "\n".join(chunk for chunk in chunks if chunk).strip()
    return str(content).strip()


def _model_input_payload(case: PairwiseCase) -> dict[str, Any]:
    return case.model_dump(
        mode="json",
        exclude_none=True,
        exclude={
            "force_escalation",
        },
    )
