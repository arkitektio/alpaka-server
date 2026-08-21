"""Create, update, refresh and delete LLM providers."""

import strawberry
from kante.types import Info

from llm import inputs, logic, models, types
from llm.redaction import REDACTED

#: Providers whose endpoint is fixed and need not be supplied by the caller.
#: Anything absent here must be given an explicit ``api_base``.
DEFAULT_API_BASE_MAP = {
    models.ProviderKind.OPENROUTER.value: "https://openrouter.ai/api/v1",
    models.ProviderKind.OLLAMA.value: "http://ollama:11434",
}


class ApiBaseRequired(Exception):
    """Raised when a provider kind has no default endpoint and none was given."""


def _resolve_api_base(kind: str, api_base: str | None) -> str:
    """Return the endpoint to use, or explain that one has to be supplied."""
    if api_base:
        return api_base
    default = DEFAULT_API_BASE_MAP.get(kind)
    if default is None:
        raise ApiBaseRequired(f"Provider kind '{kind}' has no default endpoint. Supply apiBase explicitly.")
    return default


async def create_provider(info: Info, input: inputs.ProviderInput) -> types.Provider:
    """Create a new provider of LLMs, then list the models it offers."""
    kind = input.kind.value
    provider, _ = await models.Provider.objects.for_write().aupdate_or_create(
        organization=info.context.request.organization,
        name=input.name or kind,
        defaults=dict(
            kind=kind,
            api_key=input.api_key,
            api_base=_resolve_api_base(kind, input.api_base),
            additional_config=input.additional_config,
            creator=info.context.request.user,
            description=input.description or "No description provided",
        ),
    )

    await logic.arefresh_provider_models(provider)
    return provider


def _merge_config(stored: dict | None, submitted: dict) -> dict:
    """Apply a submitted config without letting a redaction mask overwrite a secret.

    ``Provider.additionalConfig`` reads back with credential-bearing values
    masked, so a client that reads the config, edits one field and writes the
    whole object back would otherwise persist ``"**********"`` over a live
    credential. A value equal to the mask means "unchanged", and the stored one
    is kept.
    """
    stored = stored or {}
    return {key: stored.get(key) if value == REDACTED and key in stored else value for key, value in submitted.items()}


@strawberry.input(description="The provider to update, and the fields to change")
class UpdateProviderInput:
    """Fields left unset are kept as they are."""

    id: strawberry.ID
    name: str | None = None
    description: str | None = None
    api_key: str | None = None
    api_base: str | None = None
    additional_config: strawberry.scalars.JSON | None = None
    """Values reading back as the redaction mask are treated as unchanged."""


async def update_provider(info: Info, input: UpdateProviderInput) -> types.Provider:
    """Update a provider in place.

    Rotating a credential previously meant deleting and recreating the provider,
    which cascaded away every model and every collection embedded by one.
    """
    provider = await models.Provider.objects.for_organization(info.context.request.organization).aget(id=input.id)

    changed = {field: value for field, value in (("name", input.name), ("description", input.description), ("api_key", input.api_key), ("api_base", input.api_base)) if value is not None}

    if input.additional_config is not None:
        changed["additional_config"] = _merge_config(provider.additional_config, input.additional_config)

    for field, value in changed.items():
        setattr(provider, field, value)

    if changed:
        await provider.asave(update_fields=list(changed))

    return provider


@strawberry.input(description="The provider whose model list should be re-synced")
class RefreshProviderInput:
    """The provider to re-list models for."""

    id: strawberry.ID


async def refresh_provider(info: Info, input: RefreshProviderInput) -> types.Provider:
    """Re-list the models a provider offers.

    Model listing otherwise only happens at provider creation, so a model added
    upstream after the fact was unreachable short of deleting and recreating
    the provider.
    """
    provider = await models.Provider.objects.for_organization(info.context.request.organization).aget(id=input.id)
    await logic.arefresh_provider_models(provider)
    return provider


@strawberry.input(description="The provider to delete")
class DeleteProviderInput:
    """The provider to remove, along with the models it offers."""

    id: strawberry.ID


async def delete_provider(info: Info, input: DeleteProviderInput) -> strawberry.ID:
    """Delete a provider of LLMs."""
    provider = await models.Provider.objects.for_organization(info.context.request.organization).aget(id=input.id)
    await provider.adelete()
    return input.id
