import aiohttp
import litellm
from .models import Provider, LLMModel


async def arefresh_provider_models(provider: Provider) -> list[LLMModel]:
    """Refresh the models for a given provider."""
    new_models = []

    if provider.name == "ollama":
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{provider.api_base or 'http://ollama:11434'}/api/tags") as res:
                if res.status != 200:
                    raise Exception("Ollama failed")
                data = await res.json()
                for model in data.get("models", []):
                    obj, _ = LLMModel.objects.update_or_create(provider=provider, model_id=model["name"], defaults={"label": f"Ollama - {model['name']}"})
                    new_models.append(obj)

    else:
        try:
            models = litellm.list_models(api_key=provider.api_key, api_base=provider.api_base)
            for model in models.get("data", []):
                obj, _ = LLMModel.objects.update_or_create(provider=provider, model_id=model["id"], defaults={"label": f"{provider.name} - {model['id']}"})
                new_models.append(obj)
        except Exception as e:
            raise Exception(f"Failed to list models: {e}")

    return new_models
