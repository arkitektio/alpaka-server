"""alpaka as a systemone endpoint.

Mounted under ``llm/systemone/`` so that a stock TypeSafe or Ollaya client --
which builds ``/v1/systemone`` and ``/v1/models`` from its base URL -- works
against alpaka with ``TYPESAFE_BASE_URL=<alpaka>/llm/systemone`` and an alpaka
token as its key. ``llm/v1/models`` is already the OpenAI listing, which is why
this surface needs its own prefix.

The request is forwarded to whichever decision backend serves the resolved
model; the client never sees the organization's upstream credentials. Errors
use the systemone shape (``{"error", "code"}``) rather than OpenAI's.
"""

import json
import logging
import time
from typing import Any, Optional

from asgiref.sync import sync_to_async
from authentikate.models import Organization, User
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from llm import views as llm_views
from llm.decision.backends import DecisionError, backend_for
from llm.enums import DefaultKind, FeatureType, UsageEndpoint
from llm.manager import NoDefaultModel, get_default_llm_model_for_user
from llm.models import LLMModel
from llm.usage import BudgetExceeded, aenforce_budget, arecord_usage

logger = logging.getLogger(__name__)

#: The alias that resolves to the caller's default decision model.
DEFAULT_ALIAS = "alpaka/default"

#: A spent budget answers 402 rather than 429: the TypeSafe SDK retries 429 (and
#: every 5xx) on its own, and retrying a budget refusal only burns attempts.
BUDGET_EXCEEDED_STATUS = 402


def error_response(message: str, code: str, status: int, detail: Any = None) -> JsonResponse:
    """A systemone-shaped error body."""
    body: dict[str, Any] = {"error": message, "code": code}
    if detail is not None:
        body["detail"] = detail
    return JsonResponse(body, status=status)


def _decision_models(organization: Organization):
    return LLMModel.objects.for_organization(organization).select_related("provider").filter(features__contains=[FeatureType.DECISION.value])


@sync_to_async
def resolve_decision_model(identifier: Optional[str], organization: Organization, user: Optional[User]) -> Optional[LLMModel]:
    """The decision model a request names: an alias, a model id, or a database id.

    Only decision models are candidates, so a name shared with an LLM never
    resolves to the LLM.
    """
    if not identifier or identifier.startswith(DEFAULT_ALIAS):
        if not isinstance(user, User):
            return None
        try:
            return get_default_llm_model_for_user(user, organization, DefaultKind.DECISION)
        except NoDefaultModel:
            return None

    scoped = _decision_models(organization)
    match = scoped.filter(model_id=identifier).order_by("id").first()
    if match is None and identifier.isdigit():
        match = scoped.filter(id=identifier).first()
    return match


@sync_to_async
def list_decision_models(organization: Organization) -> list[LLMModel]:
    return list(_decision_models(organization).order_by("model_id"))


async def _authenticate(request: HttpRequest):
    try:
        return await llm_views.authenticate_request(request), None
    except llm_views.AuthenticationError as e:
        return None, error_response(str(e), "UNAUTHORIZED", 401)


@csrf_exempt
async def systemone_models_view(request: HttpRequest) -> JsonResponse:
    """``GET systemone/v1/models``: the organization's decision models, in the systemone shape."""
    if request.method != "GET":
        return error_response("Only GET is allowed", "METHOD_NOT_ALLOWED", 405)
    identity, failure = await _authenticate(request)
    if failure:
        return failure
    _, _, organization = identity

    models = await list_decision_models(organization)
    return JsonResponse({"models": [{"name": model.model_id, "description": model.label, "release_date": ""} for model in models]})


@csrf_exempt
async def systemone_view(request: HttpRequest) -> JsonResponse:
    """``POST systemone/v1/systemone``: answer typed questions with the resolved model."""
    if request.method != "POST":
        return error_response("Only POST is allowed", "METHOD_NOT_ALLOWED", 405)
    identity, failure = await _authenticate(request)
    if failure:
        return failure
    user, client, organization = identity

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return error_response("Invalid JSON in request body", "INVALID_REQUEST", 400)
    if not isinstance(payload, dict):
        return error_response("Request body must be a JSON object", "INVALID_REQUEST", 400)
    for field in ("state", "questions"):
        if field not in payload:
            return error_response(f"{field}: Field required", "INVALID_REQUEST", 422, detail=[{"loc": ["body", field], "msg": "Field required", "type": "missing"}])

    identifier = payload.get("model")
    model = await resolve_decision_model(identifier, organization, user)
    if model is None:
        if not identifier or identifier.startswith(DEFAULT_ALIAS):
            return error_response("No model named and no default decision model configured. Set one with useModelFor(kind: DECISION).", "MODEL_NOT_FOUND", 404)
        return error_response(f"Decision model '{identifier}' not found", "MODEL_NOT_FOUND", 404)

    started = time.monotonic()
    accounting = dict(organization=organization, user=user, client=client, model=model, endpoint=UsageEndpoint.REST_DECIDE)
    try:
        await aenforce_budget(organization, user, model)
    except BudgetExceeded as e:
        return error_response(str(e), "BUDGET_EXCEEDED", BUDGET_EXCEEDED_STATUS)

    backend = backend_for(model.provider)
    try:
        # Only state and questions are forwarded: the model is the resolved
        # upstream id, never the alias the caller used.
        response = await backend.decide(model, payload["state"], payload["questions"])
    except DecisionError as e:
        await arecord_usage(**accounting, started_at=started, error=e)
        body = e.body if isinstance(e.body, dict) and "error" in e.body else {"error": str(e), "code": e.code or "UPSTREAM_ERROR"}
        return JsonResponse(body, status=e.status if isinstance(e.status, int) and 400 <= e.status < 600 else 502)
    except Exception as e:
        await arecord_usage(**accounting, started_at=started, error=e)
        logger.exception("Decision request failed")
        return error_response(f"Decision request failed: {e}", "INTERNAL_ERROR", 500)

    await arecord_usage(**accounting, facts=backend.usage_of(response), started_at=started)
    return JsonResponse(response)
