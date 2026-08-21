"""Image generation over GraphQL."""

import base64
import json
import urllib.error
import urllib.request

import litellm
from kante.types import Info

from llm import enums
from llm.enums import DefaultKind
from llm.errors import wrap_llm_errors
from llm.graphql.mutations.chat import resolve_model
from llm.inputs import ImageInput
from llm.models import LLMModel
from llm.types import ImageResponse

#: Ceiling on a single image request. Image models are slow, so this is longer
#: than the completion timeout, but it is still bounded.
IMAGE_TIMEOUT_SECONDS = 900

#: OpenRouter serves images through the chat-completions endpoint with an
#: `image` modality rather than through an images API, so litellm's
#: `image_generation` cannot reach it and this one provider is called directly.
OPENROUTER_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"

_OPENROUTER_PROMPT = "Create a picture of the described image. Do not ask for another input, just create the image, in a cartoon-like style: {description}"


def _generate_via_openrouter(model: LLMModel, description: str) -> str:
    """Ask OpenRouter for an image and return it as base64, without the data URI prefix."""
    request = urllib.request.Request(
        OPENROUTER_COMPLETIONS_URL,
        data=json.dumps(
            {
                "model": model.model_id,
                "messages": [{"role": "user", "content": _OPENROUTER_PROMPT.format(description=description)}],
                "modalities": ["image", "text"],
                "image_config": {"aspect_ratio": "16:9"},
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {model.provider.api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=IMAGE_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise Exception(f"OpenRouter returned {e.code} for model '{model.llm_string}': {e.read().decode('utf-8', 'replace')}") from e

    choices = result.get("choices")
    if not choices:
        raise Exception(f"OpenRouter returned no choices for model '{model.llm_string}'")

    images = choices[0]["message"].get("images")
    if not images:
        raise Exception(f"OpenRouter returned no image for model '{model.llm_string}'. The model may not support image output.")

    image_url = images[0]["image_url"]["url"]
    if image_url.startswith("data:"):
        return image_url.split(",")[-1]

    with urllib.request.urlopen(image_url, timeout=IMAGE_TIMEOUT_SECONDS) as image_response:
        return base64.b64encode(image_response.read()).decode("utf-8")


def generate_image(info: Info, input: ImageInput) -> ImageResponse:
    """Generate an image from a text description."""
    image_model = resolve_model(info, input.model, DefaultKind.IMAGE_GENERATION)

    if not image_model.is_available:
        raise Exception(f"Model '{image_model.llm_string}' is not currently available")

    if image_model.provider.kind == enums.ProviderKind.OPENROUTER:
        return ImageResponse(image=_generate_via_openrouter(image_model, input.description))

    with wrap_llm_errors(image_model):
        response = litellm.image_generation(
            model=image_model.llm_string,
            prompt=input.description,
            api_base=image_model.provider.api_base,
            api_key=image_model.provider.api_key,
            timeout=IMAGE_TIMEOUT_SECONDS,
        )

    return ImageResponse(image=response.data[0]["b64_json"])
