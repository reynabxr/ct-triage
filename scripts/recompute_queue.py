from __future__ import annotations

import argparse
import json
import logging

from _bootstrap import add_src_to_path

add_src_to_path()

from storage.queue_engine import get_queue_snapshot, recompute_queue

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute the pending CT queue.")
    parser.add_argument(
        "--reason",
        default="manual_recompute",
        help="Traceability label for this recompute event.",
    )
    parser.add_argument(
        "--case-id",
        help="Optional trigger case_id for the recompute event log.",
    )
    args = parser.parse_args()

    before = get_queue_snapshot()
    result = recompute_queue(reason=args.reason, trigger_case_id=args.case_id)
    after = get_queue_snapshot()

    logger.info("QUEUE_BEFORE\n%s", json.dumps(before, indent=2))
    logger.info("QUEUE_AFTER\n%s", json.dumps(after, indent=2))
    logger.info(
        "QUEUE_RESULT version=%s pending_count=%s affected_cases=%s",
        result["queue_version"],
        result["pending_count"],
        ",".join(result["affected_cases"]) or "none",
    )


if __name__ == "__main__":
    main()
