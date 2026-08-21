"""Chat completions over GraphQL.

The serialization helpers live here and are imported by the image mutation
rather than copied into it; they used to be duplicated verbatim across both
files, and the copy in ``image.py`` was never called.
"""

from typing import Any, Dict, List, Optional

import litellm
from kante.types import Info

from llm import manager, models
from llm.enums import DefaultKind
from llm.errors import wrap_llm_errors
from llm.inputs import ChatInput, ChatMessageInput, ToolInput
from llm.types import ChatMessage, ChatResponse, Choice, FunctionCall, ThinkingBlock, ToolCall, Usage

#: Ceiling on a single completion. Alpaka proxies upstreams it does not control,
#: so a request with no ceiling would hold a worker open indefinitely.
COMPLETION_TIMEOUT_SECONDS = 600


def _thinking_blocks(choice: Any) -> Optional[List[ThinkingBlock]]:
    """Map a choice's reasoning blocks, when the upstream returned any."""
    blocks = getattr(choice.message, "thinking_blocks", None)
    if not blocks:
        return None
    return [
        ThinkingBlock(
            type=block.get("type", "thinking"),
            thinking=block.get("thinking", ""),
            signature=block.get("signature"),
        )
        for block in blocks
    ]


def _usage(usage: Any) -> Optional[Usage]:
    """Map token accounting, including the per-modality breakdowns when present."""
    if not usage:
        return None

    def as_json(value: Any) -> Optional[Any]:
        if value is None:
            return None
        return value.model_dump() if hasattr(value, "model_dump") else value

    return Usage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        prompt_token_details=as_json(getattr(usage, "prompt_tokens_details", None)),
        completion_token_details=as_json(getattr(usage, "completion_tokens_details", None)),
    )


def to_chat_response(response: litellm.ModelResponse) -> ChatResponse:
    """Map a litellm response onto the GraphQL ``ChatResponse`` type."""
    return ChatResponse(
        id=response.id,
        object=response.object,
        created=response.created,
        model=response.model,
        system_fingerprint=getattr(response, "system_fingerprint", None),
        usage=_usage(response.usage),
        choices=[
            Choice(
                index=choice.index,
                finish_reason=choice.finish_reason,
                reasoning_content=getattr(choice.message, "reasoning_content", None),
                thinking_blocks=_thinking_blocks(choice),
                message=ChatMessage(
                    role=choice.message.role,
                    content=choice.message.content,
                    name=getattr(choice.message, "name", None),
                    tool_call_id=getattr(choice.message, "tool_call_id", None),
                    function_call=FunctionCall(
                        name=choice.message.function_call.name,
                        arguments=choice.message.function_call.arguments,
                    )
                    if getattr(choice.message, "function_call", None)
                    else None,
                    tool_calls=[
                        ToolCall(
                            id=tool_call.id,
                            type=tool_call.type,
                            function=FunctionCall(name=tool_call.function.name, arguments=tool_call.function.arguments),
                        )
                        for tool_call in getattr(choice.message, "tool_calls", None) or []
                    ]
                    or None,
                ),
            )
            for choice in response.choices
        ],
    )


def serialize_messages(messages: List[ChatMessageInput]) -> List[dict]:
    """Shape the GraphQL message inputs into the dicts litellm expects."""
    result = []
    for m in messages:
        msg: Dict[str, Any] = {
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
    """Shape the GraphQL tool inputs into the dicts litellm expects."""
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


def resolve_model(info: Info, model_id: Optional[str], kind: DefaultKind) -> models.LLMModel:
    """Resolve the requested model, or the caller's default for ``kind``.

    Scoped to the request's organization, so a bare id cannot reach another
    tenant's model.
    """
    organization = info.context.request.organization
    if model_id:
        return models.LLMModel.objects.for_organization(organization).select_related("provider").get(id=model_id)
    return manager.get_default_llm_model_for_user(info.context.request.user, organization, kind)


def generation_kwargs(input: ChatInput) -> Dict[str, Any]:
    """Collect the optional generation parameters the caller actually set.

    Omitted rather than passed as ``None``, because litellm forwards explicit
    nulls to providers that reject them.
    """
    optional = {
        "tool_choice": input.tool_choice,
        "temperature": input.temperature,
        "max_tokens": input.max_tokens,
        "top_p": input.top_p,
        "frequency_penalty": input.frequency_penalty,
        "presence_penalty": input.presence_penalty,
        "stop": input.stop,
        "n": input.n,
        "response_format": input.response_format,
    }
    return {key: value for key, value in optional.items() if value is not None}


def chat(info: Info, input: ChatInput) -> ChatResponse:
    """Send a chat message to the LLM and get a response."""
    chat_model = resolve_model(info, input.model, DefaultKind.TEXT_GENERATION)

    if not chat_model.is_available:
        raise Exception(f"Model '{chat_model.llm_string}' is not currently available")

    # Streaming is not expressible on a mutation; the REST endpoint serves it.
    with wrap_llm_errors(chat_model):
        response = litellm.completion(
            model=chat_model.llm_string,
            messages=serialize_messages(input.messages),
            tools=serialize_tools(input.tools),
            api_base=chat_model.provider.api_base,
            api_key=chat_model.provider.api_key,
            stream=False,
            timeout=COMPLETION_TIMEOUT_SECONDS,
            **generation_kwargs(input),
        )

    return to_chat_response(response)
