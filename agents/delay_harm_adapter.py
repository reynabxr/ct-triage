from __future__ import annotations

import logging

from band.core import AgentToolsProtocol, HistoryProvider, PlatformMessage, SimpleAdapter

from .band_utils import participant_mention, sender_mention
from .delay_harm_agent import run_delay_harm_assessment
from .delay_harm_schema import DelayHarmAssessmentMessage
from .router_schema import CaseMessage
from .shared_schema import model_to_json, parse_json_object
from storage.queue_store import log_delay_harm_assessment

logger = logging.getLogger(__name__)


class CTDelayHarmAdapter(SimpleAdapter[HistoryProvider]):
    def __init__(
        self,
        *,
        delay_harm_mention: str = "@ct_delay_harm_agent",
        moderator_mention: str = "@ct_moderator_agent",
    ) -> None:
        super().__init__()
        self.delay_harm_mention = delay_harm_mention
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
                if _is_intended_for(msg.content, self.delay_harm_mention):
                    raise ValueError("Expected message_type='case'")
                return
            case = CaseMessage.model_validate(payload)
        except Exception as exc:
            if not _is_intended_for(msg.content, self.delay_harm_mention):
                return
            logger.exception("Failed to parse case message")
            mention = sender_mention(tools, msg, fallback=self.delay_harm_mention)
            await tools.send_message(
                content=f"{self.delay_harm_mention} could not parse case JSON: {exc}",
                mentions=[mention],
            )
            return

        assessment = run_delay_harm_assessment(case)
        log_delay_harm_assessment(
            case.case_id,
            assessment=assessment.model_dump(),
        )
        logger.info(
            "CASE_DELAY_HARM_ASSESSED case_id=%s time_sensitivity=%s delay_harm_score=%s scan_window=%s confidence=%s",
            case.case_id,
            assessment.time_sensitivity,
            assessment.delay_harm_score,
            assessment.recommended_scan_window,
            assessment.confidence,
        )
        moderator_mention = participant_mention(
            tools,
            self.moderator_mention,
            "ct_moderator_agent",
            "ct-moderator-agent",
            "CT Moderator Agent",
        )
        content = f"{moderator_mention}\n```json\n{model_to_json(assessment)}\n```"
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
