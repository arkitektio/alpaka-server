import strawberry
from typing import Optional, List
from enum import Enum

# --- ENUMS ---


@strawberry.enum(description="The type of the message sender")
class Role(str, Enum):
    """The role of the message sender in a chat conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    FUNCTION = "function"


@strawberry.enum(description="The type of the tool")
class ToolType(str, Enum):
    """The type of the tool used in a chat conversation."""

    FUNCTION = "function"  # Currently the only one LiteLLM supports


@strawberry.enum(description="The type of the thinking block")
class ThinkingBlockType(str, Enum):
    """The type of the thinking block in a chat conversation."""

    THINKING = "thinking"