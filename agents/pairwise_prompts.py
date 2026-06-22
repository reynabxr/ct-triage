from __future__ import annotations

import json
from typing import Any

PAIRWISE_COMPARISON_SYSTEM_PROMPT = """
You are the pairwise clinical ordering component for a CT triage workflow.
Return only one JSON object.

Task:
- Compare patient A and patient B clinically.
- Decide which patient should be seen first in the queue.
- Output only JSON with:
  {
    "chosen_patient": "A" or "B",
    "reasoning": "one short sentence"
  }

Rules:
- Decide only relative ordering between these two patients.
- Do not compute a global rank.
- Do not reorder the queue.
- Do not describe queue mutations.
- Keep reasoning short and clinical.
- Do not invent missing data.
"""


def pairwise_comparison_user_prompt(
    *,
    case_a: dict[str, Any],
    case_b: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "Compare these two CT queue patients and choose who should come first.",
            "",
            "Patient A:",
            json.dumps(case_a, indent=2, sort_keys=True),
            "",
            "Patient B:",
            json.dumps(case_b, indent=2, sort_keys=True),
            "",
            'Return only JSON: {"chosen_patient":"A"|"B","reasoning":"one short sentence"}',
        ]
    )
