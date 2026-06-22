from __future__ import annotations

import asyncio
import logging
import os

import certifi
from dotenv import load_dotenv

os.environ["SSL_CERT_FILE"] = certifi.where()

from band import Agent
from band.config import load_agent_config

from .review_adapter import CTReviewAdapter
from storage.db import get_db_path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing {name} in .env")
    return value


async def main() -> None:
    load_dotenv()
    agent_id, api_key = load_agent_config("ct_review_agent")
    adapter = CTReviewAdapter(
        review_mention=os.getenv("CT_REVIEW_MENTION", "@ct_review_agent"),
        moderator_mention=os.getenv(
            "CT_MODERATOR_MENTION", "@ct_moderator_agent"
        ),
    )
    agent = Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
        ws_url=_required_env("THENVOI_WS_URL"),
        rest_url=_required_env("THENVOI_REST_URL"),
    )
    logger.info("CT Review Agent using SQLite DB at %s", get_db_path())
    logger.info("CT Review Agent is running. Press Ctrl+C to stop.")
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
