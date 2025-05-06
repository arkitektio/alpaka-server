import strawberry
from typing import Optional, List
from strawberry import scalars
from llm import enums


@strawberry.input(description="A large language model to change with")
class ProviderInput:
    """A large language model provider"""

    name: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    additional_config: Optional[scalars.JSON] = None


@strawberry.input(description="A large language model function defintion")
class FunctionDefinitionInput:
    """A function definition for a large language model"""

    name: str
    description: Optional[str] = None
    parameters: Optional[scalars.JSON] = None  # JSON Schema object


@strawberry.input(description="A large language model function call")
class ToolInput:
    """A function call for a large language model"""

    type: enums.ToolType = enums.ToolType.FUNCTION
    function: FunctionDefinitionInput


# --- CHAT INPUT MESSAGES ---


@strawberry.input(description="A function call input")
class FunctionCallInput:
    """A function call input for a large language model"""

    name: str
    arguments: str


@strawberry.input(description="A tool call input")
class ToolCallInput:
    """A tool call input for a large language model"""

    id: str
    function: FunctionCallInput
    type: enums.ToolType


@strawberry.input(description="A chat message input")
class ChatMessageInput:
    """A chat message input for a large language model"""

    role: enums.Role
    content: Optional[str] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    function_call: Optional[FunctionCallInput] = None
    tool_calls: Optional[List[ToolCallInput]] = None


@strawberry.input(description="A chat message input")
class ChatInput:
    """A chat message input for a large language model"""

    model: strawberry.ID
    messages: List[ChatMessageInput]
    tools: Optional[List[ToolInput]] = None
    temperature: Optional[float] = None
