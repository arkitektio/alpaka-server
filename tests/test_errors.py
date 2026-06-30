"""Tests for ``llm.errors.wrap_llm_errors`` — the helper that re-raises litellm
failures with model/provider context attached.

Standalone — needs no database; run with ``uv run pytest tests/test_errors.py``.
"""

import types

import litellm
import pytest

from llm.errors import wrap_llm_errors


def make_model():
    """A minimal stand-in for ``llm.models.LLMModel`` exposing only the
    attributes ``wrap_llm_errors`` reads."""
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


def test_passthrough_on_success():
    """No exception inside the block -> nothing raised, value usable."""
    with wrap_llm_errors(make_model()):
        result = 42
    assert result == 42


def test_api_error_includes_full_context():
    """An upstream ``APIError`` (the reported 403 case) is re-raised naming the
    model, provider, kind, endpoint, upstream provider and status code."""
    model = make_model()
    raw = (
        'OpenrouterException - {"error":{"message":"Provider returned error",'
        '"code":403,"metadata":{"provider_name":"Sakana AI"}}}'
    )
    with pytest.raises(Exception) as excinfo:
        with wrap_llm_errors(model):
            raise litellm.exceptions.APIError(
                status_code=403,
                message=raw,
                llm_provider="openrouter",
                model="sakana-x",
            )

    msg = str(excinfo.value)
    assert "openrouter/sakana" in msg
    assert "id=sakana-x" in msg
    assert "OPENROUTER" in msg
    assert "https://openrouter.ai/api/v1" in msg
    assert "403" in msg
    assert "Sakana AI" in msg  # the buried upstream detail is preserved


def test_original_exception_is_chained():
    """The litellm exception is preserved as ``__cause__`` for the traceback."""
    original = litellm.exceptions.APIError(
        status_code=500, message="boom", llm_provider="openrouter", model="x"
    )
    with pytest.raises(Exception) as excinfo:
        with wrap_llm_errors(make_model()):
            raise original
    assert excinfo.value.__cause__ is original


def test_authentication_error_wording():
    """Auth failures use the dedicated, REST-consistent wording."""
    with pytest.raises(Exception) as excinfo:
        with wrap_llm_errors(make_model()):
            raise litellm.exceptions.AuthenticationError(
                message="bad key", llm_provider="openrouter", model="x"
            )
    msg = str(excinfo.value)
    assert "Provider authentication failed" in msg
    assert "openrouter/sakana" in msg


def test_rate_limit_error_wording():
    """Rate-limit failures use the dedicated, REST-consistent wording."""
    with pytest.raises(Exception) as excinfo:
        with wrap_llm_errors(make_model()):
            raise litellm.exceptions.RateLimitError(
                message="slow down", llm_provider="openrouter", model="x"
            )
    msg = str(excinfo.value)
    assert "Rate limit exceeded" in msg
    assert "openrouter/sakana" in msg


def test_generic_exception_still_gets_context():
    """Non-litellm errors still get model/provider context attached."""
    with pytest.raises(Exception) as excinfo:
        with wrap_llm_errors(make_model()):
            raise ValueError("something unexpected")
    msg = str(excinfo.value)
    assert "LLM request failed" in msg
    assert "openrouter/sakana" in msg
    assert "something unexpected" in msg
