"""Live room events."""

import logging
from typing import AsyncGenerator

import strawberry
from kante.types import Info

from kammer import models, types
from kammer.channels import MessageSignal, listen_to_room, message_channel, room_group
from kammer.enums import RoomEventKind

logger = logging.getLogger(__name__)


@strawberry.type(description="Something that happened in a room")
class RoomEvent:
    """A message created, updated or finished, or an agent joining or leaving."""

    kind: RoomEventKind
    message: types.Message | None = strawberry.field(default=None, description="The message, for MESSAGE_* events")
    join: types.Agent | None = strawberry.field(default=None, description="The agent that joined, for JOIN events")
    leave: types.Agent | None = strawberry.field(default=None, description="The agent that left, for LEAVE events")


async def room(
    self,
    info: Info,
    room: strawberry.ID,
    agent_id: strawberry.ID,
    filter_own: bool = True,
) -> AsyncGenerator[RoomEvent, None]:
    """Join a room and receive its events as they happen."""
    # Scoped, so a subscriber cannot listen in on another organization's room.
    room_model = await models.Room.objects.for_organization(info.context.request.organization).aget(id=room)

    agent, _ = await models.Agent.objects.for_write().aget_or_create(
        user=info.context.request.user,
        client=info.context.request.client,
        room=room_model,
        name=agent_id,
    )
    group = room_group(room_model.id)

    # Announced before listen() registers this subscriber with the group, so
    # the joiner never sees its own JOIN.
    await message_channel.abroadcast(MessageSignal(kind=RoomEventKind.JOIN, room=room_model.id, agent=agent.id), [group])
    try:
        # listen_to_room, not message_channel.listen: it scopes the events to this
        # room and refcounts the group membership, so several room subscriptions can
        # share one websocket. See kammer.channels.listen_to_room.
        async for signal in listen_to_room(info, room_model.id):
            if signal.kind in (RoomEventKind.JOIN, RoomEventKind.LEAVE):
                if not signal.agent or signal.agent == agent.id:
                    continue
                try:
                    other = await models.Agent.objects.for_write().aget(id=signal.agent, room=room_model)
                except models.Agent.DoesNotExist:
                    continue
                if signal.kind == RoomEventKind.JOIN:
                    yield RoomEvent(kind=signal.kind, join=other)
                else:
                    yield RoomEvent(kind=signal.kind, leave=other)
                continue

            if not signal.message:
                continue

            try:
                # The signal was matched to this room above, and the room was scoped
                # to the caller's organization, so this id is safe to fetch.
                message = await models.Message.objects.for_write().select_related("agent").aget(id=signal.message, room=room_model)
            except models.Message.DoesNotExist:
                # Deleted between the broadcast and here (deleting a room cascades to
                # its messages). Skip it, like the JOIN/LEAVE branch does -- letting it
                # raise would tear down the whole subscription.
                continue
            if filter_own and message.agent_id == agent.id:
                continue

            yield RoomEvent(kind=signal.kind, message=message)
    finally:
        # Runs on unsubscribe and on disconnect. Awaiting inside finally is
        # legal for an async generator as long as nothing is yielded; guarded so
        # a dying event loop cannot mask the exit.
        try:
            await message_channel.abroadcast(MessageSignal(kind=RoomEventKind.LEAVE, room=room_model.id, agent=agent.id), [group])
        except BaseException:
            logger.debug("Could not broadcast leave for agent %s", agent.id, exc_info=True)
