"""
OpenAI-compliant API views using LiteLLM.

This module provides OpenAI-compatible REST API endpoints for:
- /v1/models - List available models
- /v1/chat/completions - Chat completions (with streaming support)
- /v1/completions - Text completions (legacy)
- /v1/embeddings - Text embeddings

All endpoints are wrapped with authentication and access the correct
model/tool parameters from the database.
"""

import json
import time
from typing import Optional, AsyncGenerator, Union, Tuple
from django.http import JsonResponse, StreamingHttpResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from authentikate.utils import authenticate_header_or_none
from authentikate.expand import (
    aexpand_user_from_token,
    aexpand_client_from_token,
    aexpand_organization_from_token,
)
from authentikate.models import User, Organization
import logging
import litellm
from asgiref.sync import sync_to_async
from llm import models as llm_models
from llm.manager import get_default_llm_model_for_user

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    pass


class ModelNotFoundError(Exception):
    """Raised when a requested model is not found."""

    pass


async def authenticate_request(request: HttpRequest) -> Tuple[User, object, Organization]:
    """
    Authenticate a request using JWT token from headers.

    Returns:
        tuple: (user, client, organization) if authenticated

    Raises:
        AuthenticationError: If authentication fails
    """
    token = authenticate_header_or_none(request.headers)
    if not token:
        raise AuthenticationError("Missing or invalid authentication token")

    try:
        user = await aexpand_user_from_token(token)
        client = await aexpand_client_from_token(token)
        organization = await aexpand_organization_from_token(token)
        return user, client, organization
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        raise AuthenticationError(f"Authentication failed: {str(e)}")


def create_openai_error_response(
    message: str,
    error_type: str = "invalid_request_error",
    param: Optional[str] = None,
    code: Optional[str] = None,
    status: int = 400,
) -> JsonResponse:
    """Create an OpenAI-compatible error response."""
    error_body = {
        "error": {
            "message": message,
            "type": error_type,
            "param": param,
            "code": code,
        }
    }
    return JsonResponse(error_body, status=status)


class DefaultModelNotConfiguredError(Exception):
    """Raised when a default model is requested but not configured."""

    pass


@sync_to_async
def get_model_by_id_or_name(model_identifier: str, organization: Organization, user: Optional[User] = None) -> Optional[llm_models.LLMModel]:
    """
    Get a model by its ID or model_id string.

    Supports special "alpaka/default" syntax patterns:
    - "alpaka/default" - Uses default text_generation model
    - "alpaka/default-chat" - Uses default text_generation model
    - "alpaka/default-embedding" - Uses default embedding model

    Args:
        model_identifier: Either a database ID, model_id string, or special pattern
        organization: The organization to filter by
        user: The user (required for default model lookups)

    Returns:
        LLMModel instance or None

    Raises:
        DefaultModelNotConfiguredError: When alpaka/default is used but no default is set
    """
    # Handle special "alpaka/default" patterns
    if model_identifier.startswith("alpaka/default"):
        if user is None:
            raise DefaultModelNotConfiguredError("User context required for default model lookup")

        # Parse the default type
        suffix = model_identifier.replace("alpaka/default", "")
        kind: Optional[str] = None

        if suffix in ("", "-chat", "-text"):
            kind = "text_generation"
        elif suffix == "-embedding":
            kind = "embedding"

        if kind is not None:
            try:
                return get_default_llm_model_for_user(user, organization, kind)
            except llm_models.DefaultUse.DoesNotExist:
                raise DefaultModelNotConfiguredError(f"No default model configured for '{kind}'. Please configure a default model for your user/organization.")

    # First try to get by database ID
    try:
        return llm_models.LLMModel.objects.select_related("provider").get(id=model_identifier, provider__organization=organization)
    except (llm_models.LLMModel.DoesNotExist, ValueError):
        pass

    # Then try by model_id
    try:
        return llm_models.LLMModel.objects.select_related("provider").filter(model_id=model_identifier, provider__organization=organization).first()
    except Exception:
        pass

    # Finally try by llm_string pattern (provider/model)
    try:
        if "/" in model_identifier:
            provider_name, model_id = model_identifier.split("/", 1)
            return llm_models.LLMModel.objects.select_related("provider").get(provider__name=provider_name, model_id=model_id, provider__organization=organization)
    except llm_models.LLMModel.DoesNotExist:
        pass

    return None


@sync_to_async
def get_all_models_for_organization(organization: Organization) -> list[llm_models.LLMModel]:
    """Get all available models for an organization."""
    return list(llm_models.LLMModel.objects.select_related("provider").filter(provider__organization=organization).all())


@sync_to_async
def get_default_model(user: User, organization: Organization, kind: str) -> Optional[llm_models.LLMModel]:
    """Get the default model for a user and organization."""
    try:
        return get_default_llm_model_for_user(user, organization, kind)
    except llm_models.DefaultUse.DoesNotExist:
        return None


def model_to_openai_format(model: llm_models.LLMModel) -> dict:
    """Convert a LLMModel to OpenAI API format."""
    return {
        "id": model.llm_string,
        "object": "model",
        "created": int(time.time()),  # Could use actual created_at if available
        "owned_by": model.provider.name,
        "permission": [],
        "root": model.model_id,
        "parent": None,
    }


# ============================================================================
# OpenAI-Compatible API Endpoints
# ============================================================================


@csrf_exempt
async def openai_models_view(request: HttpRequest) -> JsonResponse:
    """
    OpenAI-compatible /v1/models endpoint.

    Lists all available models for the authenticated user's organization.

    GET /v1/models

    Returns:
        {
            "object": "list",
            "data": [
                {
                    "id": "provider/model-name",
                    "object": "model",
                    "created": 1234567890,
                    "owned_by": "provider-name"
                },
                ...
            ]
        }
    """
    if request.method != "GET":
        return create_openai_error_response("Only GET method is allowed", error_type="invalid_request_error", status=405)

    try:
        user, client, organization = await authenticate_request(request)
    except AuthenticationError as e:
        return create_openai_error_response(str(e), error_type="authentication_error", code="invalid_api_key", status=401)

    models = await get_all_models_for_organization(organization)

    return JsonResponse({"object": "list", "data": [model_to_openai_format(m) for m in models]})


@csrf_exempt
async def openai_model_detail_view(request: HttpRequest, model_id: str) -> JsonResponse:
    """
    OpenAI-compatible /v1/models/{model_id} endpoint.

    Retrieves details about a specific model.

    GET /v1/models/{model_id}
    """
    if request.method != "GET":
        return create_openai_error_response("Only GET method is allowed", error_type="invalid_request_error", status=405)

    try:
        user, client, organization = await authenticate_request(request)
    except AuthenticationError as e:
        return create_openai_error_response(str(e), error_type="authentication_error", code="invalid_api_key", status=401)

    try:
        model = await get_model_by_id_or_name(model_id, organization, user)
    except DefaultModelNotConfiguredError as e:
        return create_openai_error_response(str(e), error_type="invalid_request_error", code="default_model_not_configured", param="model", status=400)

    if not model:
        return create_openai_error_response(f"Model '{model_id}' not found", error_type="invalid_request_error", code="model_not_found", status=404)

    return JsonResponse(model_to_openai_format(model))


@csrf_exempt
async def openai_chat_completions_view(request: HttpRequest) -> Union[JsonResponse, StreamingHttpResponse]:
    """
    OpenAI-compatible /v1/chat/completions endpoint.

    Creates a chat completion using LiteLLM.
    Supports streaming and tool/function calling.

    POST /v1/chat/completions

    Request body:
        {
            "model": "provider/model-name",
            "messages": [
                {"role": "system", "content": "..."},
                {"role": "user", "content": "..."}
            ],
            "temperature": 0.7,
            "max_tokens": 1000,
            "stream": false,
            "tools": [...],
            "tool_choice": "auto"
        }
    """
    if request.method != "POST":
        return create_openai_error_response("Only POST method is allowed", error_type="invalid_request_error", status=405)

    try:
        user, client, organization = await authenticate_request(request)
    except AuthenticationError as e:
        return create_openai_error_response(str(e), error_type="authentication_error", code="invalid_api_key", status=401)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return create_openai_error_response("Invalid JSON in request body", error_type="invalid_request_error", status=400)

    # Validate required fields
    if "messages" not in payload:
        return create_openai_error_response("Missing required field: messages", error_type="invalid_request_error", param="messages", status=400)

    # Get model
    model_identifier = payload.get("model")
    if model_identifier:
        try:
            model = await get_model_by_id_or_name(model_identifier, organization, user)
        except DefaultModelNotConfiguredError as e:
            return create_openai_error_response(str(e), error_type="invalid_request_error", code="default_model_not_configured", param="model", status=400)
        if not model:
            return create_openai_error_response(f"Model '{model_identifier}' not found", error_type="invalid_request_error", code="model_not_found", param="model", status=404)
    else:
        # Use default model for chat
        model = await get_default_model(user, organization, "text_generation")
        if not model:
            return create_openai_error_response("No model specified and no default model configured", error_type="invalid_request_error", param="model", status=400)

    if not model.is_available:
        return create_openai_error_response(f"Model '{model.llm_string}' is not currently available", error_type="invalid_request_error", code="model_not_available", param="model", status=503)

    # Extract parameters
    messages = payload.get("messages", [])
    stream = payload.get("stream", False)
    tools = payload.get("tools")
    tool_choice = payload.get("tool_choice")
    temperature = payload.get("temperature")
    max_tokens = payload.get("max_tokens")
    top_p = payload.get("top_p")
    frequency_penalty = payload.get("frequency_penalty")
    presence_penalty = payload.get("presence_penalty")
    stop = payload.get("stop")
    n = payload.get("n", 1)
    response_format = payload.get("response_format")

    # Build LiteLLM request kwargs
    litellm_kwargs = {
        "model": model.llm_string,
        "messages": messages,
        "api_base": model.provider.api_base,
        "api_key": model.provider.api_key,
        "stream": stream,
    }

    # Add optional parameters if provided
    if tools:
        litellm_kwargs["tools"] = tools
    if tool_choice:
        litellm_kwargs["tool_choice"] = tool_choice
    if temperature is not None:
        litellm_kwargs["temperature"] = temperature
    if max_tokens is not None:
        litellm_kwargs["max_tokens"] = max_tokens
    if top_p is not None:
        litellm_kwargs["top_p"] = top_p
    if frequency_penalty is not None:
        litellm_kwargs["frequency_penalty"] = frequency_penalty
    if presence_penalty is not None:
        litellm_kwargs["presence_penalty"] = presence_penalty
    if stop:
        litellm_kwargs["stop"] = stop
    if n != 1:
        litellm_kwargs["n"] = n
    if response_format:
        litellm_kwargs["response_format"] = response_format

    try:
        if stream:
            return await _handle_streaming_chat(litellm_kwargs)
        else:
            response = await litellm.acompletion(**litellm_kwargs)
            return JsonResponse(response.model_dump())
    except litellm.exceptions.AuthenticationError as e:
        return create_openai_error_response(f"Provider authentication failed: {str(e)}", error_type="authentication_error", status=401)
    except litellm.exceptions.RateLimitError as e:
        return create_openai_error_response(f"Rate limit exceeded: {str(e)}", error_type="rate_limit_error", status=429)
    except litellm.exceptions.InvalidRequestError as e:
        return create_openai_error_response(str(e), error_type="invalid_request_error", status=400)
    except Exception as e:
        logger.exception("Error in chat completion")
        return create_openai_error_response(f"Internal server error: {str(e)}", error_type="api_error", status=500)


async def _handle_streaming_chat(litellm_kwargs: dict) -> StreamingHttpResponse:
    """Handle streaming chat completions."""

    async def stream_generator() -> AsyncGenerator[bytes, None]:
        try:
            response = await litellm.acompletion(**litellm_kwargs)
            async for chunk in response:
                chunk_data = chunk.model_dump()
                yield f"data: {json.dumps(chunk_data)}\n\n".encode()
            yield b"data: [DONE]\n\n"
        except Exception as e:
            error_data = {
                "error": {
                    "message": str(e),
                    "type": "api_error",
                }
            }
            yield f"data: {json.dumps(error_data)}\n\n".encode()

    return StreamingHttpResponse(
        stream_generator(),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@csrf_exempt
async def openai_completions_view(request: HttpRequest) -> Union[JsonResponse, StreamingHttpResponse]:
    """
    OpenAI-compatible /v1/completions endpoint (legacy).

    Creates a text completion using LiteLLM.

    POST /v1/completions

    Request body:
        {
            "model": "provider/model-name",
            "prompt": "Hello, ",
            "max_tokens": 100,
            "temperature": 0.7
        }
    """
    if request.method != "POST":
        return create_openai_error_response("Only POST method is allowed", error_type="invalid_request_error", status=405)

    try:
        user, client, organization = await authenticate_request(request)
    except AuthenticationError as e:
        return create_openai_error_response(str(e), error_type="authentication_error", code="invalid_api_key", status=401)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return create_openai_error_response("Invalid JSON in request body", error_type="invalid_request_error", status=400)

    if "prompt" not in payload:
        return create_openai_error_response("Missing required field: prompt", error_type="invalid_request_error", param="prompt", status=400)

    model_identifier = payload.get("model")
    if model_identifier:
        try:
            model = await get_model_by_id_or_name(model_identifier, organization, user)
        except DefaultModelNotConfiguredError as e:
            return create_openai_error_response(str(e), error_type="invalid_request_error", code="default_model_not_configured", param="model", status=400)
        if not model:
            return create_openai_error_response(f"Model '{model_identifier}' not found", error_type="invalid_request_error", code="model_not_found", param="model", status=404)
    else:
        model = await get_default_model(user, organization, "text_generation")
        if not model:
            return create_openai_error_response("No model specified and no default model configured", error_type="invalid_request_error", param="model", status=400)

    if not model.is_available:
        return create_openai_error_response(f"Model '{model.llm_string}' is not currently available", error_type="invalid_request_error", code="model_not_available", param="model", status=503)

    prompt = payload.get("prompt")
    stream = payload.get("stream", False)

    litellm_kwargs = {
        "model": model.llm_string,
        "prompt": prompt,
        "api_base": model.provider.api_base,
        "api_key": model.provider.api_key,
        "stream": stream,
    }

    # Add optional parameters
    for param in ["temperature", "max_tokens", "top_p", "frequency_penalty", "presence_penalty", "stop", "n", "logprobs", "echo", "suffix"]:
        if param in payload:
            litellm_kwargs[param] = payload[param]

    try:
        if stream:
            return await _handle_streaming_completion(litellm_kwargs)
        else:
            response = await litellm.atext_completion(**litellm_kwargs)
            return JsonResponse(response.model_dump())
    except Exception as e:
        logger.exception("Error in text completion")
        return create_openai_error_response(f"Internal server error: {str(e)}", error_type="api_error", status=500)


async def _handle_streaming_completion(litellm_kwargs: dict) -> StreamingHttpResponse:
    """Handle streaming text completions."""

    async def stream_generator() -> AsyncGenerator[bytes, None]:
        try:
            response = await litellm.atext_completion(**litellm_kwargs)
            async for chunk in response:
                chunk_data = chunk.model_dump()
                yield f"data: {json.dumps(chunk_data)}\n\n".encode()
            yield b"data: [DONE]\n\n"
        except Exception as e:
            error_data = {
                "error": {
                    "message": str(e),
                    "type": "api_error",
                }
            }
            yield f"data: {json.dumps(error_data)}\n\n".encode()

    return StreamingHttpResponse(
        stream_generator(),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@csrf_exempt
async def openai_embeddings_view(request: HttpRequest) -> JsonResponse:
    """
    OpenAI-compatible /v1/embeddings endpoint.

    Creates embeddings for the given input text.

    POST /v1/embeddings

    Request body:
        {
            "model": "provider/embedding-model",
            "input": "The text to embed" | ["Text 1", "Text 2"],
            "encoding_format": "float"  // optional: "float" or "base64"
        }
    """
    if request.method != "POST":
        return create_openai_error_response("Only POST method is allowed", error_type="invalid_request_error", status=405)

    try:
        user, client, organization = await authenticate_request(request)
    except AuthenticationError as e:
        return create_openai_error_response(str(e), error_type="authentication_error", code="invalid_api_key", status=401)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return create_openai_error_response("Invalid JSON in request body", error_type="invalid_request_error", status=400)

    if "input" not in payload:
        return create_openai_error_response("Missing required field: input", error_type="invalid_request_error", param="input", status=400)

    model_identifier = payload.get("model")
    if model_identifier:
        try:
            model = await get_model_by_id_or_name(model_identifier, organization, user)
        except DefaultModelNotConfiguredError as e:
            return create_openai_error_response(str(e), error_type="invalid_request_error", code="default_model_not_configured", param="model", status=400)
        if not model:
            return create_openai_error_response(f"Model '{model_identifier}' not found", error_type="invalid_request_error", code="model_not_found", param="model", status=404)
    else:
        model = await get_default_model(user, organization, "embedding")
        if not model:
            return create_openai_error_response("No model specified and no default embedding model configured", error_type="invalid_request_error", param="model", status=400)

    if not model.is_available:
        return create_openai_error_response(f"Model '{model.llm_string}' is not currently available", error_type="invalid_request_error", code="model_not_available", param="model", status=503)

    input_text = payload.get("input")
    encoding_format = payload.get("encoding_format", "float")

    try:
        response = await litellm.aembedding(
            model=model.llm_string,
            input=input_text,
            api_base=model.provider.api_base,
            api_key=model.provider.api_key,
            encoding_format=encoding_format,
        )
        return JsonResponse(response.model_dump())
    except Exception as e:
        logger.exception("Error in embeddings")
        return create_openai_error_response(f"Internal server error: {str(e)}", error_type="api_error", status=500)


# ============================================================================
# Legacy Ollama-style endpoints (kept for backward compatibility)
# ============================================================================


@csrf_exempt
async def models_view(request: HttpRequest) -> JsonResponse:
    """Legacy models endpoint - redirects to OpenAI-compatible endpoint."""
    return await openai_models_view(request)


@csrf_exempt
async def generate_view(request: HttpRequest) -> Union[JsonResponse, StreamingHttpResponse]:
    """Legacy generate endpoint - now uses LiteLLM."""
    return await openai_completions_view(request)


@csrf_exempt
async def chat_view(request: HttpRequest) -> Union[JsonResponse, StreamingHttpResponse]:
    """Legacy chat endpoint - now uses LiteLLM."""
    return await openai_chat_completions_view(request)
