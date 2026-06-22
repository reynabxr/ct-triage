from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from langgraph.graph import END, StateGraph
from pydantic import SecretStr

from .moderator_logic import (
    needs_human_review,
    needs_precomparison_escalation,
    pairwise_case_from_record,
    placement_from_insertion_index,
    queue_context_item,
    reason_summary,
)
from .moderator_prompts import (
    MODERATOR_PLACEMENT_SYSTEM_PROMPT,
    moderator_placement_user_prompt,
)
from .moderator_schema import (
    ComparisonStep,
    ModeratorDecisionMessage,
    ModeratorPlacementDecision,
    PlacementAction,
    QueueContextItem,
)
from .pairwise_comparator import PairwiseCase, PairwiseComparator
from .review_schema import ClinicalUrgencyMessage
from .router_schema import CaseMessage
from .shared_schema import parse_json_object
from storage.queue_engine import get_queue_snapshot
from storage.queue_store import get_case

logger = logging.getLogger(__name__)


class ModeratorState(TypedDict, total=False):
    case: CaseMessage
    clinical: ClinicalUrgencyMessage
    comparator: PairwiseComparator
    db_path: Path | None
    queue_snapshot_override: list[QueueContextItem] | None
    new_case: PairwiseCase
    queue_snapshot: list[QueueContextItem]
    queue_cases: list[PairwiseCase]
    lower_index: int
    upper_index: int
    midpoint_index: int
    insertion_index: int
    anchor_case_id: str | None
    placement_action: PlacementAction
    comparison_history: list[ComparisonStep]
    pairwise_failure: str | None
    needs_human_review: bool
    reason_summary: str
    moderator_llm_summary: str
    result: ModeratorDecisionMessage


def moderate_case(
    case: CaseMessage,
    clinical: ClinicalUrgencyMessage,
    *,
    db_path: Path | None = None,
    queue_snapshot: list[QueueContextItem] | None = None,
    comparator: PairwiseComparator | None = None,
) -> ModeratorDecisionMessage:
    logger.info(
        "MODERATOR_RECEIVED case_id=%s patient_code=%s clinical_urgency=%s",
        case.case_id,
        case.patient_code,
        clinical.clinical_urgency,
    )
    graph = build_moderator_graph()
    state = cast(
        ModeratorState,
        graph.invoke(
            {
                "case": case,
                "clinical": clinical,
                "db_path": db_path,
                "queue_snapshot_override": queue_snapshot,
                "comparator": comparator or PairwiseComparator(),
            }
        ),
    )
    result = state.get("result")
    if result is None:
        raise KeyError("ModeratorState is missing required key: result")
    return cast(ModeratorDecisionMessage, result)


def build_moderator_graph():
    graph = StateGraph(ModeratorState)
    graph.add_node("ingest_case", ingest_case)
    graph.add_node("check_escalation", check_escalation)
    graph.add_node("load_queue", load_queue)
    graph.add_node("initialize_search", initialize_search)
    graph.add_node("binary_search_compare", binary_search_compare)
    graph.add_node("decide_placement", decide_placement)
    graph.add_node("emit_result", emit_result)

    graph.set_entry_point("ingest_case")
    graph.add_edge("ingest_case", "check_escalation")
    graph.add_conditional_edges(
        "check_escalation",
        _precomparison_escalation_route,
        {
            "emit_result": "emit_result",
            "load_queue": "load_queue",
        },
    )
    graph.add_edge("load_queue", "initialize_search")
    graph.add_conditional_edges(
        "initialize_search",
        _search_route,
        {
            "decide_placement": "decide_placement",
            "binary_search_compare": "binary_search_compare",
        },
    )
    graph.add_conditional_edges(
        "binary_search_compare",
        _search_route,
        {
            "decide_placement": "decide_placement",
            "binary_search_compare": "binary_search_compare",
        },
    )
    graph.add_edge("decide_placement", "emit_result")
    graph.add_edge("emit_result", END)
    return graph.compile()


def ingest_case(state: ModeratorState) -> ModeratorState:
    case = cast(CaseMessage, _state_value(state, "case"))
    clinical = cast(ClinicalUrgencyMessage, _state_value(state, "clinical"))
    if clinical.case_id != case.case_id or clinical.patient_code != case.patient_code:
        raise ValueError("Clinical urgency identifiers do not match case identifiers")
    state["new_case"] = PairwiseCase.model_validate(case.model_dump())
    state["comparison_history"] = []
    state["pairwise_failure"] = None
    return state


def check_escalation(state: ModeratorState) -> ModeratorState:
    new_case = cast(PairwiseCase, _state_value(state, "new_case"))
    if needs_precomparison_escalation(new_case):
        state["needs_human_review"] = True
        state["placement_action"] = "hold_and_escalate"
        state["anchor_case_id"] = None
        state["insertion_index"] = 0
        state["queue_snapshot"] = []
        state["queue_cases"] = []
        state["comparison_history"] = []
        reason = "force_escalation=True" if new_case.force_escalation else f"validation_status={new_case.validation_status}"
        if new_case.force_escalation:
            state["reason_summary"] = (
                "This case was sent for human review before pairwise comparison because it was explicitly flagged for escalation."
            )
        else:
            state["reason_summary"] = (
                "This case was sent for human review before pairwise comparison because its input validation was incomplete."
            )
        logger.info(
            "MODERATOR_PRECOMPARISON_ESCALATION case_id=%s reason=%s",
            new_case.case_id,
            reason,
        )
    return state


def _precomparison_escalation_route(state: ModeratorState) -> str:
    if bool(state.get("needs_human_review")) and state.get("placement_action") == "hold_and_escalate" and not state.get("queue_cases"):
        return "emit_result"
    return "load_queue"


def load_queue(state: ModeratorState) -> ModeratorState:
    case = cast(CaseMessage, _state_value(state, "case"))
    snapshot_override = state.get("queue_snapshot_override")
    if snapshot_override is not None:
        snapshot_items = snapshot_override
    else:
        snapshot_items = [
            queue_context_item(item)
            for item in get_queue_snapshot(db_path=state.get("db_path"))
            if str(item["case_id"]) != case.case_id
        ]

    queue_cases: list[PairwiseCase] = []
    for item in snapshot_items:
        record = get_case(item.case_id, db_path=state.get("db_path"))
        if record is None:
            raise ValueError(f"Queue snapshot case_id={item.case_id} missing from storage")
        queue_cases.append(
            pairwise_case_from_record(
                record,
                queue_position=item.queue_position,
                waiting_ticks=item.waiting_ticks,
            )
        )

    state["queue_snapshot"] = snapshot_items
    state["queue_cases"] = queue_cases
    logger.info(
        "MODERATOR_QUEUE_LOADED case_id=%s pending_count=%s",
        case.case_id,
        len(queue_cases),
    )
    return state


def initialize_search(state: ModeratorState) -> ModeratorState:
    queue_cases = cast(list[PairwiseCase], state.get("queue_cases", []))
    state["lower_index"] = 0
    state["upper_index"] = len(queue_cases)
    if not queue_cases:
        state["insertion_index"] = 0
    return state


def binary_search_compare(state: ModeratorState) -> ModeratorState:
    queue_cases = cast(list[PairwiseCase], _state_value(state, "queue_cases"))
    new_case = cast(PairwiseCase, _state_value(state, "new_case"))
    comparator = cast(PairwiseComparator, _state_value(state, "comparator"))
    lower_index = int(_state_value(state, "lower_index"))
    upper_index = int(_state_value(state, "upper_index"))
    midpoint_index = (lower_index + upper_index) // 2
    existing_case = queue_cases[midpoint_index]

    try:
        decision = comparator.compare(new_case, existing_case)
    except Exception as exc:
        logger.exception(
            "MODERATOR_PAIRWISE_FAILED case_id=%s midpoint_case_id=%s",
            new_case.case_id,
            existing_case.case_id,
        )
        state["pairwise_failure"] = str(exc)
        state["needs_human_review"] = True
        state["placement_action"] = "hold_and_escalate"
        state["anchor_case_id"] = None
        state["insertion_index"] = lower_index
        return state

    history = state.get("comparison_history", [])
    history.append(
        ComparisonStep(
            midpoint_index=midpoint_index,
            lower_index=lower_index,
            upper_index=upper_index,
            existing_case_id=existing_case.case_id,
            existing_queue_position=int(existing_case.queue_position or midpoint_index + 1),
            chosen_patient=cast(Literal["A", "B"], decision.chosen_patient),
            reasoning=decision.reasoning,
        )
    )
    state["comparison_history"] = history
    logger.info(
        "MODERATOR_BINARY_STEP case_id=%s lower_index=%s upper_index=%s midpoint_index=%s existing_case_id=%s chosen_patient=%s",
        new_case.case_id,
        lower_index,
        upper_index,
        midpoint_index,
        existing_case.case_id,
        decision.chosen_patient,
    )
    if decision.chosen_patient == "A":
        state["upper_index"] = midpoint_index
    else:
        state["lower_index"] = midpoint_index + 1
    current_lower_index = int(_state_value(state, "lower_index"))
    current_upper_index = int(_state_value(state, "upper_index"))
    if current_lower_index >= current_upper_index:
        state["insertion_index"] = current_lower_index
    return state


def decide_placement(state: ModeratorState) -> ModeratorState:
    new_case = cast(PairwiseCase, _state_value(state, "new_case"))
    clinical = cast(ClinicalUrgencyMessage, _state_value(state, "clinical"))
    queue_cases = cast(list[PairwiseCase], state.get("queue_cases", []))
    insertion_index = int(state.get("insertion_index", 0))
    fallback_needs_review = bool(state.get("pairwise_failure")) or needs_human_review(new_case, clinical)

    if fallback_needs_review:
        placement_action: PlacementAction = "hold_and_escalate"
        anchor_case_id = None
    else:
        placement_action, anchor_case_id = placement_from_insertion_index(
            insertion_index=insertion_index,
            queue_cases=queue_cases,
        )

    llm_decision = _maybe_refine_moderator_placement(state)
    if llm_decision is not None:
        placement_action = llm_decision.placement_action
        anchor_case_id = llm_decision.anchor_case_id
        if llm_decision.needs_human_review and placement_action != "hold_and_escalate":
            logger.warning(
                "MODERATOR_LLM_INCONSISTENT_ESCALATION case_id=%s placement_action=%s",
                new_case.case_id,
                placement_action,
            )
            placement_action = "hold_and_escalate"
            anchor_case_id = None
        state["needs_human_review"] = llm_decision.needs_human_review
        state["reason_summary"] = llm_decision.reason_summary
        state["moderator_llm_summary"] = llm_decision.reason_summary
    else:
        state["needs_human_review"] = fallback_needs_review
        state["reason_summary"] = reason_summary(
            clinical=clinical,
            placement_action=placement_action,
            anchor_case_id=anchor_case_id,
            comparison_count=len(state.get("comparison_history", [])),
            needs_review=bool(state["needs_human_review"]),
            pairwise_failure=state.get("pairwise_failure"),
        )
    logger.info(
        "MODERATOR_DECISION_READY case_id=%s placement_action=%s anchor_case_id=%s comparison_count=%s needs_human_review=%s",
        new_case.case_id,
        placement_action,
        anchor_case_id,
        len(state.get("comparison_history", [])),
        state["needs_human_review"],
    )
    state["placement_action"] = placement_action
    state["anchor_case_id"] = anchor_case_id
    return state


def emit_result(state: ModeratorState) -> ModeratorState:
    case = cast(CaseMessage, _state_value(state, "case"))
    clinical = cast(ClinicalUrgencyMessage, _state_value(state, "clinical"))
    recommended_next_route = (
        "ct_escalation_agent"
        if bool(_state_value(state, "needs_human_review"))
        else "queue_engine_apply"
    )
    state["result"] = ModeratorDecisionMessage(
        case_id=case.case_id,
        patient_code=case.patient_code,
        clinical_urgency=clinical.clinical_urgency,
        confidence=clinical.confidence,
        placement_action=cast(PlacementAction, _state_value(state, "placement_action")),
        anchor_case_id=state.get("anchor_case_id"),
        comparison_count=len(state.get("comparison_history", [])),
        needs_human_review=bool(_state_value(state, "needs_human_review")),
        reason_summary=cast(str, _state_value(state, "reason_summary")),
        recommended_next_route=recommended_next_route,
        comparison_history=state.get("comparison_history", []),
        queue_snapshot=state.get("queue_snapshot", []),
    )
    return state


def _search_route(state: ModeratorState) -> str:
    if "insertion_index" in state or bool(state.get("pairwise_failure")):
        return "decide_placement"
    return "binary_search_compare"


def _state_value(state: ModeratorState, key: str) -> Any:
    value = state.get(key)
    if value is None:
        raise KeyError(f"ModeratorState is missing required key: {key}")
    return value


def _maybe_refine_moderator_placement(state: ModeratorState) -> ModeratorPlacementDecision | None:
    case = cast(PairwiseCase, _state_value(state, "new_case"))
    if not _moderator_llm_enabled():
        logger.info("MODERATOR_LLM_SKIPPED case_id=%s", case.case_id)
        return None
    try:
        return _invoke_moderator_placement_llm(state)
    except Exception:
        logger.exception("MODERATOR_LLM_REFINEMENT_FAILED")
        return None


def _invoke_moderator_placement_llm(state: ModeratorState) -> ModeratorPlacementDecision:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    api_key_value = os.getenv("AIML_API_KEY") or os.getenv("OPENAI_API_KEY")
    llm_kwargs: dict[str, Any] = {
        "model": _moderator_model_name(),
        "base_url": os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1"),
        "temperature": 0,
    }
    if api_key_value:
        llm_kwargs["api_key"] = SecretStr(api_key_value)
    llm = ChatOpenAI(**llm_kwargs)

    case = cast(PairwiseCase, _state_value(state, "new_case"))
    clinical = cast(ClinicalUrgencyMessage, _state_value(state, "clinical"))
    queue_snapshot = state.get("queue_snapshot", [])
    queue_preview = [
        {
            "case_id": item.case_id,
            "queue_position": item.queue_position,
            "waiting_ticks": item.waiting_ticks,
        }
        for item in queue_snapshot[:6]
    ]
    comparison_history = state.get("comparison_history", [])
    case_json = json.dumps(case.model_dump(mode="json", exclude_none=True), sort_keys=True)
    clinical_json = json.dumps(clinical.model_dump(mode="json", exclude_none=True), sort_keys=True)
    queue_json = json.dumps(queue_preview, sort_keys=True)
    comparison_history_json = json.dumps(
        [step.model_dump(mode="json") for step in comparison_history],
        sort_keys=True,
    )

    response = llm.invoke(
        [
            SystemMessage(content=MODERATOR_PLACEMENT_SYSTEM_PROMPT),
            HumanMessage(
                content=moderator_placement_user_prompt(
                    case_json=case_json,
                    clinical_json=clinical_json,
                    queue_json=queue_json,
                    comparison_history_json=comparison_history_json,
                )
            ),
        ]
    )
    content = getattr(response, "content", response)
    if not isinstance(content, str):
        content = str(content)
    payload = parse_json_object(content)
    return ModeratorPlacementDecision.model_validate(payload)


def _moderator_llm_enabled() -> bool:
    value = os.getenv("CT_MODERATOR_USE_LLM", "").strip().lower()
    if value in {"0", "false", "no", "n"}:
        return False
    return bool(os.getenv("AIML_API_KEY") or os.getenv("OPENAI_API_KEY"))


def _moderator_model_name() -> str:
    return os.getenv(
        "CT_MODERATOR_MODEL",
        os.getenv("CT_PAIRWISE_MODEL", os.getenv("CT_REVIEW_MODEL", "deepseek-v4-flash")),
    )
