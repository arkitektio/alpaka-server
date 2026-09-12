import decimal

import strawberry
from typing import Optional, List
from strawberry import scalars
from llm import enums


@strawberry.input(description="A large language model to change with")
class ProviderInput:
    """A large language model provider"""

    description: Optional[str] = None
    name: Optional[str] = None
    kind: enums.ProviderKind
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


@strawberry.input(description="A chat completion request")
class ChatInput:
    """A chat completion request for a large language model.

    The optional generation parameters mirror those the OpenAI-compatible REST
    endpoint accepts, so the two front doors take the same request.
    """

    messages: List[ChatMessageInput]
    model: strawberry.ID | None = None
    tools: Optional[List[ToolInput]] = None
    tool_choice: Optional[scalars.JSON] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    stop: Optional[List[str]] = None
    n: Optional[int] = None
    response_format: Optional[scalars.JSON] = None


@strawberry.input(description="The image")
class ImageInput:
    model: strawberry.ID | None = None
    description: str


@strawberry.input(description="The input for using a model for a specific task")
class UseModelForInput:
    """The model to register, and the task to register it against."""

    model: strawberry.ID
    kind: enums.DefaultKind


@strawberry.input(description="A budget to create")
class CreateBudgetInput:
    """A new cap on LLM consumption. Applies to the whole organization unless narrowed to a user and/or a model."""

    user: Optional[strawberry.ID] = None
    model: Optional[strawberry.ID] = None
    period: enums.BudgetPeriod = enums.BudgetPeriod.MONTH
    limit_tokens: Optional[int] = None
    limit_cost: Optional[decimal.Decimal] = None
    hard: bool = True


@strawberry.input(description="Changes to a budget; omitted fields are left as they are, explicit nulls clear a limit")
class UpdateBudgetInput:
    """A partial update of a budget."""

    id: strawberry.ID
    period: Optional[enums.BudgetPeriod] = strawberry.UNSET
    limit_tokens: Optional[int] = strawberry.UNSET
    limit_cost: Optional[decimal.Decimal] = strawberry.UNSET
    hard: Optional[bool] = strawberry.UNSET


@strawberry.input(description="The budget to delete")
class DeleteBudgetInput:
    """The budget to remove."""

    id: strawberry.ID
