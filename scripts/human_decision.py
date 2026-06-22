from __future__ import annotations

import argparse
import logging

from _bootstrap import add_src_to_path

add_src_to_path()

from storage.queue_store import apply_human_decision, get_case

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply a human decision to an escalated CT case."
    )
    parser.add_argument("case_id", help="Escalated case_id to update")
    parser.add_argument(
        "decision",
        choices=("approve", "return_to_review"),
        help="Human decision to apply",
    )
    parser.add_argument(
        "--notes",
        default=None,
        help="Optional operator notes saved with the decision",
    )
    args = parser.parse_args()

    case = get_case(args.case_id)
    if case is None:
        raise SystemExit(f"Case not found: {args.case_id}")

    result = apply_human_decision(
        args.case_id,
        decision=args.decision,
        notes=args.notes,
    )
    if result is None:
        raise SystemExit(
            f"Case {args.case_id} is not currently awaiting a human decision"
        )

    logger.info(
        "HUMAN_DECISION_APPLIED case_id=%s decision=%s status=%s",
        args.case_id,
        args.decision,
        get_case(args.case_id).status if get_case(args.case_id) else "unknown",
    )
    logger.info("HUMAN_DECISION_RESULT %s", result)


if __name__ == "__main__":
    main()
