import strawberry
from typing import Optional, List
from strawberry.types import Info
from llm import models, enums, filters
import strawberry_django
from strawberry import scalars

# --- Strawberry types ---

# --- RETURN TYPES ---


@strawberry.type(description="The type of the tool")
class FunctionCall:
    """A function call for a large language model"""

    name: str
    arguments: str


@strawberry.type(description="A function definition for a large language model")
class ToolCall:
    """A function call for a large language model"""

    id: str
    type: enums.ToolType
    function: FunctionCall


@strawberry.type
class ChatMessage:
    """A chat message input for a large language model"""

    role: enums.Role
    content: Optional[str]
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    function_call: Optional[FunctionCall] = None
    tool_calls: Optional[List[ToolCall]] = None
    
    
    
    
@strawberry.type
class ThinkingBlock:
    
    type: enums.ThinkingBlockType
    thinking: str
    signature: Optional[str] = None


@strawberry.type
class Choice:
    """A choice in the chat response"""

    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None
    thinking_blocks: Optional[List[ThinkingBlock]] = None
    reasoning_content= Optional[str] = None


@strawberry.type
class Usage:
    """The usage of the chat response"""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_token_details: Optional[scalars.JSON] = None
    completion_token_details: Optional[scalars.JSON] = None


@strawberry.type
class ChatResponse:
    """A chat response from a large language model"""

    id: str
    object: str
    system_fingerprint: str | None = None
    created: int
    model: str
    choices: List[Choice]
    usage: Optional[Usage]


@strawberry_django.type(models.LLMModel, description="A LLM model to chage with", filters=filters.LLMModelFilter, pagination=True)
class LLMModel:
    """A large language model"""

    id: strawberry.ID
    model_id: str
    label: str


@strawberry_django.type(models.Provider, description="A provider of LLMs", filters=filters.ProviderFilter, pagination=True)
class Provider:
    """A provider of LLMs"""

    id: str
    name: str
    api_key: str
    api_base: str
    additional_config: scalars.JSON
    models: List[LLMModel]
