"""Creating rooms and posting messages into them.

Agents live on clients, never on the server: nothing here calls an LLM. A
client that streams a reply (from the ``chat`` mutation or the OpenAI-compatible
REST endpoint) forwards it into a room with ``startMessage`` /
``appendMessage`` / ``finishMessage`` — or, with far less overhead per token,
over the websocket in :mod:`kammer.consumers`. Both share :mod:`kammer.streaming`.
"""

import logging
from typing import List

import strawberry
from kante.types import Info

from kammer import models, streaming, types
from kammer.enums import RoomEventKind
from vector import inputs as vector_inputs

logger = logging.getLogger(__name__)


def _owned(info: Info, message_id: strawberry.ID) -> models.Message:
    request = info.context.request
    return streaming.owned_streaming_message(organization=request.organization, user=request.user, client=request.client, message_id=message_id)


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
        room.contextual_structures.add(*streaming.attach_structures(input.talking_about))

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
    attach_structures: List[vector_inputs.StructureInput] | None = None


def send(info: Info, input: SendMessageInput) -> types.Message:
    """Post a complete message into a room as the calling agent."""
    request = info.context.request
    room, agent = streaming.room_and_agent(organization=request.organization, user=request.user, client=request.client, room_id=input.room, agent_name=input.agent_id)

    message = models.Message.objects.for_write().create(
        agent=agent,
        room=room,
        text=input.text,
        is_reply_to=streaming.parent_message(organization=request.organization, room=room, parent_id=input.parent),
    )

    if input.attach_structures:
        message.attached_structures.add(*streaming.attach_structures(input.attach_structures))

    return message


@strawberry.input(description="Open a message that text will be streamed into")
class StartMessageInput:
    """The room to stream into, and the agent doing it."""

    room: strawberry.ID
    agent_id: str
    parent: strawberry.ID | None = None
    text: str = ""


def start_message(info: Info, input: StartMessageInput) -> types.Message:
    """Open a streaming message. Only the same user and client can append to or finish it."""
    request = info.context.request
    return streaming.open_message(
        organization=request.organization,
        user=request.user,
        client=request.client,
        room_id=input.room,
        agent_name=input.agent_id,
        parent_id=input.parent,
        text=input.text,
    )


@strawberry.input(description="Text to append to a streaming message")
class AppendMessageInput:
    """A delta for a message that is still streaming."""

    message: strawberry.ID
    delta: str


def append_message(info: Info, input: AppendMessageInput) -> types.Message:
    """Append a delta to a streaming message and tell the room."""
    message = _owned(info, input.message)
    if streaming.append_delta(message.id, input.delta) == 0:
        # Lost the race with a concurrent finish.
        raise ValueError("This message is finished and cannot be modified")
    message.refresh_from_db(fields=["text"])
    streaming.announce(RoomEventKind.MESSAGE_UPDATED, message)
    return message


@strawberry.input(description="Close a streaming message")
class FinishMessageInput:
    """The message to finish, optionally with its authoritative final text."""

    message: strawberry.ID
    text: str | None = None
    attach_structures: List[vector_inputs.StructureInput] | None = None


def finish_message(info: Info, input: FinishMessageInput) -> types.Message:
    """Mark a streaming message as complete, optionally replacing its text with the final version."""
    message = streaming.finish_message(_owned(info, input.message), text=input.text, structures=input.attach_structures)
    streaming.announce(RoomEventKind.MESSAGE_FINISHED, message)
    return message
