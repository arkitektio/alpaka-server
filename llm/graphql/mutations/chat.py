import strawberry
from typing import Optional, List
from llm.inputs import ChatMessageInput, ToolInput, ChatInput
from llm.types import (
    ChatResponse,
)
import litellm
from kante.types import Info
from django.conf import settings

from llm.types import ChatResponse, Choice, ChatMessage, Usage, FunctionCall, ToolCall
from llm import models, enums, filters, inputs
from typing import List


def to_chat_response(response: litellm.ModelResponse) -> ChatResponse:
    usage = response.usage
    choices = response.choices

    return ChatResponse(
        id=response.id,
        object=response.object,
        created=response.created,
        model=response.model,
        usage=Usage(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
        )
        if usage
        else None,
        choices=[
            Choice(
                index=c.index,
                finish_reason=c.finish_reason,
                message=ChatMessage(
                    role=c.message.role,
                    content=c.message.content,
                    name=getattr(c.message, "name", None),
                    tool_call_id=getattr(c.message, "tool_call_id", None),
                    function_call=FunctionCall(
                        name=c.message.function_call.name,
                        arguments=c.message.function_call.arguments,
                    )
                    if getattr(c.message, "function_call", None)
                    else None,
                    tool_calls=[ToolCall(id=tc.id, type=tc.type, function=FunctionCall(name=tc.function.name, arguments=tc.function.arguments)) for tc in getattr(c.message, "tool_calls", []) or []] if hasattr(c.message, "tool_calls") else None,
                ),
            )
            for c in choices
        ],
    )


def serialize_messages(messages: List[ChatMessageInput]) -> List[dict]:
    """"""
    result = []
    for m in messages:
        msg = {
            "role": m.role.value,
            "content": m.content,
            "name": m.name,
            "tool_call_id": m.tool_call_id,
        }
        if m.function_call:
            msg["function_call"] = {
                "name": m.function_call.name,
                "arguments": m.function_call.arguments,
            }
        if m.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type.value,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in m.tool_calls
            ]
        result.append(msg)
    return result


def serialize_tools(tools: Optional[List[ToolInput]]) -> Optional[List[dict]]:
    if not tools:
        return None
    return [
        {
            "type": t.type.value,
            "function": {
                "name": t.function.name,
                "description": t.function.description,
                "parameters": t.function.parameters,
            },
        }
        for t in tools
    ]


def chat(info: Info, input: ChatInput) -> ChatResponse:
    """Send a chat message to the LLM and get a response."""

    serialized_messages = serialize_messages(input.messages)
    serialized_tools = serialize_tools(input.tools)
    
    # Check if the model is available
    chat_model = models.LLMModel.objects.get(id=input.model)
    
    # type: ignore
    if not chat_model:
        raise Exception("Model not found")
    

    if not chat_model.is_available:
        raise Exception("Model is not available")

    # Disallow streaming in this endpoint
    response = litellm.completion(
        model=chat_model.llm_string,
        messages=serialized_messages,
        tools=serialized_tools,
        api_base=settings.OLLAMA_URL,
        stream=False,
    )

    return to_chat_response(response)
