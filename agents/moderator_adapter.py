from __future__ import annotations

import logging

from band.core import AgentToolsProtocol, HistoryProvider, PlatformMessage, SimpleAdapter

from .band_utils import participant_mention, sender_mention
from .moderator_graph import moderate_case
from .moderator_schema import ModeratorDecisionMessage, ModeratorInputMessage
from .shared_schema import model_to_json, parse_json_object
from storage.queue_engine import apply_placement_decision
from storage.queue_store import log_moderator_decision

logger = logging.getLogger(__name__)


class CTModeratorAdapter(SimpleAdapter[HistoryProvider]):
    def __init__(
        self,
        *,
        moderator_mention: str = "@ct_moderator_agent",
        escalation_mention: str = "@ct_escalation_agent",
    ) -> None:
        super().__init__()
        self.moderator_mention = moderator_mention
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
            if payload.get("message_type") != "moderator_input":
                if _is_intended_for(msg.content, self.moderator_mention):
                    raise ValueError("Expected message_type='moderator_input'")
                return
            moderator_input = ModeratorInputMessage.model_validate(payload)
        except Exception as exc:
            if not _is_intended_for(msg.content, self.moderator_mention):
                return
            logger.exception("Failed to parse moderator input message")
            mention = sender_mention(tools, msg, fallback=self.moderator_mention)
            await tools.send_message(
                content=f"{self.moderator_mention} could not parse moderator input JSON: {exc}",
                mentions=[mention],
            )
            return

        moderator_decision = moderate_case(
            moderator_input.case,
            moderator_input.clinical_urgency,
            queue_snapshot=moderator_input.queue_snapshot,
        )
        logger.info(
            "CASE_MODERATED case_id=%s clinical_urgency=%s placement_action=%s anchor_case_id=%s comparison_count=%s needs_human_review=%s",
            moderator_input.case.case_id,
            moderator_decision.clinical_urgency,
            moderator_decision.placement_action,
            moderator_decision.anchor_case_id,
            moderator_decision.comparison_count,
            moderator_decision.needs_human_review,
        )

        decision_json = model_to_json(moderator_decision)
        log_moderator_decision(
            moderator_input.case.case_id,
            decision=moderator_decision.model_dump(),
        )
        apply_placement_decision(
            case_id=moderator_input.case.case_id,
            decision=moderator_decision.model_dump(),
            case_payload=moderator_input.case.model_dump(),
        )
        if moderator_decision.needs_human_review:
            escalation_mention = participant_mention(
                tools,
                self.escalation_mention,
                "ct_escalation_agent",
                "ct-escalation-agent",
                "CT Escalation Agent",
            )
            content = f"{escalation_mention}\n```json\n{decision_json}\n```"
            await tools.send_message(content=content, mentions=[escalation_mention])
            return

        mention = sender_mention(tools, msg, fallback=self.moderator_mention)
        content = f"{mention}\n```json\n{decision_json}\n```"
        await tools.send_message(content=content, mentions=[mention])


def _is_intended_for(content: str, mention: str) -> bool:
    return mention.lower() in content.lower()
