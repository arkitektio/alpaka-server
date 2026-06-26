import logging

import aiohttp
import litellm
from .models import Provider, ProviderPartner, LLMModel
from .enums import ProviderKind
from django.conf import settings

logger = logging.getLogger(__name__)


def auto_configure_provider_partners(organization) -> list[str]:
    """Provision a :class:`Provider` for ``organization`` from every auto-config partner.

    Mirrors lok's ``auto_configure_kommunity_partners``. Runs on organization
    creation (see ``llm.signals``). Kept pure sync ORM with **no network calls**:
    it executes inside the auth request path (possibly within an async ORM context),
    so model listing is refreshed separately, not here.
    """
    applied: list[str] = []

    for partner in ProviderPartner.objects.filter(auto_configure=True):
        # alpaka's Organization has no owner, so there is no user to filter on here;
        # filter_config is honoured by Provider creation paths that do have a user.
        Provider.objects.update_or_create(
            organization=organization,
            name=partner.name,
            defaults=dict(
                kind=partner.kind,
                api_key=partner.api_key,
                api_base=partner.api_base,
                additional_config=partner.additional_config,
                description=partner.description or "Auto-provisioned from partner",
                partner=partner,
            ),
        )
        logger.info("Auto-configured provider '%s' for organization '%s'", partner.identifier, organization)
        applied.append(partner.identifier)

    return applied


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


def detect_modalities(model_id: str, model_data: dict | None = None) -> tuple[list[str], list[str]]:
    """Detect modalities supported by the model based on its ID/name or data."""
    input_modalities = ["text"]
    output_modalities = ["text"]

    if model_data:
        architecture = model_data.get("architecture")
        if architecture:
            modality = architecture.get("modality")
            if modality:
                # Example: "text+image->text"
                if "->" in modality:
                    inputs, outputs = modality.split("->")
                    if "image" in inputs:
                        input_modalities.append("image")
                    if "audio" in inputs:
                        input_modalities.append("audio")

                    if "image" in outputs:
                        output_modalities.append("image")
                    if "audio" in outputs:
                        output_modalities.append("audio")

                return list(set(input_modalities)), list(set(output_modalities))

    # Fallback to ID based detection
    if "vision" in model_id or "gpt-4-vision" in model_id or "claude-3" in model_id or "gpt-4o" in model_id:
        input_modalities.append("image")

    if "dall-e" in model_id or "stable-diffusion" in model_id:
        output_modalities.append("image")

    return list(set(input_modalities)), list(set(output_modalities))


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
                    input_modalities, output_modalities = detect_modalities(model_id)
                    obj, _ = await LLMModel.objects.aupdate_or_create(
                        provider=provider,
                        model_id=model_id,
                        defaults={
                            "label": f"Ollama - {model_id}",
                            "features": features,
                            "input_modalities": input_modalities,
                            "output_modalities": output_modalities,
                        },
                    )
                    new_models.append(obj)

    elif provider_kind == ProviderKind.OPENROUTER.value:
        # Use OpenRouter "user models" list (filtered to the API key / provider prefs)
        base = provider.api_base.rstrip("/") if provider.api_base else "https://openrouter.ai/api/v1"
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
            input_modalities, output_modalities = detect_modalities(model_id, model)
            label = model.get("name") or model_id
            obj, _ = await LLMModel.objects.aupdate_or_create(
                provider=provider,
                model_id=model_id,
                defaults={
                    "label": f"OpenRouter - {label}",
                    "features": features,
                    "input_modalities": input_modalities,
                    "output_modalities": output_modalities,
                },
            )
            new_models.append(obj)

    else:
        try:
            # For all other providers, use LiteLLM's list_models
            models = litellm.list_models(api_key=provider.api_key, api_base=provider.api_base)
            for model in models.get("data", []):
                model_id = model["id"]
                features = detect_features(model_id)
                input_modalities, output_modalities = detect_modalities(model_id, model)
                obj, _ = await LLMModel.objects.aupdate_or_create(
                    provider=provider,
                    model_id=model_id,
                    defaults={
                        "label": f"{provider.name} - {model_id}",
                        "features": features,
                        "input_modalities": input_modalities,
                        "output_modalities": output_modalities,
                    },
                )
                new_models.append(obj)
        except Exception as e:
            raise Exception(f"Failed to list models for {provider_kind} provider: {e}")

    return new_models
