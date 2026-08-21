"""Creating rooms and posting messages into them."""

import logging
from typing import List

import strawberry
from kante.types import Info

from kammer import models, types
from vector import inputs as vector_inputs

logger = logging.getLogger(__name__)


def _attach_structures(structures: List[vector_inputs.StructureInput]) -> List[models.Structure]:
    """Resolve (or create) the structure rows for a list of structure references."""
    resolved = []
    for structure in structures:
        row, _ = models.Structure.objects.get_or_create(object=structure.object, identifier=structure.identifier)
        resolved.append(row)
    return resolved


@strawberry.input(description="The room to create")
class CreateRoomInput:
    """The room to open, and what it is about."""

    description: str | None = None
    title: str | None = None
    talking_about: List[vector_inputs.StructureInput] | None = None


def create_room(info: Info, input: CreateRoomInput) -> types.Room:
    """Create a new room in the caller's organization."""
    room = models.Room.objects.for_write().create(
        title=input.title or "Untitled",
        description=input.description or "No description",
        creator=info.context.request.user,
        organization=info.context.request.organization,
    )

    if input.talking_about:
        room.contextual_structures.add(*_attach_structures(input.talking_about))

    return room


@strawberry.input(description="The room to delete")
class DeleteRoomInput:
    """The room to remove, along with its messages."""

    id: strawberry.ID


def delete_room(info: Info, input: DeleteRoomInput) -> strawberry.ID:
    """Delete a room belonging to the caller's organization."""
    room = models.Room.objects.for_organization(info.context.request.organization).get(id=input.id)
    room.delete()
    return input.id


@strawberry.input(description="The message to send")
class SendMessageInput:
    """The message to post, and the room to post it into."""

    room: strawberry.ID
    agent_id: str
    text: str
    parent: strawberry.ID | None = None
    notify: bool | None = None
    attach_structures: List[vector_inputs.StructureInput] | None = None


def send(info: Info, input: SendMessageInput) -> types.Message:
    """Post a message into a room as the calling agent."""
    # Scoped first, so a caller cannot post into another organization's room.
    room = models.Room.objects.for_organization(info.context.request.organization).get(id=input.room)

    agent, _ = models.Agent.objects.for_write().get_or_create(
        user=info.context.request.user,
        client=info.context.request.client,
        room=room,
        name=input.agent_id,
    )

    message = models.Message.objects.for_write().create(
        agent=agent,
        room=room,
        text=input.text,
        is_reply_to_id=input.parent,
    )

    if input.attach_structures:
        message.attached_structures.add(*_attach_structures(input.attach_structures))

    return message
