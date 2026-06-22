from __future__ import annotations

import logging

from band.core import AgentToolsProtocol, HistoryProvider, PlatformMessage, SimpleAdapter

from .band_utils import sender_mention
from .escalation_agent import create_human_handoff
from .moderator_schema import ModeratorDecisionMessage
from .shared_schema import model_to_json, parse_json_object
from storage.queue_store import mark_escalated_with_handoff

logger = logging.getLogger(__name__)


class CTEscalationAdapter(SimpleAdapter[HistoryProvider]):
    def __init__(
        self,
        *,
        escalation_mention: str = "@ct_escalation_agent",
    ) -> None:
        super().__init__()
        self.escalation_mention = escalation_mention

    async def on_message(
        self,
        msg: PlatformMessage,
        tools: AgentToolsProtocol,
        history: HistoryProvider,
        participants_msg: str | None,
        contacts_msg: str | None,
        *,
        is_session_bootstrap: bool,
        room_id: str,
    ) -> None:
        try:
            payload = parse_json_object(msg.content)
            if payload.get("message_type") != "moderator_decision":
                if _is_intended_for(msg.content, self.escalation_mention):
                    raise ValueError("Expected message_type='moderator_decision'")
                return
            review = ModeratorDecisionMessage.model_validate(payload)
            if not review.needs_human_review:
                return
        except Exception as exc:
            if not _is_intended_for(msg.content, self.escalation_mention):
                return
            logger.exception("Failed to parse review message")
            mention = sender_mention(tools, msg, fallback=self.escalation_mention)
            await tools.send_message(
                content=f"{self.escalation_mention} could not parse review JSON: {exc}",
                mentions=[mention],
            )
            return

        handoff = create_human_handoff(review)
        mark_escalated_with_handoff(
            review.case_id,
            handoff_packet=handoff.model_dump_json(indent=2),
            due_at=handoff.due_at,
        )
        logger.info("CASE_ESCALATED case_id=%s", review.case_id)
        handoff_json = model_to_json(handoff)
        mention = sender_mention(tools, msg, fallback=self.escalation_mention)
        content = f"Human Review Required\n```json\n{handoff_json}\n```"
        await tools.send_message(content=content, mentions=[mention])


def _is_intended_for(content: str, mention: str) -> bool:
    return mention.lower() in content.lower()
