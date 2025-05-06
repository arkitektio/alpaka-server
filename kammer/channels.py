from kante.channel import build_channel
from pydantic import BaseModel, Field


class MessageSignal(BaseModel):
    message: int | None = Field(None, description="The message that was created.")



message_channel = build_channel(MessageSignal)
