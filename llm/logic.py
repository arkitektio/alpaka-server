import aiohttp
import litellm
from .models import Provider, LLMModel
from django.conf import settings


def detect_features(model_id: str) -> list[str]:
    """Detect features supported by the model based on its ID/name."""
    features = []

    if "embed" in model_id or model_id.startswith("text-embedding"):
        features.append("embedding")
    else:
        features.append("chat")

    if "vision" in model_id or "gpt-4-vision" in model_id:
        features.append("vision")

    return features


async def arefresh_provider_models(provider: Provider) -> list[LLMModel]:
    """Refresh the models for a given provider."""
    new_models = []

    if provider.name == "ollama":
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{provider.api_base or settings.OLLAMA_URL}/api/tags") as res:
                if res.status != 200:
                    raise Exception("Ollama failed")
                data = await res.json()
                for model in data.get("models", []):
                    model_id = model["name"]
                    features = detect_features(model_id)
                    obj, _ = await LLMModel.objects.aupdate_or_create(
                        provider=provider,
                        model_id=model_id,
                        defaults={
                            "label": f"Ollama - {model_id}",
                            "features": features,
                        }
                    )
                    new_models.append(obj)

    else:
        try:
            models = litellm.list_models(api_key=provider.api_key, api_base=provider.api_base)
            for model in models.get("data", []):
                model_id = model["id"]
                features = detect_features(model_id)
                obj, _ = await LLMModel.objects.aupdate_or_create(
                    provider=provider,
                    model_id=model_id,
                    defaults={
                        "label": f"{provider.name} - {model_id}",
                        "features": features,
                    }
                )
                new_models.append(obj)
        except Exception as e:
            raise Exception(f"Failed to list models: {e}")

    return new_models
