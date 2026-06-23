from __future__ import annotations

import certifi
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from band.client.rest import DEFAULT_REQUEST_OPTIONS
from band.config import load_agent_config
from band_rest import (
    AsyncRestClient,
    ChatMessageRequest,
    ChatMessageRequestMentionsItem,
    ChatRoomRequest,
    ParticipantRequest,
)

from storage.queue_store import (
    bind_case_dispatch_room,
    claim_case_dispatch,
    clear_shared_room_id,
    get_case,
    get_next_pending_case,
    get_shared_room_id,
    release_case_dispatch_claim,
    set_shared_room_id,
)

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

    if pending_case.status != "pending":
        logger.info(
            "CASE_DISPATCH_SKIPPED case_id=%s reason=status_not_dispatchable status=%s",
            pending_case.case_id,
            pending_case.status,
        )
        return {
            "case_id": pending_case.case_id,
            "dispatch_status": "skipped",
            "skip_reason": f"status={pending_case.status}",
            "room_id": pending_case.dispatch_room_id,
        }

    trigger_id = str(uuid.uuid4())
    requested_at = _utc_now()
    if not claim_case_dispatch(
        pending_case.case_id,
        trigger_id=trigger_id,
        requested_at=requested_at,
    ):
        refreshed_case = get_case(pending_case.case_id)
        skip_reason = "duplicate_in_flight"
        if refreshed_case is not None and refreshed_case.status != "pending":
            skip_reason = f"status={refreshed_case.status}"
        logger.info(
            "CASE_DISPATCH_SKIPPED case_id=%s reason=%s",
            pending_case.case_id,
            skip_reason,
        )
        return {
            "case_id": pending_case.case_id,
            "dispatch_status": "skipped",
            "skip_reason": skip_reason,
            "room_id": refreshed_case.dispatch_room_id if refreshed_case else None,
        }

    logger.info("CASE_LOADED case_id=%s status=%s", pending_case.case_id, pending_case.status)

    dispatcher_agent_id, dispatcher_api_key = load_agent_config("ct_dispatcher_agent")
    router_agent_id, _ = load_agent_config("ct_router_agent")
    review_agent_id, _ = load_agent_config("ct_review_agent")
    moderator_agent_id, _ = load_agent_config("ct_moderator_agent")
    escalation_agent_id, _ = load_agent_config("ct_escalation_agent")
    delay_harm_agent_id, _ = load_agent_config("ct_delay_harm_agent")
    rest_url = _required_env("THENVOI_REST_URL")

    dispatch_client = AsyncRestClient(api_key=dispatcher_api_key, base_url=rest_url)
    try:
        room_id, recovered_room = await get_or_create_shared_dispatch_room(
            dispatch_client,
            dispatcher_agent_id=dispatcher_agent_id,
            router_agent_id=router_agent_id,
            review_agent_id=review_agent_id,
            moderator_agent_id=moderator_agent_id,
            escalation_agent_id=escalation_agent_id,
            delay_harm_agent_id=delay_harm_agent_id,
        )
        bind_case_dispatch_room(
            pending_case.case_id,
            trigger_id=trigger_id,
            room_id=room_id,
        )
        room_id, recovered_post = await post_queue_trigger(
            dispatch_client,
            room_id=room_id,
            dispatcher_agent_id=dispatcher_agent_id,
            router_agent_id=router_agent_id,
            review_agent_id=review_agent_id,
            moderator_agent_id=moderator_agent_id,
            escalation_agent_id=escalation_agent_id,
            delay_harm_agent_id=delay_harm_agent_id,
            case_id=pending_case.case_id,
            trigger_id=trigger_id,
            requested_at=requested_at,
        )
        recovered_room = recovered_room or recovered_post
    except Exception:
        release_case_dispatch_claim(pending_case.case_id, trigger_id=trigger_id)
        raise

    updated_case = get_case(pending_case.case_id)
    if updated_case is not None:
        logger.info(
            "CASE_READBACK case_id=%s status=%s final_result_present=%s",
            updated_case.case_id,
            updated_case.status,
            bool(updated_case.final_result),
        )
    logger.info(
        "CASE_DISPATCHED case_id=%s room_id=%s dispatcher_agent_id=%s dispatch_status=posted recovered_room=%s trigger_id=%s",
        pending_case.case_id,
        room_id,
        dispatcher_agent_id,
        recovered_room,
        trigger_id,
    )
    return {
        "case_id": pending_case.case_id,
        "room_id": room_id,
        "dispatcher_agent_id": dispatcher_agent_id,
        "dispatch_status": "posted",
        "recovered_room": recovered_room,
        "trigger_id": trigger_id,
    }


async def get_or_create_shared_dispatch_room(
    dispatch_client: AsyncRestClient,
    *,
    dispatcher_agent_id: str,
    router_agent_id: str,
    review_agent_id: str,
    moderator_agent_id: str,
    escalation_agent_id: str,
    delay_harm_agent_id: str,
    force_recreate: bool = False,
) -> tuple[str, bool]:
    participant_ids = (
        router_agent_id,
        review_agent_id,
        moderator_agent_id,
        escalation_agent_id,
        delay_harm_agent_id,
    )
    stored_room_id = None if force_recreate else get_shared_room_id()
    if stored_room_id:
        try:
            await dispatch_client.agent_api_chats.get_agent_chat(
                stored_room_id,
                request_options=DEFAULT_REQUEST_OPTIONS,
            )
            await ensure_room_participants(
                dispatch_client,
                room_id=stored_room_id,
                participant_ids=participant_ids,
            )
            return stored_room_id, False
        except Exception:
            logger.exception(
                "SHARED_ROOM_INVALID room_id=%s dispatcher_agent_id=%s",
                stored_room_id,
                dispatcher_agent_id,
            )
            clear_shared_room_id()

    room_response = await dispatch_client.agent_api_chats.create_agent_chat(
        chat=ChatRoomRequest(),
        request_options=DEFAULT_REQUEST_OPTIONS,
    )
    room_id = room_response.data.id
    await ensure_room_participants(
        dispatch_client,
        room_id=room_id,
        participant_ids=participant_ids,
    )
    set_shared_room_id(room_id)
    logger.info(
        "SHARED_ROOM_CREATED room_id=%s dispatcher_agent_id=%s replaced_existing=%s",
        room_id,
        dispatcher_agent_id,
        bool(stored_room_id or force_recreate),
    )
    return room_id, bool(stored_room_id or force_recreate)


async def ensure_room_participants(
    dispatch_client: AsyncRestClient,
    *,
    room_id: str,
    participant_ids: tuple[str, ...],
) -> list[object]:
    participants_response = await dispatch_client.agent_api_participants.list_agent_chat_participants(
        room_id,
        request_options=DEFAULT_REQUEST_OPTIONS,
    )
    participants = list(participants_response.data)
    participant_ids_present = {getattr(participant, "id", None) for participant in participants}

    for participant_id in participant_ids:
        if participant_id in participant_ids_present:
            continue
        await dispatch_client.agent_api_participants.add_agent_chat_participant(
            room_id,
            participant=ParticipantRequest(participant_id=participant_id, role="member"),
            request_options=DEFAULT_REQUEST_OPTIONS,
        )

    if not all(participant_id in participant_ids_present for participant_id in participant_ids):
        participants_response = await dispatch_client.agent_api_participants.list_agent_chat_participants(
            room_id,
            request_options=DEFAULT_REQUEST_OPTIONS,
        )
        participants = list(participants_response.data)
    return participants


async def post_queue_trigger(
    dispatch_client: AsyncRestClient,
    *,
    room_id: str,
    dispatcher_agent_id: str,
    router_agent_id: str,
    review_agent_id: str,
    moderator_agent_id: str,
    escalation_agent_id: str,
    delay_harm_agent_id: str,
    case_id: str,
    trigger_id: str,
    requested_at: str,
) -> tuple[str, bool]:
    try:
        await _post_queue_trigger_once(
            dispatch_client,
            room_id=room_id,
            router_agent_id=router_agent_id,
            case_id=case_id,
            trigger_id=trigger_id,
            requested_at=requested_at,
        )
        return room_id, False
    except Exception:
        logger.exception(
            "CASE_TRIGGER_POST_FAILED case_id=%s room_id=%s trigger_id=%s retrying_with_recreated_room=true",
            case_id,
            room_id,
            trigger_id,
        )

    clear_shared_room_id()
    recreated_room_id, _ = await get_or_create_shared_dispatch_room(
        dispatch_client,
        dispatcher_agent_id=dispatcher_agent_id,
        router_agent_id=router_agent_id,
        review_agent_id=review_agent_id,
        moderator_agent_id=moderator_agent_id,
        escalation_agent_id=escalation_agent_id,
        delay_harm_agent_id=delay_harm_agent_id,
        force_recreate=True,
    )
    bind_case_dispatch_room(case_id, trigger_id=trigger_id, room_id=recreated_room_id)
    await _post_queue_trigger_once(
        dispatch_client,
        room_id=recreated_room_id,
        router_agent_id=router_agent_id,
        case_id=case_id,
        trigger_id=trigger_id,
        requested_at=requested_at,
    )
    return recreated_room_id, True


async def _post_queue_trigger_once(
    dispatch_client: AsyncRestClient,
    *,
    room_id: str,
    router_agent_id: str,
    case_id: str,
    trigger_id: str,
    requested_at: str,
) -> None:
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
            "dispatch_trigger_id": trigger_id,
            "dispatched_at": requested_at,
            "shared_chat": True,
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
