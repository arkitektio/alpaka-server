from typing import AsyncGenerator

import strawberry
import strawberry_django
from ekke.types import Info
from kammer import models, scalars, types
from kammer.channels import message_listen


@strawberry.type
class RoomEvent:
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
    """Join and subscribe to message sent to the given rooms."""
    print("FUUUUCK THISS man", room)

    agent, _ = await models.Agent.objects.aget_or_create(
        user=info.context.request.user,
        app=info.context.request.app,
        room_id=room,
        name=agent_id,
    )

    async for message in message_listen(info, ["room_" + str(room)]):
        print("Received message", message)
        message_model = await models.Message.objects.prefetch_related("agent").aget(
            id=message
        )
        if filter_own and message_model.agent == agent:
            continue

        yield RoomEvent(message=message_model)
