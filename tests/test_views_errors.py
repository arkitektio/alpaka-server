"""Tests for ``llm.views.litellm_error_response`` — the REST counterpart to
``llm.errors.wrap_llm_errors`` that maps litellm failures to OpenAI-compatible
error responses with upstream provider/status surfaced.

Needs Django configured (``DJANGO_SETTINGS_MODULE``) but no database; run with
``uv run pytest tests/test_views_errors.py``.
"""

import json
import types

import litellm

from llm.views import litellm_error_response


def make_model():
    provider = types.SimpleNamespace(
        name="openrouter",
        kind="OPENROUTER",
        api_base="https://openrouter.ai/api/v1",
    )
    return types.SimpleNamespace(
        llm_string="openrouter/sakana",
        model_id="sakana-x",
        provider=provider,
    )


def body(response):
    return json.loads(response.content)["error"]


def test_api_error_surfaces_upstream_status_and_provider():
    """The reported 403 case: status is propagated and the message names the
    upstream provider and the model instead of a blanket 500."""
    e = litellm.exceptions.APIError(
        status_code=403,
        message="OpenrouterException - 403 Forbidden (Sakana AI)",
        llm_provider="openrouter",
        model="x",
    )
    r = litellm_error_response(e, model=make_model())
    assert r.status_code == 403
    err = body(r)
    assert err["type"] == "api_error"
    assert "openrouter" in err["message"]
    assert "403" in err["message"]
    assert "openrouter/sakana" in err["message"]  # model context
    assert "Sakana AI" in err["message"]  # buried upstream detail preserved


def test_api_error_without_usable_status_falls_back_to_502():
    """A non-HTTP / missing status_code becomes a 502 rather than echoing a
    nonsensical HTTP status."""
    e = litellm.exceptions.APIError(
        status_code=0, message="connection blew up", llm_provider="openrouter", model="x"
    )
    r = litellm_error_response(e, model=make_model())
    assert r.status_code == 502


def test_authentication_error_maps_to_401():
    e = litellm.exceptions.AuthenticationError(message="bad key", llm_provider="openrouter", model="x")
    r = litellm_error_response(e, model=make_model())
    assert r.status_code == 401
    assert body(r)["type"] == "authentication_error"
    assert "Provider authentication failed" in body(r)["message"]


def test_rate_limit_error_maps_to_429():
    e = litellm.exceptions.RateLimitError(message="slow down", llm_provider="openrouter", model="x")
    r = litellm_error_response(e, model=make_model())
    assert r.status_code == 429
    assert body(r)["type"] == "rate_limit_error"


def test_invalid_request_error_maps_to_400():
    e = litellm.exceptions.InvalidRequestError(message="bad params", model="x", llm_provider="openrouter")
    r = litellm_error_response(e, model=make_model())
    assert r.status_code == 400
    assert body(r)["type"] == "invalid_request_error"


def test_generic_error_is_500_and_works_without_model():
    """Non-litellm errors map to 500, and the helper tolerates no model."""
    r = litellm_error_response(ValueError("weird"), model=None)
    assert r.status_code == 500
    assert body(r)["type"] == "api_error"
    assert "weird" in body(r)["message"]
