from __future__ import annotations

import argparse
import logging

from _bootstrap import add_src_to_path

add_src_to_path()

from storage.queue_store import get_case, reset_case

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset one case back to pending.")
    parser.add_argument("case_id", help="Case ID to reset")
    args = parser.parse_args()

    case = get_case(args.case_id)
    if case is None:
        raise SystemExit(f"Case not found: {args.case_id}")

    reset_case(args.case_id)
    updated_case = get_case(args.case_id)
    logger.info(
        "CASE_READBACK case_id=%s status=%s final_result_present=%s",
        updated_case.case_id,
        updated_case.status,
        bool(updated_case.final_result),
    )


if __name__ == "__main__":
    main()

