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
from typing import Any, AsyncGenerator, AsyncIterable, Awaitable, Callable, Optional, Union, Tuple
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
from llm.enums import DefaultKind, UsageEndpoint
from llm.manager import NoDefaultModel, get_default_llm_model_for_user
from llm.usage import BudgetExceeded, aenforce_budget, arecord_usage, usage_from_response, usage_from_stream

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
    token = await authenticate_header_or_none(request.headers)
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


def litellm_error_response(e: Exception, *, model: Optional[llm_models.LLMModel] = None) -> JsonResponse:
    """Map a litellm exception to an OpenAI-compatible error response.

    Surfaces the upstream provider and HTTP status where available so a failing
    request reports *which* provider rejected it and *why*, instead of a blanket
    ``Internal server error``. Mirrors ``llm.errors.wrap_llm_errors`` (used by the
    GraphQL mutations) for the REST endpoints. The specific subclasses are checked
    before ``APIError`` because they all inherit from it.
    """
    ctx = f" for model '{model.llm_string}'" if model is not None else ""
    if isinstance(e, BudgetExceeded):
        return create_openai_error_response(f"{e}", error_type="insufficient_quota", code="budget_exceeded", status=429)
    if isinstance(e, litellm.exceptions.AuthenticationError):
        return create_openai_error_response(f"Provider authentication failed{ctx}: {e}", error_type="authentication_error", status=401)
    if isinstance(e, litellm.exceptions.RateLimitError):
        return create_openai_error_response(f"Rate limit exceeded{ctx}: {e}", error_type="rate_limit_error", status=429)
    if isinstance(e, litellm.exceptions.InvalidRequestError):
        return create_openai_error_response(f"{e}", error_type="invalid_request_error", status=400)
    if isinstance(e, litellm.exceptions.APIError):
        status = getattr(e, "status_code", None)
        upstream = getattr(e, "llm_provider", None) or "provider"
        msg = getattr(e, "message", None) or str(e)
        out_status = status if isinstance(status, int) and 400 <= status < 600 else 502
        return create_openai_error_response(f"Upstream {upstream} returned {status}{ctx}: {msg}", error_type="api_error", status=out_status)
    logger.exception("Unexpected LLM error")
    return create_openai_error_response(f"Internal server error{ctx}: {e}", error_type="api_error", status=500)


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
        kind: Optional[DefaultKind] = None

        if suffix in ("", "-chat", "-text"):
            kind = DefaultKind.TEXT_GENERATION
        elif suffix == "-embedding":
            kind = DefaultKind.EMBEDDING
        elif suffix == "-image":
            kind = DefaultKind.IMAGE_GENERATION

        if kind is not None:
            try:
                return get_default_llm_model_for_user(user, organization, kind)
            except NoDefaultModel as e:
                raise DefaultModelNotConfiguredError(str(e)) from e

    scoped = llm_models.LLMModel.objects.for_organization(organization).select_related("provider")

    # First try to get by database ID
    try:
        return scoped.get(id=model_identifier)
    except (llm_models.LLMModel.DoesNotExist, ValueError):
        pass

    # Then try by model_id
    match = scoped.filter(model_id=model_identifier).first()
    if match is not None:
        return match

    # Finally try by llm_string pattern (provider/model). The advertised ids
    # use the litellm prefix derived from Provider.kind, but a provider's
    # display name is also accepted for backward compatibility.
    if "/" in model_identifier:
        prefix, model_id = model_identifier.split("/", 1)
        match = scoped.filter(provider__kind__in=llm_models.KINDS_BY_LITELLM_PREFIX.get(prefix, []), model_id=model_id).first()
        if match is None:
            match = scoped.filter(provider__name=prefix, model_id=model_id).first()
        return match

    return None


@sync_to_async
def get_all_models_for_organization(organization: Organization) -> list[llm_models.LLMModel]:
    """Get all available models for an organization."""
    return list(llm_models.LLMModel.objects.for_organization(organization).select_related("provider"))


@sync_to_async
def get_default_model(user: User, organization: Organization, kind: DefaultKind) -> Optional[llm_models.LLMModel]:
    """Get the default model for a user and organization."""
    try:
        return get_default_llm_model_for_user(user, organization, kind)
    except NoDefaultModel:
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
        model = await get_default_model(user, organization, DefaultKind.TEXT_GENERATION)
        if not model:
            return create_openai_error_response("No model specified and no default model configured", error_type="invalid_request_error", param="model", status=400)

    if not model.is_available:
        return create_openai_error_response(f"Model '{model.llm_string}' is not currently available", error_type="invalid_request_error", code="model_not_available", param="model", status=503)

    stream = bool(payload.get("stream", False))

    litellm_kwargs = _build_litellm_kwargs(
        payload,
        model,
        handled={"model", "messages", "stream"},
        messages=payload["messages"],
        stream=stream,
    )

    started = time.monotonic()
    accounting = dict(organization=organization, user=user, client=client, model=model, endpoint=UsageEndpoint.REST_CHAT)

    try:
        await aenforce_budget(organization, user, model)
        if stream:
            # Ask the upstream to report usage on its final chunk. The extra
            # usage-only chunk is hidden from callers that did not ask for it.
            injected_usage = "stream_options" not in payload
            if injected_usage:
                litellm_kwargs["stream_options"] = {"include_usage": True}
                litellm_kwargs.setdefault("drop_params", True)
            response = await litellm.acompletion(**litellm_kwargs)

            async def on_complete(chunks: list, error: Optional[BaseException]) -> None:
                facts = await sync_to_async(usage_from_stream)(chunks, messages=payload["messages"], model_string=model.llm_string)
                await arecord_usage(**accounting, facts=facts, started_at=started, error=error)

            return _streaming_response(response, on_complete=on_complete, hide_usage_chunks=injected_usage)
        else:
            response = await litellm.acompletion(**litellm_kwargs)
            await arecord_usage(**accounting, facts=usage_from_response(response, model_string=model.llm_string), started_at=started)
            return JsonResponse(response.model_dump())
    except Exception as e:
        if not isinstance(e, BudgetExceeded):
            await arecord_usage(**accounting, started_at=started, error=e)
        return litellm_error_response(e, model=model)


#: Request-body keys never forwarded to litellm: routing and credentials are
#: decided by the resolved model's provider, not the caller.
RESERVED_LITELLM_KEYS = {
    "api_key",
    "api_base",
    "base_url",
    "api_version",
    "custom_llm_provider",
    "extra_headers",
    "organization",
}


def _build_litellm_kwargs(payload: dict, model: llm_models.LLMModel, *, handled: set, **explicit) -> dict:
    """Assemble litellm kwargs: provider routing/credentials, the explicitly
    handled fields, and every remaining request-body key forwarded verbatim.

    A closed allowlist here silently dropped whatever the caller's SDK sent that
    we hadn't enumerated (``stream_options``, ``seed``, ``logprobs``, ...); as a
    tunnel we pass params through and reserve only the routing/credential keys.
    """
    kwargs = {
        "model": model.llm_string,
        "api_base": model.provider.api_base,
        "api_key": model.provider.api_key,
        **explicit,
    }
    for key, value in payload.items():
        if key in handled or key in RESERVED_LITELLM_KEYS or value is None:
            continue
        kwargs[key] = value
    return kwargs


StreamCallback = Callable[[list, Optional[BaseException]], Awaitable[None]]


def _streaming_response(response: AsyncIterable[Any], *, on_complete: Optional[StreamCallback] = None, hide_usage_chunks: bool = False) -> StreamingHttpResponse:
    """Wrap an already-started litellm stream as SSE.

    The upstream call is awaited by the caller *before* this response is
    constructed, so pre-stream failures (bad provider key, rate limit) surface
    as real HTTP statuses via ``litellm_error_response`` instead of a 200 with
    an error frame. Only mid-stream failures degrade to an error event.

    ``on_complete(chunks, error)`` runs once the stream ends — after ``[DONE]``,
    after an error frame, or when the client disconnects — so usage can be
    recorded from whatever was actually sent. ``hide_usage_chunks`` drops the
    choices-less usage chunk that ``stream_options.include_usage`` adds, for
    callers that did not request it.
    """

    async def stream_generator() -> AsyncGenerator[bytes, None]:
        chunks: list = []
        error: Optional[BaseException] = None
        try:
            async for chunk in response:
                chunks.append(chunk)
                chunk_data = chunk.model_dump()
                if hide_usage_chunks and not chunk_data.get("choices") and chunk_data.get("usage"):
                    continue
                yield f"data: {json.dumps(chunk_data)}\n\n".encode()
            yield b"data: [DONE]\n\n"
        except Exception as e:
            error = e
            error_data = {
                "error": {
                    "message": str(e),
                    "type": "api_error",
                }
            }
            yield f"data: {json.dumps(error_data)}\n\n".encode()
        except BaseException as e:  # client disconnect: GeneratorExit / CancelledError
            error = e
            raise
        finally:
            if on_complete is not None:
                try:
                    await on_complete(chunks, error)
                except Exception:
                    logger.exception("Usage callback failed after stream")

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
        model = await get_default_model(user, organization, DefaultKind.TEXT_GENERATION)
        if not model:
            return create_openai_error_response("No model specified and no default model configured", error_type="invalid_request_error", param="model", status=400)

    if not model.is_available:
        return create_openai_error_response(f"Model '{model.llm_string}' is not currently available", error_type="invalid_request_error", code="model_not_available", param="model", status=503)

    stream = bool(payload.get("stream", False))

    litellm_kwargs = _build_litellm_kwargs(
        payload,
        model,
        handled={"model", "prompt", "stream"},
        prompt=payload["prompt"],
        stream=stream,
    )

    started = time.monotonic()
    accounting = dict(organization=organization, user=user, client=client, model=model, endpoint=UsageEndpoint.REST_COMPLETION)

    try:
        await aenforce_budget(organization, user, model)
        if stream:
            response = await litellm.atext_completion(**litellm_kwargs)

            async def on_complete(chunks: list, error: Optional[BaseException]) -> None:
                facts = await sync_to_async(usage_from_stream)(chunks, model_string=model.llm_string, text_completion=True)
                await arecord_usage(**accounting, facts=facts, started_at=started, error=error)

            return _streaming_response(response, on_complete=on_complete)
        else:
            response = await litellm.atext_completion(**litellm_kwargs)
            await arecord_usage(**accounting, facts=usage_from_response(response, model_string=model.llm_string), started_at=started)
            return JsonResponse(response.model_dump())
    except Exception as e:
        if not isinstance(e, BudgetExceeded):
            await arecord_usage(**accounting, started_at=started, error=e)
        return litellm_error_response(e, model=model)


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
        model = await get_default_model(user, organization, DefaultKind.EMBEDDING)
        if not model:
            return create_openai_error_response("No model specified and no default embedding model configured", error_type="invalid_request_error", param="model", status=400)

    if not model.is_available:
        return create_openai_error_response(f"Model '{model.llm_string}' is not currently available", error_type="invalid_request_error", code="model_not_available", param="model", status=503)

    litellm_kwargs = _build_litellm_kwargs(
        payload,
        model,
        handled={"model", "input"},
        input=payload["input"],
        encoding_format=payload.get("encoding_format", "float"),
    )

    started = time.monotonic()
    accounting = dict(organization=organization, user=user, client=client, model=model, endpoint=UsageEndpoint.REST_EMBEDDING)

    try:
        await aenforce_budget(organization, user, model)
        response = await litellm.aembedding(**litellm_kwargs)
        await arecord_usage(**accounting, facts=usage_from_response(response, model_string=model.llm_string, call_type="embedding"), started_at=started)
        return JsonResponse(response.model_dump())
    except Exception as e:
        if not isinstance(e, BudgetExceeded):
            await arecord_usage(**accounting, started_at=started, error=e)
        return litellm_error_response(e, model=model)


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
