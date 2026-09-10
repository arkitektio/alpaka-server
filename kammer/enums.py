from enum import Enum

import strawberry


@strawberry.enum(description="What happened in a room")
class RoomEventKind(str, Enum):
    """The kind of a room event.

    ``MESSAGE_*`` events carry the message; ``JOIN``/``LEAVE`` carry the agent.
    """

    MESSAGE_CREATED = "MESSAGE_CREATED"
    MESSAGE_UPDATED = "MESSAGE_UPDATED"
    MESSAGE_FINISHED = "MESSAGE_FINISHED"
    JOIN = "JOIN"
    LEAVE = "LEAVE"
