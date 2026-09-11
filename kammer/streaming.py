"""Opening, growing and closing streamed messages.

The one implementation behind both front doors: the GraphQL mutations
(``startMessage`` / ``appendMessage`` / ``finishMessage``) and the websocket
in :mod:`kammer.consumers`. Everything here is sync ORM; async callers wrap it
in ``sync_to_async``.

Agents live on clients. Nothing here calls an LLM; the client forwards the
tokens it received and the server stores and fans them out.
"""

from typing import Iterable, Optional

from django.db.models import F, TextField, Value
from django.db.models.functions import Concat

from kammer import models
from kammer.channels import MessageSignal, message_channel, room_group
from kammer.enums import RoomEventKind


def attach_structures(structures: Iterable) -> list[models.Structure]:
    """Resolve (or create) the structure rows for a list of structure references."""
    resolved = []
    for structure in structures:
        row, _ = models.Structure.objects.get_or_create(object=structure.object, identifier=structure.identifier)
        resolved.append(row)
    return resolved


def room_and_agent(*, organization, user, client, room_id, agent_name: str) -> tuple[models.Room, models.Agent]:
    """The scoped room, and the user+client's agent in it (created on first use)."""
    # Scoped first, so a caller cannot post into another organization's room.
    room = models.Room.objects.for_organization(organization).get(id=room_id)
    agent, _ = models.Agent.objects.for_write().get_or_create(user=user, client=client, room=room, name=agent_name)
    return room, agent


def parent_message(*, organization, room: models.Room, parent_id) -> Optional[models.Message]:
    """The message being replied to, which must live in the same room."""
    if parent_id is None:
        return None
    return models.Message.objects.for_organization(organization).get(id=parent_id, room=room)


def open_message(*, organization, user, client, room_id, agent_name: str, parent_id=None, text: str = "") -> models.Message:
    """Create a message with ``is_streaming=True``. The post_save receiver announces it."""
    room, agent = room_and_agent(organization=organization, user=user, client=client, room_id=room_id, agent_name=agent_name)
    return models.Message.objects.for_write().create(
        agent=agent,
        room=room,
        text=text,
        is_streaming=True,
        is_reply_to=parent_message(organization=organization, room=room, parent_id=parent_id),
    )


def owned_streaming_message(*, organization, user, client, message_id) -> models.Message:
    """The message, provided it is in ``organization``, still streaming, and started by ``user``+``client``.

    Scoped read first: another organization gets a plain "does not exist",
    never a permission error about a row it cannot see.
    """
    message = models.Message.objects.for_organization(organization).select_related("agent").get(id=message_id)
    if message.agent.user_id != user.id or message.agent.client_id != client.id:
        raise PermissionError("Only the agent that started this message may write to it")
    if not message.is_streaming:
        raise ValueError("This message is finished and cannot be modified")
    return message


def append_delta(message_id: int, delta: str) -> int:
    """Append ``delta`` server-side in one atomic UPDATE. Returns rows updated (0 if finished meanwhile)."""
    return models.Message.objects.for_write().filter(id=message_id, is_streaming=True).update(text=Concat(F("text"), Value(delta), output_field=TextField()))


def finish_message(message: models.Message, *, text: Optional[str] = None, structures: Optional[Iterable] = None) -> models.Message:
    """Close a streaming message, optionally replacing its text with the final version."""
    message.is_streaming = False
    fields = ["is_streaming"]
    if text is not None:
        message.text = text
        fields.append("text")
    # Only the override touches ``text``: the instance may predate appends made
    # by atomic UPDATEs, and saving its stale copy would wipe them.
    # One history row with the final text; appends deliberately leave none.
    message.save(update_fields=fields)
    message.refresh_from_db(fields=["text"])
    if structures:
        message.attached_structures.add(*attach_structures(structures))
    return message


def signal_for(kind: RoomEventKind, message: models.Message) -> tuple[MessageSignal, list[str]]:
    """The channel payload and group announcing ``kind`` for ``message``."""
    return MessageSignal(kind=kind, room=message.room_id, message=message.id), [room_group(message.room_id)]


def announce(kind: RoomEventKind, message: models.Message) -> None:
    """Tell the room's subscribers (sync)."""
    message_channel.broadcast(*signal_for(kind, message))
