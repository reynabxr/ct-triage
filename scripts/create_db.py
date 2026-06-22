from __future__ import annotations

import logging

from _bootstrap import add_src_to_path

add_src_to_path()

from storage.db import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    path = init_db()
    logger.info("Initialized SQLite database at %s", path)


if __name__ == "__main__":
    main()
