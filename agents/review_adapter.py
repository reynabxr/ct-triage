from __future__ import annotations

import logging

from band.core import AgentToolsProtocol, HistoryProvider, PlatformMessage, SimpleAdapter

from .band_utils import participant_mention, sender_mention
from .moderator_schema import ModeratorInputMessage
from .review_agent import review_case
from .router_schema import CaseMessage
from .shared_schema import model_to_json, parse_json_object
from storage.queue_store import log_clinical_urgency, mark_reviewed

logger = logging.getLogger(__name__)


class CTReviewAdapter(SimpleAdapter[HistoryProvider]):
    def __init__(
        self,
        *,
        review_mention: str = "@ct_review_agent",
        moderator_mention: str = "@ct_moderator_agent",
    ) -> None:
        super().__init__()
        self.review_mention = review_mention
        self.moderator_mention = moderator_mention

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
            if payload.get("message_type") != "case":
                if _is_intended_for(msg.content, self.review_mention):
                    raise ValueError("Expected message_type='case'")
                return
            case = CaseMessage.model_validate(payload)
        except Exception as exc:
            if not _is_intended_for(msg.content, self.review_mention):
                return
            logger.exception("Failed to parse case message")
            mention = sender_mention(tools, msg, fallback=self.review_mention)
            await tools.send_message(
                content=f"{self.review_mention} could not parse case JSON: {exc}",
                mentions=[mention],
            )
            return

        clinical_urgency = review_case(case)
        mark_reviewed(case.case_id)
        log_clinical_urgency(
            case.case_id,
            decision=clinical_urgency.model_dump(),
        )
        logger.info(
            "CASE_CLINICAL_URGENCY_REVIEWED case_id=%s clinical_urgency=%s confidence=%s red_flag_count=%s reasoning_summary=%s",
            case.case_id,
            clinical_urgency.clinical_urgency,
            clinical_urgency.confidence,
            len(clinical_urgency.red_flags),
            clinical_urgency.reasoning_summary,
        )
        moderator_input = ModeratorInputMessage(
            case=case,
            clinical_urgency=clinical_urgency,
        )
        moderator_mention = participant_mention(
            tools,
            self.moderator_mention,
            "ct_moderator_agent",
            "ct-moderator-agent",
            "CT Moderator Agent",
        )
        content = f"{moderator_mention}\n```json\n{model_to_json(moderator_input)}\n```"
        try:
            await tools.send_message(content=content, mentions=[moderator_mention])
        except ValueError as exc:
            logger.error(
                "MODERATOR_SEND_FAILED case_id=%s error=%s available=%s",
                case.case_id,
                exc,
                [getattr(p, "handle", p) for p in tools.participants],
            )


def _is_intended_for(content: str, mention: str) -> bool:
    return mention.lower() in content.lower()
