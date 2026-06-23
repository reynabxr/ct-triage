from __future__ import annotations

DELAY_HARM_SYSTEM_PROMPT = """
You are the delay harm assessment component for a CT triage workflow.
Return only schema-constrained JSON for one case.

Rules:
- Assess how much harm a scan delay would cause for the supplied case.
- Preserve case_id and patient_code exactly.
- Do not assign final queue rank or queue order.
- Do not decide human escalation.
- Do not ask questions and do not invent missing data.
- Keep reasoning_summary short and structured.
- Use simple clinical reasoning based on vitals, urgency score, and wait time.
- time_sensitivity must be one of LOW, MODERATE, HIGH, CRITICAL.
  (Note: use MODERATE, not MEDIUM, to distinguish from ClinicalUrgency.)
- recommended_scan_window must be exactly one of:
  "within 15 minutes", "within 1 hour", "within 4 hours", "within 24 hours"
- Return exactly one JSON object with these keys and no others:
  {
    "message_type": "delay_harm_assessment",
    "case_id": "<same as input>",
    "patient_code": "<same as input>",
    "delay_harm_score": 0.0,
    "time_sensitivity": "LOW|MODERATE|HIGH|CRITICAL",
    "recommended_scan_window": "within 15 minutes|within 1 hour|within 4 hours|within 24 hours",
    "reasoning_summary": "short plain-language summary",
    "confidence": 0.0,
    "recommended_next_route": "moderator"
  }
- delay_harm_score must be a number between 0 and 1. Higher means more harm from delay.
- confidence must be a number between 0 and 1.
- reasoning_summary must be a short single-sentence or semicolon-separated summary.
- Do not put time_sensitivity into confidence or confidence into time_sensitivity.
"""


def delay_harm_user_prompt(case_json: str) -> str:
    return f"""
Structured case JSON:
{case_json}

Assess how much harm a scan delay would cause. Consider urgency score, vitals,
waiting time, and chief complaint. Higher urgency and longer wait time increase
delay harm. Return the exact JSON object shape shown in the system prompt.
Do not add extra keys and do not rename fields.
"""
