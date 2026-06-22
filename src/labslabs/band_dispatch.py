from __future__ import annotations

import certifi
import json
import logging
import os
from typing import Any

from band.client.rest import DEFAULT_REQUEST_OPTIONS
from band.config import load_agent_config
from thenvoi_rest import (
    AsyncRestClient,
    ChatMessageRequest,
    ChatMessageRequestMentionsItem,
    ChatRoomRequest,
    ParticipantRequest,
)

from storage.queue_store import get_case, get_next_pending_case

os.environ["SSL_CERT_FILE"] = certifi.where()

logger = logging.getLogger(__name__)


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing {name} in .env")
    return value


async def dispatch_next_pending_case() -> dict[str, Any] | None:
    pending_case = get_next_pending_case()
    if pending_case is None:
        logger.info("No dispatchable pending cases remain.")
        return None

    return await dispatch_case(pending_case.case_id)


async def dispatch_case(case_id: str) -> dict[str, Any] | None:
    pending_case = get_case(case_id)
    if pending_case is None:
        logger.info("No dispatchable case found for case_id=%s.", case_id)
        return None

    logger.info("CASE_LOADED case_id=%s status=%s", pending_case.case_id, pending_case.status)

    dispatcher_agent_id, dispatcher_api_key = load_agent_config("ct_dispatcher_agent")
    router_agent_id, _ = load_agent_config("ct_router_agent")
    review_agent_id, _ = load_agent_config("ct_review_agent")
    moderator_agent_id, _ = load_agent_config("ct_moderator_agent")
    escalation_agent_id, _ = load_agent_config("ct_escalation_agent")
    rest_url = _required_env("THENVOI_REST_URL")

    dispatch_client = AsyncRestClient(api_key=dispatcher_api_key, base_url=rest_url)
    room_id = await create_dispatch_room(
        dispatch_client,
        dispatcher_agent_id=dispatcher_agent_id,
        router_agent_id=router_agent_id,
        review_agent_id=review_agent_id,
        moderator_agent_id=moderator_agent_id,
        escalation_agent_id=escalation_agent_id,
        case_id=pending_case.case_id,
    )
    updated_case = get_case(pending_case.case_id)
    if updated_case is not None:
        logger.info(
            "CASE_READBACK case_id=%s status=%s final_result_present=%s",
            updated_case.case_id,
            updated_case.status,
            bool(updated_case.final_result),
        )
    logger.info(
        "Queued case_id=%s into Band room %s from dispatcher agent %s",
        pending_case.case_id,
        room_id,
        dispatcher_agent_id,
    )
    return {
        "case_id": pending_case.case_id,
        "room_id": room_id,
        "dispatcher_agent_id": dispatcher_agent_id,
    }


async def create_dispatch_room(
    dispatch_client: AsyncRestClient,
    *,
    dispatcher_agent_id: str,
    router_agent_id: str,
    review_agent_id: str,
    moderator_agent_id: str,
    escalation_agent_id: str,
    case_id: str,
) -> str:
    room_response = await dispatch_client.agent_api_chats.create_agent_chat(
        chat=ChatRoomRequest(),
        request_options=DEFAULT_REQUEST_OPTIONS,
    )
    room_id = room_response.data.id
    logger.info("Created Band room %s for case_id=%s", room_id, case_id)

    for participant_id in (
        router_agent_id,
        review_agent_id,
        moderator_agent_id,
        escalation_agent_id,
    ):
        await dispatch_client.agent_api_participants.add_agent_chat_participant(
            room_id,
            participant=ParticipantRequest(participant_id=participant_id, role="member"),
            request_options=DEFAULT_REQUEST_OPTIONS,
        )

    participants_response = await dispatch_client.agent_api_participants.list_agent_chat_participants(
        room_id,
        request_options=DEFAULT_REQUEST_OPTIONS,
    )
    participants = participants_response.data
    router_mention = _participant_mention(participants, router_agent_id)

    trigger = json.dumps(
        {
            "message_type": "queue_trigger",
            "case_id": case_id,
            "command": "PROCESS_NEXT_CASE",
            "source": "sqlite_queue",
        },
        indent=2,
    )
    kickoff_content = f"{router_mention}\n```json\n{trigger}\n```"
    await dispatch_client.agent_api_messages.create_agent_chat_message(
        room_id,
        message=ChatMessageRequest(
            content=kickoff_content,
            mentions=[_participant_message_mention(participants, router_agent_id)],
        ),
        request_options=DEFAULT_REQUEST_OPTIONS,
    )
    return room_id


def _participant_mention(participants: list[object], participant_id: str) -> str:
    for participant in participants:
        if getattr(participant, "id", None) == participant_id:
            handle = getattr(participant, "handle", None)
            if handle:
                return handle
            name = getattr(participant, "name", None)
            if name:
                return f"@{name}"
    raise RuntimeError(f"Participant {participant_id} not found in room")


def _participant_message_mention(
    participants: list[object],
    participant_id: str,
) -> ChatMessageRequestMentionsItem:
    for participant in participants:
        if getattr(participant, "id", None) != participant_id:
            continue
        return ChatMessageRequestMentionsItem(
            id=participant_id,
            handle=getattr(participant, "handle", None),
            name=getattr(participant, "name", None),
        )
    raise RuntimeError(f"Participant {participant_id} not found in room")
