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


@strawberry.input
class CreateRoomInput:
    description: str | None = None
    title: str | None = None


def create_room(info: Info, input: CreateRoomInput) -> types.Room:
    creator = info.context.request.user

    exp = models.Room.objects.create(
        title=input.title or "Untitled",
        description=input.description or "No description",
    )

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
