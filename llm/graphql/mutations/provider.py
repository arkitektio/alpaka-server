from llm import models, types, inputs, logic
import strawberry
from kante.types import Info


DEFAULT_API_BASE_MAP = {
    models.ProviderKind.OPENROUTER: "https://openrouter.ai/api/v1",
}


async def create_provider(info: Info, input: inputs.ProviderInput) -> types.Provider:
    """Create a new provider of LLMs"""
    provider, _ = await models.Provider.objects.aupdate_or_create(
        name=input.name or input.kind,
        api_key=input.api_key,
        defaults=dict(
            kind=input.kind,
            api_base=input.api_base or DEFAULT_API_BASE_MAP[input.kind],
            additional_config=input.additional_config,
            creator=info.context.request.user,
            description=input.description or "No description provided",
        )
    )

    await logic.arefresh_provider_models(provider)
    return provider


def delete_provider(info: Info, id: strawberry.ID) -> strawberry.ID:
    """Delete a provider of LLMs"""
    x = models.Provider.objects.get(id=id)
    x.delete
    return id
