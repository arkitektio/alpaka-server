"""The room channel: what subscribers of a room are told about."""

import contextlib
import logging
from typing import Any, AsyncGenerator

from kante.channel import build_channel
from kante.context import WsContext
from pydantic import BaseModel, Field, ValidationError

from kammer.enums import RoomEventKind

logger = logging.getLogger(__name__)


class MessageSignal(BaseModel):
    """A room event. Carries ids only; subscribers re-fetch through the scoped managers."""

    kind: RoomEventKind = Field(RoomEventKind.MESSAGE_CREATED, description="What happened")
    #: Required, and re-checked by every subscriber. Group membership alone does
    #: not scope a subscription: strawberry's consumer fans a channel message to
    #: every listen queue of that message type (ignoring groups), and the channel
    #: name is per-*connection*, so two room subscriptions multiplexed on one
    #: websocket would otherwise cross-feed each other's events. Required rather
    #: than optional so a producer that forgets it fails loudly at validation
    #: instead of silently disabling the filter.
    room: int = Field(description="The room this happened in")
    message: int | None = Field(None, description="The message that was created, updated or finished")
    agent: int | None = Field(None, description="The agent that joined or left")


message_channel = build_channel(MessageSignal)


def room_group(room_id: int) -> str:
    """The channel group of a room. The single definition both broadcasters and listeners use."""
    return f"room_{room_id}"


#: Where a consumer's room-group refcounts live. One attribute per connection,
#: set lazily so nothing has to subclass the GraphQL consumer (``kante.router``
#: hardcodes it) to carry this state.
_GROUP_REFCOUNTS = "_kammer_room_group_refcounts"


def _ws_context(info: Any) -> WsContext:
    """The websocket context behind a subscription's ``info``."""
    context = getattr(info, "context", info)
    if not isinstance(context, WsContext):
        raise TypeError("The room subscription requires a websocket connection")
    return context


async def listen_to_room(info: Any, room_id: int) -> AsyncGenerator[MessageSignal, None]:
    """This room's events, on a connection that may be watching several rooms.

    Not ``message_channel.listen``, because both of its assumptions break as soon
    as a client multiplexes two subscriptions over one websocket -- which is what
    every Apollo-style client does by default. The channel name is per-*connection*,
    not per-subscription, so:

    * Group membership does not scope delivery. Strawberry's ``ChannelsConsumer``
      fans every channel message to all listen queues matching the message *type*
      and ignores groups entirely, so a subscriber to room A used to receive room
      B's events. We filter on ``signal.room`` here instead of trusting the group.
    * ``listen_to_channel(groups=...)`` calls ``group_discard`` on exit, so closing
      one subscription to a room removed the whole *connection* from that room and
      silenced its siblings. We own the membership and refcount it per consumer,
      discarding only when the last subscription to that room goes away.

    Delete this in favour of ``Channel.listen`` if kante ever refcounts group
    memberships per consumer itself.
    """
    consumer = _ws_context(info).consumer
    if consumer.channel_layer is None:
        raise RuntimeError("Channel layer is not available in the context")
    group = room_group(room_id)

    refcounts: dict[str, int] = getattr(consumer, _GROUP_REFCOUNTS, None)  # type: ignore[assignment]
    if refcounts is None:
        refcounts = {}
        setattr(consumer, _GROUP_REFCOUNTS, refcounts)

    # Membership first, then the count: incrementing before the await would strand
    # the count at one if group_add raised, and this connection would then never
    # discard the group. group_add is idempotent, so repeating it per subscription
    # is cheaper than reasoning about a second one that starts mid-registration.
    await consumer.channel_layer.group_add(group, consumer.channel_name)
    # No await between the read and the write, so the count cannot be lost.
    refcounts[group] = refcounts.get(group, 0) + 1
    try:
        async with consumer.listen_to_channel(message_channel.message_type, groups=()) as messages:
            async for message in messages:
                try:
                    signal = MessageSignal.model_validate(message.get("message"))
                except ValidationError:
                    logger.warning("Invalid room signal received", exc_info=True)
                    continue
                if signal.room != room_id:
                    continue
                yield signal
    finally:
        refcounts[group] = refcounts.get(group, 1) - 1
        if refcounts[group] <= 0:
            refcounts.pop(group, None)
            with contextlib.suppress(Exception):
                await consumer.channel_layer.group_discard(group, consumer.channel_name)
