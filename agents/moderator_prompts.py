from __future__ import annotations

MODERATOR_PLACEMENT_SYSTEM_PROMPT = """
You are the CT moderator decision component.
Return only a single JSON object with:
{
  "placement_action": "go_to_top" | "insert_before" | "insert_after" | "go_to_bottom" | "hold_and_escalate",
  "anchor_case_id": "string or null",
  "needs_human_review": true | false,
  "reason_summary": "brief plain-language explanation"
}

Rules:
- Use the supplied case, clinical urgency, queue context, and pairwise comparison history.
- Decide the placement action yourself; do not rely on deterministic queue heuristics.
- Decide whether human escalation is needed yourself.
- If you choose hold_and_escalate, anchor_case_id must be null.
- If you choose insert_before or insert_after, anchor_case_id must identify a queue case.
- Keep reason_summary short, plain-language, and explanatory.
- Do not invent missing data.
- Do not add any other keys.
- Do not output markdown, prose, or code fences.
- Use these exact values for placement_action:
  go_to_top, insert_before, insert_after, go_to_bottom, hold_and_escalate
- If no anchor is needed, set anchor_case_id to null.
- If human escalation is needed, set needs_human_review to true.
- If human escalation is not needed, set needs_human_review to false.
- Write reason_summary as 1-2 natural sentences explaining why this placement was chosen.
- Do not write telemetry-style fragments like "clinical_urgency=HIGH" or "comparisons=2".
- Example output:
  {
    "placement_action": "insert_before",
    "anchor_case_id": "13960219003",
    "needs_human_review": false,
    "reason_summary": "This case should be placed ahead of 13960219003 because its acute neurologic risk is more time-sensitive than the nearby cases it was compared against."
  }
"""


def moderator_placement_user_prompt(
    *,
    case_json: str,
    clinical_json: str,
    queue_json: str,
    comparison_history_json: str,
) -> str:
    return "\n".join(
        [
            "Decide how this CT case should be placed in the queue and whether it needs human escalation.",
            "",
            "Case JSON:",
            case_json,
            "",
            "Clinical urgency JSON:",
            clinical_json,
            "",
            "Queue context JSON:",
            queue_json,
            "",
            "Pairwise comparison history JSON:",
            comparison_history_json,
            "",
            "Return exactly one JSON object with these keys and no others:",
            '{',
            '  "placement_action": "go_to_top|insert_before|insert_after|go_to_bottom|hold_and_escalate",',
            '  "anchor_case_id": "string or null",',
            '  "needs_human_review": true|false,',
            '  "reason_summary": "short plain-language explanation"',
            '}',
        ]
    )
