from __future__ import annotations

import logging
from typing import TypedDict

from band.core import AgentToolsProtocol, HistoryProvider, PlatformMessage, SimpleAdapter

from .band_utils import participant_mention, sender_mention
from .delay_harm_schema import DelayHarmAssessmentMessage
from .moderator_graph import moderate_case
from .moderator_schema import ModeratorDecisionMessage, ModeratorInputMessage
from .shared_schema import model_to_json, parse_json_object
from storage.queue_engine import apply_placement_decision
from storage.queue_store import log_moderator_decision

logger = logging.getLogger(__name__)


class _PendingEntry(TypedDict, total=False):
    review: ModeratorInputMessage
    delay_harm: DelayHarmAssessmentMessage


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
        self._pending: dict[str, _PendingEntry] = {}

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
        except Exception:
            if _is_intended_for(msg.content, self.moderator_mention):
                logger.exception("Failed to parse JSON from message addressed to moderator")
            return

        message_type = payload.get("message_type")

        if message_type == "moderator_input":
            try:
                moderator_input = ModeratorInputMessage.model_validate(payload)
            except Exception as exc:
                if not _is_intended_for(msg.content, self.moderator_mention):
                    return
                logger.exception("Failed to validate ModeratorInputMessage")
                mention = sender_mention(tools, msg, fallback=self.moderator_mention)
                await tools.send_message(
                    content=f"{self.moderator_mention} could not parse moderator input JSON: {exc}",
                    mentions=[mention],
                )
                return
            case_id = moderator_input.case.case_id
            # A fresh review message starts a new moderation cycle for this case_id.
            # We intentionally drop any stale buffered delay-harm packet from an older cycle.
            entry = {"review": moderator_input}
            self._pending[case_id] = entry
            logger.info("MODERATOR_BUFFER_REVIEW_RECEIVED case_id=%s", case_id)

        elif message_type == "delay_harm_assessment":
            try:
                delay_harm = DelayHarmAssessmentMessage.model_validate(payload)
            except Exception as exc:
                if not _is_intended_for(msg.content, self.moderator_mention):
                    return
                logger.exception("Failed to validate DelayHarmAssessmentMessage")
                mention = sender_mention(tools, msg, fallback=self.moderator_mention)
                await tools.send_message(
                    content=f"{self.moderator_mention} could not parse delay harm JSON: {exc}",
                    mentions=[mention],
                )
                return
            case_id = delay_harm.case_id
            entry = self._pending.setdefault(case_id, {})
            entry["delay_harm"] = delay_harm  # type: ignore[typeddict-item]
            logger.info("MODERATOR_BUFFER_DELAY_HARM_RECEIVED case_id=%s", case_id)

        else:
            if _is_intended_for(msg.content, self.moderator_mention):
                logger.warning(
                    "MODERATOR_UNEXPECTED_MESSAGE_TYPE message_type=%s", message_type
                )
            return

        entry = self._pending.get(case_id, {})
        review_msg: ModeratorInputMessage | None = entry.get("review")  # type: ignore[assignment]
        delay_harm_msg: DelayHarmAssessmentMessage | None = entry.get("delay_harm")  # type: ignore[assignment]

        if review_msg is None:
            logger.info(
                "MODERATOR_BUFFER_WAITING_FOR_REVIEW case_id=%s delay_harm_present=%s",
                case_id,
                delay_harm_msg is not None,
            )
            return

        # Proceed with whatever we have — delay_harm may be None if that agent failed/lagged
        self._pending.pop(case_id, None)

        moderator_input = ModeratorInputMessage(
            case=review_msg.case,
            clinical_urgency=review_msg.clinical_urgency,
            queue_snapshot=review_msg.queue_snapshot,
            delay_harm=delay_harm_msg,
        )

        await self._run_moderation(moderator_input, tools, msg)

    async def _run_moderation(
        self,
        moderator_input: ModeratorInputMessage,
        tools: AgentToolsProtocol,
        msg: PlatformMessage,
    ) -> None:
        moderator_decision = moderate_case(
            moderator_input.case,
            moderator_input.clinical_urgency,
            queue_snapshot=moderator_input.queue_snapshot,
        )
        logger.info(
            "CASE_MODERATED case_id=%s clinical_urgency=%s placement_action=%s anchor_case_id=%s comparison_count=%s needs_human_review=%s delay_harm_score=%s",
            moderator_input.case.case_id,
            moderator_decision.clinical_urgency,
            moderator_decision.placement_action,
            moderator_decision.anchor_case_id,
            moderator_decision.comparison_count,
            moderator_decision.needs_human_review,
            moderator_input.delay_harm.delay_harm_score if moderator_input.delay_harm else "N/A",
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
