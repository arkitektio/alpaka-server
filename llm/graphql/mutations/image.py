import strawberry
from typing import Optional, List
from llm.inputs import ChatMessageInput, ToolInput, ChatInput, ImageInput
from llm.types import (
    ChatResponse,
    ImageReponse,
)
import litellm
from kante.types import Info
from django.conf import settings

from llm.types import ChatResponse, Choice, ChatMessage, Usage, FunctionCall, ToolCall
from llm import models, enums, filters, inputs, manager
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


def generate_image(info: Info, input: ImageInput) -> ImageReponse:
    """Send a chat message to the LLM and get a response."""

    # Check if the model is available
    chat_model = models.LLMModel.objects.get(id=input.model) if input.model else manager.get_default_llm_model_for_user(info.context.request.user, info.context.request.organization, "image_generation")

    # type: ignore
    if not chat_model:
        raise Exception("Model not found")

    if not chat_model.is_available:
        raise Exception("Model is not available")

    if chat_model.provider.kind == enums.ProviderKind.OPENROUTER:
        import json
        import urllib.request
        import urllib.error
        import base64

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {chat_model.provider.api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": chat_model.model_id,
            "messages": [{"role": "user", "content": f"Create a picture o the described image. DO NOT ASK for another input just created the image, go for a cartoon like style: {input.description}"}],
            "modalities": ["image", "text"],
            "image_config": {"aspect_ratio": "16:9"},
        }

        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)

        print("Starting to generate")
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode("utf-8"))
                print("Result", result)
                if result.get("choices"):
                    message = result["choices"][0]["message"]

                    if message.get("images"):
                        image_url = message["images"][0]["image_url"]["url"]

                        if image_url.startswith("data:"):
                            return ImageReponse(image=image_url.split(",")[-1])
                        else:
                            with urllib.request.urlopen(image_url) as img_response:
                                img_data = img_response.read()
                                b64_img = base64.b64encode(img_data).decode("utf-8")
                                return ImageReponse(image=b64_img)

                    raise Exception("No images returned in response")
                else:
                    raise Exception("No choices in response")

        except urllib.error.HTTPError as e:
            raise Exception(f"OpenRouter API Error: {e.read().decode('utf-8')}")

    # Disallow streaming in this endpoint
    response = litellm.image_generation(
        model=chat_model.llm_string,
        prompt=input.description,
        api_base=chat_model.provider.api_base,
        api_key=chat_model.provider.api_key,
    )

    answer = response.data[0]["b64_json"]

    return ImageReponse(image=answer)
