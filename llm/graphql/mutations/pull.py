"""Pulling a model into an Ollama provider."""

from typing import Optional

import aiohttp
import strawberry
from kante.types import Info

from llm import enums, models

#: A model pull downloads gigabytes, so the ceiling is generous — but it is a
#: ceiling. Without one a stalled pull held the connection open forever.
PULL_TIMEOUT_SECONDS = 3600


@strawberry.type(description="The outcome of pulling a model")
class OllamaPullResult:
    """What happened when the model was pulled."""

    status: str
    detail: Optional[str] = None


@strawberry.input(description="The model to pull, and the provider to pull it into")
class PullInput:
    """Input for pulling a model from Ollama."""

    model_name: str
    provider: Optional[strawberry.ID] = None


class ProviderNotPullable(Exception):
    """Raised when asked to pull into a provider that is not an Ollama instance."""


async def _resolve_provider(info: Info, provider_id: Optional[str]) -> models.Provider:
    """Resolve the Ollama provider to pull into, scoped to the caller's organization."""
    providers = models.Provider.objects.for_organization(info.context.request.organization)

    if provider_id:
        provider = await providers.aget(id=provider_id)
        if provider.kind != enums.ProviderKind.OLLAMA.value:
            raise ProviderNotPullable(f"Provider '{provider.name}' is a {provider.kind} provider. Only Ollama providers can pull models.")
        return provider

    provider = await providers.filter(kind=enums.ProviderKind.OLLAMA.value).afirst()
    if provider is None:
        raise ProviderNotPullable("No Ollama provider is configured for this organization. Create one, or name a provider explicitly.")
    return provider


async def pull(info: Info, input: PullInput) -> OllamaPullResult:
    """Pull a model into an Ollama provider.

    The endpoint comes from the provider rather than a hardcoded host, so an
    organization running Ollama anywhere other than ``http://ollama:11434`` can
    pull too.
    """
    provider = await _resolve_provider(info, input.provider)
    base = (provider.api_base or "").rstrip("/")

    timeout = aiohttp.ClientTimeout(total=PULL_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{base}/api/pull", json={"name": input.model_name}) as res:
                if res.status != 200:
                    try:
                        data = await res.json()
                        detail = data.get("error", f"HTTP {res.status}")
                    except Exception:
                        detail = f"HTTP {res.status}"
                    return OllamaPullResult(status="error", detail=detail)

                async for line in res.content:
                    decoded = line.decode("utf-8").strip()
                    if decoded and '"status":"success"' in decoded:
                        return OllamaPullResult(status="success")

                return OllamaPullResult(status="incomplete", detail="Pull stream ended without a success message.")
    except aiohttp.ClientError as e:
        return OllamaPullResult(status="error", detail=f"Could not reach Ollama at {base}: {e}")
