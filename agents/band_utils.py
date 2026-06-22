from __future__ import annotations

from typing import Any

from band.core import AgentToolsProtocol, PlatformMessage


def participant_mention(
    tools: AgentToolsProtocol,
    configured_mention: str,
    *aliases: str,
) -> str:
    """Resolve a configured mention to an actual participant handle when possible."""
    wanted = {_normalize(configured_mention), *[_normalize(alias) for alias in aliases]}
    wanted.discard("")

    for participant in tools.participants:
        handle = _field(participant, "handle")
        name = _field(participant, "name")
        candidates = {
            _normalize(handle),
            _normalize(name),
            _normalize(handle.rsplit("/", 1)[-1]),
        }
        if wanted & candidates:
            return handle or configured_mention
    return configured_mention


def sender_mention(
    tools: AgentToolsProtocol,
    msg: PlatformMessage,
    fallback: str,
) -> str:
    """Return the sender's Band handle when it is available in participants."""
    for participant in tools.participants:
        sender_id = _field(participant, "id")
        if sender_id != msg.sender_id:
            continue
        handle = _field(participant, "handle")
        if handle:
            return handle
    return fallback


def _field(entity: Any, name: str) -> str:
    if isinstance(entity, dict):
        value = entity.get(name)
    else:
        value = getattr(entity, name, None)
    return value or ""


def _normalize(value: str) -> str:
    return value.strip().lower().lstrip("@").replace("_", "-").replace(" ", "-")
