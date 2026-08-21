"""Live room events."""

import logging
from typing import AsyncGenerator

import strawberry
from kante.types import Info

from kammer import models, types
from kammer.channels import message_channel

logger = logging.getLogger(__name__)


@strawberry.type(description="Something that happened in a room")
class RoomEvent:
    """A message posted, or an agent joining or leaving."""

    message: types.Message | None = None
    join: types.Agent | None = None
    leave: types.Agent | None = None


async def room(
    self,
    info: Info,
    room: strawberry.ID,
    agent_id: strawberry.ID,
    filter_own: bool = True,
) -> AsyncGenerator[RoomEvent, None]:
    """Join and subscribe to messages sent to the given room."""
    # Scoped, so a subscriber cannot listen in on another organization's room.
    room_model = await models.Room.objects.for_organization(info.context.request.organization).aget(id=room)

    agent, _ = await models.Agent.objects.for_write().aget_or_create(
        user=info.context.request.user,
        client=info.context.request.client,
        room=room_model,
        name=agent_id,
    )

    async for signal in message_channel.listen(info.context, [f"room_{room_model.id}"]):
        if not signal.message:
            continue

        # The channel is per-room and the room was scoped above, so every id
        # arriving here already belongs to the caller's organization.
        message = await models.Message.objects.for_write().select_related("agent").aget(id=signal.message)
        if filter_own and message.agent_id == agent.id:
            continue

        yield RoomEvent(message=message)
