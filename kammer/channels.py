"""The room channel: what subscribers of a room are told about."""

from kante.channel import build_channel
from pydantic import BaseModel, Field

from kammer.enums import RoomEventKind


class MessageSignal(BaseModel):
    """A room event. Carries ids only; subscribers re-fetch through the scoped managers."""

    kind: RoomEventKind = Field(RoomEventKind.MESSAGE_CREATED, description="What happened")
    message: int | None = Field(None, description="The message that was created, updated or finished")
    agent: int | None = Field(None, description="The agent that joined or left")


message_channel = build_channel(MessageSignal)


def room_group(room_id: int) -> str:
    """The channel group of a room. The single definition both broadcasters and listeners use."""
    return f"room_{room_id}"
