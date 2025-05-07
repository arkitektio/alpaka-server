from llm import models, types, inputs, logic
import strawberry
from kante.types import Info


async def create_provider(info: Info, input: inputs.ProviderInput) -> types.Provider:
    """Create a new provider of LLMs"""
    provider, _ = await models.Provider.objects.aupdate_or_create(
        name=input.name,
        api_key=input.api_key,
        defaults=dict(
            api_base=input.api_base,
            additional_config=input.additional_config,
            creator=info.context.request.user,
            description=input.description,
        )
    )

    await logic.arefresh_provider_models(provider)
    return provider


def delete_provider(info: Info, id: strawberry.ID) -> strawberry.ID:
    """Delete a provider of LLMs"""
    x = models.Provider.objects.get(id=id)
    x.delete
    return id
