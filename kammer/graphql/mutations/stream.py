import hashlib
import json
import logging
from typing import Any, Dict, List, Tuple

import strawberry
import strawberry_django
from ekke.types import Info
from kammer import enums, inputs, models, scalars, types

logger = logging.getLogger(__name__)
from django.contrib.auth import get_user_model
from kammer import inputs
from livekit import api
from livekit.protocol.room import ListRoomsRequest
from django.conf import settings


@strawberry.input
class CreateStreamInput:
    room: strawberry.ID
    title: str | None = None
    agent_id: str | None = None


async def create_video_stream(info: Info, input: CreateStreamInput) -> types.Stream:

    room = await models.Room.objects.aget(id=input.room)

    agent, _ = await models.Agent.objects.aget_or_create(
        user=info.context.request.user,
        app=info.context.request.app,
        room=room,
        name=input.agent_id,
    )

    # Check if room exists.

    print(settings.LIVEKIT)

    lkapi = api.LiveKitAPI(
        url=settings.LIVEKIT["API_URL"],
        api_key=settings.LIVEKIT["API_KEY"],
        api_secret=settings.LIVEKIT["API_SECRET"],
    )

    reponse = await lkapi.room.list_rooms(
        ListRoomsRequest(names=[room.streamlit_room_id])
    )

    if reponse.rooms:
        room_info = reponse.rooms[0]
        print(room_info)

    else:
        room_info = await lkapi.room.create_room(
            api.CreateRoomRequest(name=room.streamlit_room_id),
        )

    token = (
        api.AccessToken(
            api_key=settings.LIVEKIT["API_KEY"],
            api_secret=settings.LIVEKIT["API_SECRET"],
        )
        .with_identity("agent-" + str(agent.id))
        .with_name("agent-" + agent.name)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room.streamlit_room_id,
            )
        )
        .to_jwt()
    )

    print(token)

    exp, _ = await models.Stream.objects.aupdate_or_create(
        title=input.title or "default", agent=agent, defaults=dict(token=token)
    )

    return exp


@strawberry.input
class JoinStreamInput:
    id: strawberry.ID


async def join_video_stream(info: Info, input: JoinStreamInput) -> types.Stream:
    creator = info.context.request.user

    room = await models.Room.objects.aget(id=input.room)

    agent, _ = await models.Agent.objects.get_or_create(
        user=info.context.request.user,
        app=info.context.request.app,
        room=room,
        name=input.agent_id,
    )

    token = (
        api.AccessToken()
        .with_identity(agent.id)
        .with_name(agent.name)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room.streamlit_room_id,
            )
        )
        .to_jwt()
    )

    exp = await models.Stream.objects.acreate(
        title=input.title or "Untitled", agent=agent, token=token
    )

    return exp


@strawberry.input
class LeaveStreamInput:
    id: strawberry.ID


async def leave_video_stream(info: Info, input: LeaveStreamInput) -> types.Stream:

    exp = await models.Stream.objects.aget(id=input.id)

    i

    await exp.delete()

    return exp


@strawberry.input
class StructureInput:
    object: strawberry.ID
    identifier: str


@strawberry.input
class SendMessageInput:
    room: strawberry.ID
    agent_id: str
    text: str
    parent: strawberry.ID | None = None
    notify: bool | None = None
    attach_structures: List[StructureInput] | None = None


def send(info: Info, input: SendMessageInput) -> types.Message:

    agent, _ = models.Agent.objects.get_or_create(
        user=info.context.request.user,
        app=info.context.request.app,
        room_id=input.room,
        name=input.agent_id,
    )

    message = models.Message.objects.create(agent=agent, text=input.text)
    if input.attach_structures:
        for structure in input.attach_structures:
            structure, _ = models.Structure.objects.get_or_create(
                object=structure.object, identifier=structure.identifier
            )
            message.attached_structures.add(structure)

    return message
