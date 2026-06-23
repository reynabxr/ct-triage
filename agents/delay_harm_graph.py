from __future__ import annotations

import json
import logging
import os
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import SecretStr

from .delay_harm_prompts import DELAY_HARM_SYSTEM_PROMPT, delay_harm_user_prompt
from .delay_harm_schema import DelayHarmAssessmentMessage, ScanWindow, TimeSensitivity
from .shared_schema import parse_json_object
from .router_schema import CaseMessage

logger = logging.getLogger(__name__)

_SENSITIVITY_BASE_SCORE: dict[TimeSensitivity, float] = {
    "CRITICAL": 0.90,
    "HIGH": 0.70,
    "MODERATE": 0.45,
    "LOW": 0.20,
}

_SENSITIVITY_SCAN_WINDOW: dict[TimeSensitivity, ScanWindow] = {
    "CRITICAL": "within 15 minutes",
    "HIGH": "within 1 hour",
    "MODERATE": "within 4 hours",
    "LOW": "within 24 hours",
}


class DelayHarmGraphState(TypedDict, total=False):
    case: CaseMessage
    time_sensitivity: TimeSensitivity
    delay_harm_score: float
    recommended_scan_window: ScanWindow
    reasoning_summary: str
    confidence: float
    result: DelayHarmAssessmentMessage


def _require_case(state: DelayHarmGraphState) -> CaseMessage:
    case = state.get("case")
    if case is None:
        raise KeyError("case")
    return case


def _require_sensitivity(state: DelayHarmGraphState) -> TimeSensitivity:
    sensitivity = state.get("time_sensitivity")
    if sensitivity is None:
        raise KeyError("time_sensitivity")
    return sensitivity


def assess_delay_harm(case: CaseMessage) -> DelayHarmAssessmentMessage:
    logger.info(
        "DELAY_HARM_RECEIVED case_id=%s patient_code=%s",
        case.case_id,
        case.patient_code,
    )
    graph = _build_delay_harm_graph()
    state = graph.invoke({"case": case})
    result = state.get("result")
    if result is None:
        raise KeyError("result")
    return result


def _build_delay_harm_graph():
    graph = StateGraph(DelayHarmGraphState)
    graph.add_node("ingest_case", _ingest_case)
    graph.add_node("assess_time_criticality", _assess_time_criticality)
    graph.add_node("score_delay_harm", _score_delay_harm)
    graph.add_node("recommend_scan_window", _recommend_scan_window)
    graph.add_node("emit_result", _emit_result)

    graph.set_entry_point("ingest_case")
    graph.add_edge("ingest_case", "assess_time_criticality")
    graph.add_edge("assess_time_criticality", "score_delay_harm")
    graph.add_edge("score_delay_harm", "recommend_scan_window")
    graph.add_edge("recommend_scan_window", "emit_result")
    graph.add_edge("emit_result", END)
    return graph.compile()


def _ingest_case(state: DelayHarmGraphState) -> DelayHarmGraphState:
    case = _require_case(state)
    logger.info(
        "DELAY_HARM_INGESTED case_id=%s validation_status=%s",
        case.case_id,
        case.validation_status,
    )
    return state


def _assess_time_criticality(state: DelayHarmGraphState) -> DelayHarmGraphState:
    case = _require_case(state)

    avpu_upper = (case.avpu or "").strip().upper()
    abnormal_avpu = avpu_upper in {"V", "P", "U"}
    spo2_critical = case.spo2 is not None and case.spo2 < 90

    if case.urgency_score >= 8 or abnormal_avpu or spo2_critical:
        sensitivity: TimeSensitivity = "CRITICAL"
    elif case.urgency_score >= 6:
        sensitivity = "HIGH"
    elif case.urgency_score >= 4 or (case.pain_grade is not None and case.pain_grade >= 5):
        sensitivity = "MODERATE"
    else:
        sensitivity = "LOW"

    state["time_sensitivity"] = sensitivity
    return state


def _score_delay_harm(state: DelayHarmGraphState) -> DelayHarmGraphState:
    sensitivity = _require_sensitivity(state)
    case = _require_case(state)

    base = _SENSITIVITY_BASE_SCORE[sensitivity]
    waiting_minutes = case.waiting_time_minutes or 0
    wait_bonus = min((waiting_minutes // 30) * 0.03, 0.10)
    score = round(max(0.0, min(base + wait_bonus, 1.0)), 4)

    state["delay_harm_score"] = score
    return state


def _recommend_scan_window(state: DelayHarmGraphState) -> DelayHarmGraphState:
    sensitivity = _require_sensitivity(state)
    state["recommended_scan_window"] = _SENSITIVITY_SCAN_WINDOW[sensitivity]
    return state


def _emit_result(state: DelayHarmGraphState) -> DelayHarmGraphState:
    case = _require_case(state)
    sensitivity = _require_sensitivity(state)
    score = state.get("delay_harm_score")
    if score is None:
        raise KeyError("delay_harm_score")
    window = state.get("recommended_scan_window")
    if window is None:
        raise KeyError("recommended_scan_window")

    reasoning = (
        f"time_sensitivity={sensitivity}; urgency_score={case.urgency_score}; "
        f"delay_harm_score={score}; "
        f"waiting_time_minutes={case.waiting_time_minutes or 0}"
    )
    state["reasoning_summary"] = reasoning
    state["confidence"] = _base_confidence(case)

    _maybe_refine_with_llm(state)

    result = DelayHarmAssessmentMessage(
        case_id=case.case_id,
        patient_code=case.patient_code,
        delay_harm_score=state.get("delay_harm_score", score),
        time_sensitivity=state.get("time_sensitivity", sensitivity),
        recommended_scan_window=state.get("recommended_scan_window", window),
        reasoning_summary=state.get("reasoning_summary", reasoning),
        confidence=state.get("confidence", _base_confidence(case)),
    )
    state["result"] = result
    logger.info(
        "DELAY_HARM_COMPLETED case_id=%s time_sensitivity=%s delay_harm_score=%s scan_window=%s",
        case.case_id,
        result.time_sensitivity,
        result.delay_harm_score,
        result.recommended_scan_window,
    )
    return state


def _base_confidence(case: CaseMessage) -> float:
    confidence = 0.80
    if case.validation_status != "valid":
        confidence -= 0.15
    if case.spo2 is not None or case.avpu is not None:
        confidence += 0.05
    return round(max(0.35, min(confidence, 0.98)), 2)


def _maybe_refine_with_llm(state: DelayHarmGraphState) -> None:
    if not _llm_enabled():
        logger.info("DELAY_HARM_LLM_SKIPPED case_id=%s", _require_case(state).case_id)
        return
    try:
        logger.info(
            "DELAY_HARM_LLM_ENABLED case_id=%s model=%s",
            _require_case(state).case_id,
            _llm_model_name(),
        )
        llm_result = _invoke_structured_llm(state)
    except Exception:
        logger.exception("DELAY_HARM_LLM_REFINEMENT_FAILED")
        return

    case = _require_case(state)
    if llm_result.case_id != case.case_id or llm_result.patient_code != case.patient_code:
        logger.warning("DELAY_HARM_LLM_IDENTIFIER_MISMATCH case_id=%s", case.case_id)
        return

    state["time_sensitivity"] = llm_result.time_sensitivity
    state["delay_harm_score"] = round(float(llm_result.delay_harm_score), 4)
    state["recommended_scan_window"] = llm_result.recommended_scan_window
    state["reasoning_summary"] = llm_result.reasoning_summary
    state["confidence"] = round(float(llm_result.confidence), 2)


def _invoke_structured_llm(state: DelayHarmGraphState) -> DelayHarmAssessmentMessage:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    api_key_value = os.getenv("AIML_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1")
    model = _llm_model_name()
    llm_kwargs: dict[str, Any] = {
        "model": model,
        "base_url": base_url,
        "temperature": 0,
    }
    if api_key_value:
        llm_kwargs["api_key"] = SecretStr(api_key_value)
    llm = ChatOpenAI(**llm_kwargs)
    case = _require_case(state)
    case_json = json.dumps(case.model_dump(), sort_keys=True)
    result = llm.invoke(
        [
            SystemMessage(content=DELAY_HARM_SYSTEM_PROMPT),
            HumanMessage(content=delay_harm_user_prompt(case_json)),
        ]
    )
    if isinstance(result, DelayHarmAssessmentMessage):
        return result
    content = getattr(result, "content", result)
    if not isinstance(content, str):
        content = str(content)
    payload = parse_json_object(content)
    payload = _normalize_llm_payload(payload, state)
    return DelayHarmAssessmentMessage.model_validate(payload)


def _llm_enabled() -> bool:
    value = os.getenv("CT_DELAY_HARM_USE_LLM", "").strip().lower()
    if value in {"0", "false", "no", "n"}:
        return False
    return bool(os.getenv("AIML_API_KEY") or os.getenv("OPENAI_API_KEY"))


def _llm_model_name() -> str:
    return (
        os.getenv("CT_DELAY_HARM_MODEL")
        or os.getenv("CT_REVIEW_MODEL")
        or "deepseek-v4-flash"
    )


def _normalize_llm_payload(
    payload: dict[str, Any],
    state: DelayHarmGraphState,
) -> dict[str, Any]:
    case = _require_case(state)
    merged = dict(payload)
    merged.setdefault("message_type", "delay_harm_assessment")
    merged["case_id"] = case.case_id
    merged["patient_code"] = case.patient_code
    merged.setdefault("recommended_next_route", "moderator")

    # Coerce delay_harm_score
    raw_score = merged.get("delay_harm_score")
    if isinstance(raw_score, (int, float)):
        merged["delay_harm_score"] = float(raw_score)
    else:
        merged["delay_harm_score"] = state.get("delay_harm_score", 0.2)

    # Coerce confidence
    raw_conf = merged.get("confidence")
    if isinstance(raw_conf, (int, float)):
        merged["confidence"] = float(raw_conf)
    else:
        merged["confidence"] = state.get("confidence", _base_confidence(case))

    # Coerce time_sensitivity
    ts = merged.get("time_sensitivity", "")
    valid_sensitivities = {"LOW", "MODERATE", "HIGH", "CRITICAL"}
    if str(ts).upper() not in valid_sensitivities:
        merged["time_sensitivity"] = state.get("time_sensitivity", "LOW")

    # Coerce recommended_scan_window
    window = merged.get("recommended_scan_window", "")
    valid_windows = {
        "within 15 minutes",
        "within 1 hour",
        "within 4 hours",
        "within 24 hours",
    }
    if window not in valid_windows:
        merged["recommended_scan_window"] = state.get(
            "recommended_scan_window", "within 24 hours"
        )

    # Coerce reasoning_summary
    if not merged.get("reasoning_summary"):
        for alias in ("summary", "reasoning", "explanation", "analysis"):
            value = merged.get(alias)
            if value not in (None, ""):
                merged["reasoning_summary"] = str(value)
                break
    merged.setdefault("reasoning_summary", state.get("reasoning_summary", ""))

    return merged
