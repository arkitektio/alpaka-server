import aiohttp
import litellm
from .models import Provider, LLMModel
from .enums import ProviderKind
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

    provider_kind = provider.kind

    if provider_kind == ProviderKind.OLLAMA.value:
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

    elif provider_kind == ProviderKind.OPENROUTER.value:
        # Use OpenRouter "user models" list (filtered to the API key / provider prefs)
        base = (provider.api_base.rstrip("/") if provider.api_base else "https://openrouter.ai/api/v1")
        url = f"{base}/models/user"
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as res:
                if res.status != 200:
                    text = await res.text()
                    raise Exception(f"OpenRouter list models failed: {res.status} {text}")
                data = await res.json()

        for model in data.get("data", []):
            model_id = model.get("id")
            if not model_id:
                continue
            features = detect_features(model_id)
            label = model.get("name") or model_id
            obj, _ = await LLMModel.objects.aupdate_or_create(
                provider=provider,
                model_id=model_id,
                defaults={
                    "label": f"OpenRouter - {label}",
                    "features": features,
                }
            )
            new_models.append(obj)

    else:
        try:
            # For all other providers, use LiteLLM's list_models
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
            raise Exception(f"Failed to list models for {provider_kind} provider: {e}")

    return new_models
