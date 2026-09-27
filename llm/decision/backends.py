"""Backends for typed decision models, one per wire protocol.

Every backend today speaks the systemone protocol, so there is one HTTP
implementation (:class:`SystemOneBackend`) and the kinds differ only in their
default endpoint, their price and, for Ollaya, the ability to pull models. A
runtime with a different protocol becomes another :class:`DecisionBackend`
registered in :data:`DECISION_BACKENDS`; callers only ever go through
:func:`backend_for`.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, Protocol

import aiohttp

from llm.enums import ProviderKind
from llm.models import LLMModel, Provider
from llm.usage import UsageFacts

logger = logging.getLogger(__name__)

#: A decision call is a single forward pass, milliseconds to a few seconds even
#: on CPU; the ceiling only guards against a hung upstream.
DECIDE_TIMEOUT_SECONDS = 60
LIST_MODELS_TIMEOUT_SECONDS = 60
#: A pull downloads hundreds of megabytes to gigabytes.
PULL_TIMEOUT_SECONDS = 3600

#: Statuses worth another attempt: rate limited, overloaded (TypeSafe's 529),
#: and the gateway errors a restarting local daemon produces.
RETRY_STATUSES = frozenset({429, 502, 503, 504, 529})
MAX_ATTEMPTS = 3
RETRY_BASE_SECONDS = 0.5
RETRY_MAX_SECONDS = 10.0


class DecisionError(Exception):
    """A decision backend refused or failed a request.

    Carries the upstream status and the wire error body so the REST passthrough
    can relay a validation failure verbatim instead of flattening it.
    """

    def __init__(self, message: str, *, status: Optional[int] = None, code: Optional[str] = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body


@dataclass
class DecisionModelInfo:
    """One entry of a backend's model list."""

    name: str
    description: str = ""
    release_date: Optional[str] = None


class DecisionBackend(Protocol):
    """What alpaka needs from a decision runtime."""

    kind: ProviderKind
    label: str
    default_api_base: str

    async def decide(self, model: LLMModel, state: Any, questions: dict) -> dict:
        """Answer ``questions`` about ``state``; returns the systemone response body."""
        ...

    async def list_models(self, provider: Provider) -> list[DecisionModelInfo]:
        """The models ``provider`` serves."""
        ...

    def usage_of(self, response: dict) -> UsageFacts:
        """Token counts and cost of one ``decide`` response."""
        ...


def _retry_delay(attempt: int, headers: Any) -> float:
    """Seconds to wait before the next attempt, honouring a numeric Retry-After."""
    retry_after = headers.get("Retry-After") if headers is not None else None
    if retry_after:
        try:
            return min(float(retry_after), RETRY_MAX_SECONDS)
        except ValueError:
            pass
    return min(RETRY_BASE_SECONDS * (2**attempt), RETRY_MAX_SECONDS)


class SystemOneBackend:
    """The systemone wire protocol over HTTP."""

    def __init__(self, kind: ProviderKind, *, label: str, default_api_base: str, input_price_per_million: Decimal) -> None:
        self.kind = kind
        self.label = label
        self.default_api_base = default_api_base
        self.input_price_per_million = input_price_per_million

    def base_url(self, provider: Provider) -> str:
        """The provider's endpoint, or this backend's default.

        Auto-configured partners (the ``providers:`` config shorthand) carry no
        ``api_base``, so the default has to live here rather than only in the
        createProvider mutation.
        """
        return (provider.api_base or self.default_api_base).rstrip("/")

    def headers(self, provider: Provider) -> dict[str, str]:
        """Bearer auth when a key is configured; a keyless local daemon gets none."""
        headers = {"Content-Type": "application/json"}
        if provider.api_key:
            headers["Authorization"] = f"Bearer {provider.api_key}"
        return headers

    async def _request(self, provider: Provider, method: str, path: str, *, body: Optional[dict] = None, timeout: float = DECIDE_TIMEOUT_SECONDS) -> dict:
        """One JSON request, retried on the transient statuses."""
        url = f"{self.base_url(provider)}{path}"
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        for attempt in range(MAX_ATTEMPTS):
            try:
                async with aiohttp.ClientSession(headers=self.headers(provider), timeout=client_timeout) as session:
                    async with session.request(method, url, json=body) as res:
                        text = await res.text()
                        if res.status == 200:
                            return json.loads(text)
                        if res.status in RETRY_STATUSES and attempt + 1 < MAX_ATTEMPTS:
                            delay = _retry_delay(attempt, res.headers)
                            logger.info("%s %s returned %s, retrying in %.1fs", self.label, path, res.status, delay)
                            await asyncio.sleep(delay)
                            continue
                        raise self._error(res.status, text)
            except aiohttp.ClientError as e:
                raise DecisionError(f"Could not reach {self.label} at {url}: {e}", status=502, code="UPSTREAM_UNREACHABLE") from e
            except asyncio.TimeoutError as e:
                raise DecisionError(f"{self.label} at {url} did not answer within {timeout:.0f}s", status=504, code="UPSTREAM_TIMEOUT") from e
        raise AssertionError("unreachable")  # pragma: no cover

    def _error(self, status: int, text: str) -> DecisionError:
        """Turn a non-200 wire response into a :class:`DecisionError`."""
        try:
            body = json.loads(text)
        except ValueError:
            body = None
        if isinstance(body, dict):
            message = body.get("error") or body.get("message") or text
            code = body.get("code")
            if not isinstance(message, str):
                message = json.dumps(message)
        else:
            message, code = text or f"HTTP {status}", None
        return DecisionError(f"{self.label} returned {status}: {message}", status=status, code=code, body=body)

    async def decide(self, model: LLMModel, state: Any, questions: dict) -> dict:
        return await self._request(model.provider, "POST", "/v1/systemone", body={"model": model.model_id, "state": state, "questions": questions})

    async def list_models(self, provider: Provider) -> list[DecisionModelInfo]:
        data = await self._request(provider, "GET", "/v1/models", timeout=LIST_MODELS_TIMEOUT_SECONDS)
        return [
            DecisionModelInfo(name=entry["name"], description=entry.get("description") or "", release_date=entry.get("release_date"))
            for entry in data.get("models", [])
            if isinstance(entry, dict) and entry.get("name")
        ]

    def usage_of(self, response: dict) -> UsageFacts:
        usage = response.get("usage") or {}
        prompt = int(usage.get("input_tokens") or 0)
        completion = int(usage.get("output_tokens") or 0)
        cost = self.input_price_per_million * prompt / Decimal(1_000_000)
        return UsageFacts(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion, cost=cost)


class OllayaBackend(SystemOneBackend):
    """A self-hosted Ollaya daemon, which can also pull models by name."""

    async def pull(self, provider: Provider, name: str) -> tuple[str, Optional[str]]:
        """Pull ``name`` into the daemon; returns ``(status, detail)`` like the Ollama pull.

        Ollaya's pull takes ``{"model": ...}`` (Ollama's takes ``name``) and
        streams NDJSON progress ending in ``{"status": "success"}``.
        """
        url = f"{self.base_url(provider)}/api/pull"
        timeout = aiohttp.ClientTimeout(total=PULL_TIMEOUT_SECONDS)
        try:
            async with aiohttp.ClientSession(headers=self.headers(provider), timeout=timeout) as session:
                async with session.post(url, json={"model": name}) as res:
                    if res.status != 200:
                        error = self._error(res.status, await res.text())
                        return "error", str(error)
                    async for line in res.content:
                        decoded = line.decode("utf-8").strip()
                        if not decoded:
                            continue
                        try:
                            event = json.loads(decoded)
                        except ValueError:
                            continue
                        if event.get("error"):
                            return "error", str(event["error"])
                        if event.get("status") == "success":
                            return "success", None
                    return "incomplete", "Pull stream ended without a success message."
        except aiohttp.ClientError as e:
            return "error", f"Could not reach {self.label} at {url}: {e}"


DECISION_BACKENDS: dict[str, DecisionBackend] = {
    ProviderKind.TYPESAFE.value: SystemOneBackend(
        ProviderKind.TYPESAFE,
        label="TypeSafe",
        default_api_base="https://api.typesafe.ai",
        # Input only; output tokens are free (docs.typesafe.ai/models).
        input_price_per_million=Decimal("0.042"),
    ),
    ProviderKind.OLLAYA.value: OllayaBackend(
        ProviderKind.OLLAYA,
        label="Ollaya",
        default_api_base="http://ollaya:11435",
        input_price_per_million=Decimal(0),
    ),
}


def is_decision_kind(kind: "ProviderKind | str | None") -> bool:
    """Whether providers of ``kind`` serve decision models."""
    return getattr(kind, "value", kind) in DECISION_BACKENDS


def backend_for(provider: Provider) -> DecisionBackend:
    """The decision backend serving ``provider``."""
    kind = getattr(provider.kind, "value", provider.kind)
    try:
        return DECISION_BACKENDS[kind]
    except KeyError:
        raise DecisionError(f"Provider '{provider.name}' is a {kind} provider, which serves no decision models.", status=400, code="NOT_A_DECISION_PROVIDER") from None
