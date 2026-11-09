import logging

import aiohttp
import litellm
from asgiref.sync import sync_to_async
from litellm.types.utils import LlmProviders
from litellm.utils import ProviderConfigManager
from .models import LITELLM_PREFIX_BY_KIND, Provider, ProviderPartner, LLMModel
from .decision import backend_for, is_decision_kind
from .enums import FeatureType, ProviderKind
from django.conf import settings

logger = logging.getLogger(__name__)

#: Ceiling on a provider's model-listing call. Listing is a small request, so a
#: short timeout is right; without one a hung provider stalled the mutation.
LIST_MODELS_TIMEOUT_SECONDS = 60


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
        Provider.objects.for_write().update_or_create(
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

    # Every value here must exist in `llm.enums.FeatureType`, or serializing
    # LLMModel.features fails for the whole model.
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

    if is_decision_kind(provider_kind):
        return await arefresh_decision_models(provider)

    if provider_kind == ProviderKind.OLLAMA.value:
        timeout = aiohttp.ClientTimeout(total=LIST_MODELS_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{provider.api_base or settings.OLLAMA_URL}/api/tags") as res:
                if res.status != 200:
                    raise Exception("Ollama failed")
                data = await res.json()
                for model in data.get("models", []):
                    model_id = model["name"]
                    features = detect_features(model_id)
                    input_modalities, output_modalities = detect_modalities(model_id)
                    obj, _ = await LLMModel.objects.for_write().aupdate_or_create(
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
        timeout = aiohttp.ClientTimeout(total=LIST_MODELS_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
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
            obj, _ = await LLMModel.objects.for_write().aupdate_or_create(
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
            if provider_kind == ProviderKind.ANTHROPIC.value:
                model_ids = await alist_anthropic_models(provider)
            else:
                model_ids = await sync_to_async(list_litellm_models)(provider)
        except Exception as e:
            raise Exception(f"Failed to list models for {provider_kind} provider: {e}") from e

        for model_id in model_ids:
            features = detect_features(model_id)
            input_modalities, output_modalities = detect_modalities(model_id)
            obj, _ = await LLMModel.objects.for_write().aupdate_or_create(
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

    return new_models


def strip_routing_prefix(model_id: str, prefix: str) -> str:
    """Return ``model_id`` without litellm's ``<prefix>/`` routing prefix.

    ``LLMModel.llm_string`` adds the prefix itself, so a stored id that kept it
    would route to ``anthropic/anthropic/...``. litellm's listings and its
    static catalogue are inconsistent about including it.
    """
    return model_id.removeprefix(f"{prefix}/")


async def alist_anthropic_models(provider: Provider) -> list[str]:
    """List every model an Anthropic key can use, following pagination.

    litellm's own Anthropic listing reads one page of ``/v1/models`` (20 by
    default) and drops the rest, so it is listed here directly.
    """
    base = (provider.api_base or "https://api.anthropic.com").rstrip("/")
    headers = {"x-api-key": provider.api_key or "", "anthropic-version": "2023-06-01"}
    timeout = aiohttp.ClientTimeout(total=LIST_MODELS_TIMEOUT_SECONDS)
    model_ids: list[str] = []
    params = {"limit": "1000"}
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        while True:
            async with session.get(f"{base}/v1/models", params=params) as res:
                if res.status != 200:
                    raise Exception(f"Anthropic list models failed: {res.status} {await res.text()}")
                page = await res.json()
            model_ids.extend(model["id"] for model in page.get("data", []))
            if not page.get("has_more") or not page.get("last_id"):
                return model_ids
            params = {"limit": "1000", "after_id": page["last_id"]}


def list_litellm_models(provider: Provider) -> list[str]:
    """List a provider's models through litellm's per-provider model info.

    Errors from the provider (a bad key, an unreachable endpoint) propagate;
    litellm's catalogue is used only for providers it cannot list at all.
    """
    prefix = LITELLM_PREFIX_BY_KIND.get(provider.kind)
    if prefix is None:
        raise Exception(f"'{provider.kind}' providers cannot list their models")
    model_info = ProviderConfigManager.get_provider_model_info(model=None, provider=LlmProviders(prefix))
    try:
        if model_info is None:
            raise NotImplementedError
        listed = model_info.get_models(api_key=provider.api_key, api_base=provider.api_base)
    except NotImplementedError:
        listed = sorted(litellm.models_by_provider.get(prefix, []))
    return [strip_routing_prefix(model_id, prefix) for model_id in listed]


async def arefresh_decision_models(provider: Provider) -> list[LLMModel]:
    """List a decision provider's models through its backend.

    They are tagged ``decision`` only -- never ``chat`` -- so the litellm paths
    reject them and ``decide`` accepts them.
    """
    backend = backend_for(provider)
    new_models = []
    for info in await backend.list_models(provider):
        obj, _ = await LLMModel.objects.for_write().aupdate_or_create(
            provider=provider,
            model_id=info.name,
            defaults={
                "label": f"{backend.label} - {info.name}",
                "features": [FeatureType.DECISION.value],
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
        )
        new_models.append(obj)
    return new_models
