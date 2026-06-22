from __future__ import annotations

import logging

from band.core import AgentToolsProtocol, HistoryProvider, PlatformMessage, SimpleAdapter

from .band_utils import participant_mention
from .router_logic import (
    build_router_decision,
    normalize_case_payload,
    parse_router_input,
    to_case_message,
)
from .shared_schema import model_to_json
from storage.queue_store import get_case, mark_routed, update_case_payload

logger = logging.getLogger(__name__)


class CTRouterAdapter(SimpleAdapter[HistoryProvider]):
    def __init__(
        self,
        *,
        router_mention: str = "@ct_router_agent",
        review_mention: str = "@ct_review_agent",
    ) -> None:
        super().__init__()
        self.router_mention = router_mention
        self.review_mention = review_mention

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
        router_input = parse_router_input(msg.content)
        if (
            router_input.trigger is None
            and router_input.payload is None
            and not _is_intended_for(msg.content, self.router_mention)
        ):
            return

        try:
            record = None
            payload = router_input.payload
            if payload is None and router_input.trigger and router_input.trigger.case_id:
                record = get_case(router_input.trigger.case_id)
                if record is None:
                    logger.warning(
                        "CASE_VALIDATION_FAILURE case_id=%s reason=record_not_found",
                        router_input.trigger.case_id,
                    )
                    return
                payload = record.payload
            elif router_input.trigger and router_input.trigger.case_id:
                record = get_case(router_input.trigger.case_id)
        except Exception:
            logger.exception("Failed to load CT case input")
            return

        if payload is None:
            logger.warning("CASE_VALIDATION_FAILURE case_id=unknown reason=missing_payload")
            return

        try:
            normalized_case = normalize_case_payload(payload, record=record)
        except Exception as exc:
            logger.exception("Failed to normalize CT case input")
            logger.warning(
                "CASE_VALIDATION_FAILURE case_id=%s reason=%s",
                _safe_case_id(payload),
                exc,
            )
            return

        logger.info(
            "CASE_LOADED case_id=%s status=%s",
            normalized_case.case_id,
            record.status if record else "message_payload",
        )
        logger.info(
            "CASE_NORMALIZED case_id=%s validation_status=%s missing_fields=%s urgency_score=%s waiting_time_minutes=%s",
            normalized_case.case_id,
            normalized_case.validation_status,
            ",".join(normalized_case.missing_fields) or "none",
            normalized_case.urgency_score,
            normalized_case.waiting_time_minutes,
        )
        if record is not None and normalized_case.case_id is not None:
            update_case_payload(
                normalized_case.case_id,
                normalized_case.model_dump(),
            )

        decision = build_router_decision(normalized_case)
        if not decision.should_route:
            logger.warning(
                "CASE_VALIDATION_FAILURE case_id=%s missing_fields=%s",
                decision.case_id or "unknown",
                ",".join(decision.missing_fields) or "none",
            )
            return

        case_message = to_case_message(normalized_case)
        review_mention = participant_mention(
            tools,
            self.review_mention,
            "ct_review_agent",
            "ct-review-agent",
            "CT Review Agent",
        )
        content = f"{review_mention}\n```json\n{model_to_json(case_message)}\n```"
        await tools.send_message(content=content, mentions=[review_mention])
        if record is not None and record.status == "pending":
            mark_routed(normalized_case.case_id)
        logger.info("CASE_ROUTED case_id=%s", normalized_case.case_id)


def _is_intended_for(content: str, mention: str) -> bool:
    return mention.lower() in content.lower()


def _safe_case_id(payload: dict[str, object]) -> str:
    for key in ("case_id", "triage_code"):
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "unknown"
