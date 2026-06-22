from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone

from _bootstrap import add_src_to_path

add_src_to_path()

from storage.queue_store import expire_human_reviews

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Expire overdue escalated CT cases.")
    parser.add_argument(
        "--due-before",
        help="Expire cases due on or before this UTC ISO timestamp.",
    )
    parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=None,
        help="Expire cases whose human_due_at is older than this many minutes from now.",
    )
    args = parser.parse_args()

    due_before = _parse_due_before(args.due_before, args.timeout_minutes)
    expired = expire_human_reviews(due_before=due_before)
    logger.info("EXPIRED_CASES case_ids=%s", ",".join(expired) or "none")


def _parse_due_before(value: str | None, timeout_minutes: int | None) -> datetime | None:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    if timeout_minutes is not None:
        return datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
    return None


if __name__ == "__main__":
    main()
