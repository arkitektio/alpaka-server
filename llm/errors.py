"""Helpers for surfacing LLM provider failures with actionable context.

When litellm fails, the raw exception (e.g. ``OpenrouterException - {...403...}``)
tells you *that* something went wrong but not *which* model or provider was being
used. ``wrap_llm_errors`` re-raises these failures with the model/provider context
attached so callers (and the GraphQL response) get an actionable message.
"""

import contextlib

import litellm


class WrongModelKind(Exception):
    """Raised when a model is used for a task it cannot do.

    Decision models answer typed questions and are unreachable through
    litellm; generative models cannot answer ``decide``.
    """


def ensure_generative(model) -> None:
    """Reject a decision model on a chat, completion, image or embedding path."""
    if model.is_decision_model:
        raise WrongModelKind(f"Model '{model.model_id}' is a decision model: it answers typed questions and cannot generate. Use the decide mutation or the systemone endpoint.")


def ensure_decision(model) -> None:
    """Reject a generative model on the decide paths."""
    if not model.is_decision_model:
        raise WrongModelKind(f"Model '{model.model_id}' is not a decision model. Pick a model from a decision provider (e.g. TypeSafe or Ollaya).")


@contextlib.contextmanager
def wrap_llm_errors(model):
    """Run an litellm call, re-raising failures with model/provider context.

    Wraps a block that performs a litellm request for ``model`` (an
    ``llm.models.LLMModel``). On failure the original exception is preserved via
    ``raise ... from`` while the surfaced message names the model, provider,
    provider kind, endpoint, upstream provider, and HTTP status where available.
    """
    provider = model.provider
    ctx = (
        f"model '{model.llm_string}' (id={model.model_id}) via provider "
        f"'{provider.name}' [{provider.kind}] at {provider.api_base}"
    )
    try:
        yield
    except litellm.exceptions.AuthenticationError as e:
        raise Exception(f"Provider authentication failed for {ctx}: {e}") from e
    except litellm.exceptions.RateLimitError as e:
        raise Exception(f"Rate limit exceeded for {ctx}: {e}") from e
    except litellm.exceptions.APIError as e:
        status = getattr(e, "status_code", None)
        upstream = getattr(e, "llm_provider", None)
        msg = getattr(e, "message", None) or str(e)
        raise Exception(
            f"LLM request failed for {ctx}: upstream "
            f"{upstream or 'provider'} returned {status} — {msg}"
        ) from e
    except Exception as e:
        raise Exception(f"LLM request failed for {ctx}: {e}") from e
