from __future__ import annotations

import json
import logging
import os
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import SecretStr

from .review_prompts import (
    CLINICAL_URGENCY_SYSTEM_PROMPT,
    clinical_urgency_user_prompt,
)
from .review_schema import ClinicalUrgency, ClinicalUrgencyMessage
from .shared_schema import parse_json_object
from .router_schema import CaseMessage

logger = logging.getLogger(__name__)

PHYSIOLOGIC_FIELDS = (
    "bp_systolic",
    "bp_diastolic",
    "pulse_rate",
    "respiratory_rate",
    "spo2",
    "avpu",
)


class ReviewGraphState(TypedDict, total=False):
    case: CaseMessage
    red_flags: list[str]
    physiologic_instability: list[str]
    missing_information: list[str]
    urgency: ClinicalUrgency
    confidence: float
    reasoning_summary: str
    result: ClinicalUrgencyMessage


def _require_case(state: ReviewGraphState) -> CaseMessage:
    case = state.get("case")
    if case is None:
        raise KeyError("case")
    return case


def _require_urgency(state: ReviewGraphState) -> ClinicalUrgency:
    urgency = state.get("urgency")
    if urgency is None:
        raise KeyError("urgency")
    return urgency


def _require_confidence(state: ReviewGraphState) -> float:
    confidence = state.get("confidence")
    if confidence is None:
        raise KeyError("confidence")
    return confidence


def _require_reasoning_summary(state: ReviewGraphState) -> str:
    reasoning_summary = state.get("reasoning_summary")
    if reasoning_summary is None:
        raise KeyError("reasoning_summary")
    return reasoning_summary


def review_clinical_urgency(case: CaseMessage) -> ClinicalUrgencyMessage:
    logger.info(
        "CLINICAL_URGENCY_RECEIVED case_id=%s patient_code=%s",
        case.case_id,
        case.patient_code,
    )
    graph = build_review_graph()
    state = graph.invoke({"case": case})
    result = state.get("result")
    if result is None:
        raise KeyError("result")
    return result


def build_review_graph():
    graph = StateGraph(ReviewGraphState)
    graph.add_node("ingest_case", ingest_case)
    graph.add_node("assess_red_flags", assess_red_flags)
    graph.add_node("assess_physiologic_instability", assess_physiologic_instability)
    graph.add_node("assess_missingness", assess_missingness)
    graph.add_node("synthesize_urgency", synthesize_urgency)
    graph.add_node("emit_structured_result", emit_structured_result)

    graph.set_entry_point("ingest_case")
    graph.add_edge("ingest_case", "assess_red_flags")
    graph.add_edge("assess_red_flags", "assess_physiologic_instability")
    graph.add_edge("assess_physiologic_instability", "assess_missingness")
    graph.add_edge("assess_missingness", "synthesize_urgency")
    graph.add_edge("synthesize_urgency", "emit_structured_result")
    graph.add_edge("emit_structured_result", END)
    return graph.compile()


def ingest_case(state: ReviewGraphState) -> ReviewGraphState:
    case = _require_case(state)
    logger.info(
        "CLINICAL_URGENCY_INGESTED case_id=%s validation_status=%s",
        case.case_id,
        case.validation_status,
    )
    return state


def assess_red_flags(state: ReviewGraphState) -> ReviewGraphState:
    case = _require_case(state)
    flags: list[str] = []

    if case.avpu and case.avpu.strip().upper() in {"V", "P", "U"}:
        flags.append("abnormal_avpu")
    if case.spo2 is not None and case.spo2 < 92:
        flags.append("low_spo2")
    if case.bp_systolic is not None and case.bp_systolic < 90:
        flags.append("hypotension")
    if case.pulse_rate is not None and (case.pulse_rate < 40 or case.pulse_rate >= 130):
        flags.append("abnormal_pulse")
    if case.respiratory_rate is not None and (
        case.respiratory_rate <= 8 or case.respiratory_rate >= 30
    ):
        flags.append("abnormal_respiratory_rate")
    if case.pain_grade is not None and case.pain_grade >= 8:
        flags.append("severe_pain")
    if _has_complaint_text(case, ("chest pain", "stroke", "weakness", "dyspnea")):
        flags.append("high_risk_chief_complaint")

    state["red_flags"] = _dedupe(flags)
    return state


def assess_physiologic_instability(state: ReviewGraphState) -> ReviewGraphState:
    case = _require_case(state)
    instability: list[str] = []

    if case.spo2 is not None:
        if case.spo2 < 90:
            instability.append("severe_hypoxemia")
        elif case.spo2 < 95:
            instability.append("mild_hypoxemia")
    if case.bp_systolic is not None:
        if case.bp_systolic < 90:
            instability.append("shock_range_systolic_bp")
        elif case.bp_systolic >= 180:
            instability.append("severe_hypertension_systolic_bp")
    if case.respiratory_rate is not None:
        if case.respiratory_rate <= 8:
            instability.append("bradypnea")
        elif case.respiratory_rate >= 30:
            instability.append("tachypnea")
    if case.pulse_rate is not None:
        if case.pulse_rate < 40:
            instability.append("severe_bradycardia")
        elif case.pulse_rate >= 130:
            instability.append("marked_tachycardia")
    if case.avpu and case.avpu.strip().upper() in {"V", "P", "U"}:
        instability.append("reduced_consciousness")
    if case.age is not None and case.age >= 75 and instability:
        instability.append("older_adult_with_instability")

    state["physiologic_instability"] = _dedupe(instability)
    return state


def assess_missingness(state: ReviewGraphState) -> ReviewGraphState:
    case = _require_case(state)
    missing: list[str] = []
    if _is_blank(case.patient_code):
        missing.append("patient_code")
    if _is_blank(case.case_id):
        missing.append("case_id")
    state["missing_information"] = _dedupe(missing)
    return state


def synthesize_urgency(state: ReviewGraphState) -> ReviewGraphState:
    case = _require_case(state)
    red_flags = state.get("red_flags", [])
    physiologic_instability = state.get("physiologic_instability", [])
    missing_information = state.get("missing_information", [])

    urgency = _rule_based_urgency(case, red_flags, physiologic_instability)
    confidence = _confidence(case, red_flags, physiologic_instability, missing_information)
    reasoning_summary = _reasoning_summary(
        case,
        urgency,
        red_flags,
        physiologic_instability,
        missing_information,
    )

    state["urgency"] = urgency
    state["confidence"] = confidence
    state["reasoning_summary"] = reasoning_summary
    _maybe_refine_with_llm(state)
    return state


def emit_structured_result(state: ReviewGraphState) -> ReviewGraphState:
    case = _require_case(state)
    result = ClinicalUrgencyMessage(
        case_id=case.case_id,
        patient_code=case.patient_code,
        clinical_urgency=_require_urgency(state),
        confidence=_require_confidence(state),
        red_flags=state.get("red_flags", []),
        missing_information=state.get("missing_information", []),
        reasoning_summary=_require_reasoning_summary(state),
        recommended_next_route="moderator",
    )
    state["result"] = result
    logger.info(
        "CLINICAL_URGENCY_COMPLETED case_id=%s clinical_urgency=%s confidence=%s red_flags=%s",
        case.case_id,
        result.clinical_urgency,
        result.confidence,
        ",".join(result.red_flags) or "none",
    )
    return state


def _rule_based_urgency(
    case: CaseMessage,
    red_flags: list[str],
    physiologic_instability: list[str],
) -> ClinicalUrgency:
    critical_flags = {
        "abnormal_avpu",
        "low_spo2",
        "hypotension",
        "abnormal_respiratory_rate",
    }
    if len(critical_flags.intersection(red_flags)) >= 2:
        return "CRITICAL"
    if "severe_hypoxemia" in physiologic_instability:
        return "CRITICAL"
    if red_flags or case.urgency_score >= 8:
        return "HIGH"
    if (
        case.urgency_score >= 4
        or "mild_hypoxemia" in physiologic_instability
        or (case.pain_grade is not None and case.pain_grade >= 5)
    ):
        return "MEDIUM"
    return "LOW"


def _confidence(
    case: CaseMessage,
    red_flags: list[str],
    physiologic_instability: list[str],
    missing_information: list[str],
) -> float:
    confidence = 0.82
    if red_flags or physiologic_instability:
        confidence += 0.08
    if case.validation_status != "valid":
        confidence -= 0.18
    if not any(field in missing_information for field in {"patient_code", "case_id"}):
        confidence += 0.05
    confidence -= min(len(missing_information), 2) * 0.08
    return round(max(0.35, min(confidence, 0.98)), 2)


def _reasoning_summary(
    case: CaseMessage,
    urgency: ClinicalUrgency,
    red_flags: list[str],
    physiologic_instability: list[str],
    missing_information: list[str],
) -> str:
    pieces = [f"urgency={urgency}", f"urgency_score={case.urgency_score}"]
    if red_flags:
        pieces.append("red_flags=" + ",".join(red_flags[:5]))
    if physiologic_instability:
        pieces.append("instability=" + ",".join(physiologic_instability[:5]))
    if case.chief_complaint_description:
        pieces.append("chief_complaint_description_present")
    elif case.chief_complaint_code:
        pieces.append("chief_complaint_code_present_without_description")
    if missing_information:
        pieces.append("missing=" + ",".join(missing_information[:5]))
    return "; ".join(pieces)


def _maybe_refine_with_llm(state: ReviewGraphState) -> None:
    if not _llm_enabled():
        logger.info("CLINICAL_URGENCY_LLM_SKIPPED case_id=%s", _require_case(state).case_id)
        return
    try:
        logger.info(
            "CLINICAL_URGENCY_LLM_ENABLED case_id=%s model=%s",
            _require_case(state).case_id,
            _llm_model_name(),
        )
        llm_result = _invoke_structured_llm(state)
    except Exception:
        logger.exception("CLINICAL_URGENCY_LLM_REFINEMENT_FAILED")
        return

    case = _require_case(state)
    if llm_result.case_id != case.case_id or llm_result.patient_code != case.patient_code:
        logger.warning("CLINICAL_URGENCY_LLM_IDENTIFIER_MISMATCH case_id=%s", case.case_id)
        return
    state["urgency"] = llm_result.clinical_urgency
    state["confidence"] = round(float(llm_result.confidence), 2)
    state["red_flags"] = _dedupe(llm_result.red_flags)
    state["missing_information"] = _dedupe(llm_result.missing_information)
    state["reasoning_summary"] = llm_result.reasoning_summary


def _invoke_structured_llm(state: ReviewGraphState) -> ClinicalUrgencyMessage:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    api_key_value = os.getenv("AIML_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1")
    model = os.getenv("CT_REVIEW_MODEL", "deepseek-v4-flash")
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
            SystemMessage(content=CLINICAL_URGENCY_SYSTEM_PROMPT),
            HumanMessage(content=clinical_urgency_user_prompt(case_json)),
        ]
    )
    if isinstance(result, ClinicalUrgencyMessage):
        return result
    content = getattr(result, "content", result)
    if not isinstance(content, str):
        content = str(content)
    payload = parse_json_object(content)
    payload = _normalize_llm_payload(payload, state)
    return ClinicalUrgencyMessage.model_validate(payload)


def _llm_enabled() -> bool:
    value = os.getenv("CT_REVIEW_USE_LLM", "").strip().lower()
    if value in {"0", "false", "no", "n"}:
        return False
    return bool(os.getenv("AIML_API_KEY") or os.getenv("OPENAI_API_KEY"))


def _llm_model_name() -> str:
    return os.getenv("CT_REVIEW_MODEL", "deepseek-v4-flash")


def _has_complaint_text(case: CaseMessage, terms: tuple[str, ...]) -> bool:
    text = (case.chief_complaint_description or "").strip().lower()
    return bool(text) and any(term in text for term in terms)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _normalize_llm_payload(
    payload: dict[str, Any],
    state: ReviewGraphState,
) -> dict[str, Any]:
    """Restore required schema fields and immutable identifiers before validation."""
    case = _require_case(state)
    merged = dict(payload)
    merged.setdefault("message_type", "clinical_urgency")
    merged["case_id"] = case.case_id
    merged["patient_code"] = case.patient_code
    if "clinical_urgency" not in merged and "urgency" in merged:
        merged["clinical_urgency"] = merged.pop("urgency")
    if "clinical_urgency" not in merged:
        confidence_value = merged.get("confidence")
        if isinstance(confidence_value, str) and confidence_value.strip().upper() in {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }:
            merged["clinical_urgency"] = confidence_value.strip().upper()
            merged["confidence"] = _require_confidence(state)
    if "reasoning_summary" not in merged:
        for alias in ("summary", "reasoning", "explanation", "analysis"):
            value = merged.get(alias)
            if value not in (None, ""):
                merged["reasoning_summary"] = str(value)
                break
    merged.setdefault("clinical_urgency", _require_urgency(state))
    merged["confidence"] = _coerce_confidence(merged.get("confidence"), state)
    merged.setdefault("red_flags", state.get("red_flags", []))
    merged.setdefault("missing_information", state.get("missing_information", []))
    merged.setdefault("reasoning_summary", _require_reasoning_summary(state))
    merged.setdefault("recommended_next_route", "moderator")
    return merged


def _is_blank(value: Any) -> bool:
    return value in (None, "") or str(value).strip() == ""


def _coerce_confidence(value: Any, state: ReviewGraphState) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        try:
            return float(cleaned)
        except ValueError:
            pass
        if cleaned.upper() in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            return _require_confidence(state)
    return _require_confidence(state)
