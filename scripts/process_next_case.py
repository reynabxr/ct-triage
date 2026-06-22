from __future__ import annotations

import asyncio
import logging

from _bootstrap import add_src_to_path

add_src_to_path()

from labslabs.band_dispatch import dispatch_next_pending_case

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    await dispatch_next_pending_case()


if __name__ == "__main__":
    asyncio.run(main())
