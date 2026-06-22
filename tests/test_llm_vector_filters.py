"""Tests for the new ``filter_type`` API on the llm (Provider, LLMModel) and
vector (ChromaCollection) types — including the search field, which previously
filtered on a non-existent ``title`` column."""

import pytest
from asgiref.sync import sync_to_async

from authentikate.models import Organization
from llm import models as llm_models
from vector import models as vector_models


@sync_to_async
def seed():
    org = Organization.objects.get(slug="static_org")

    openai = llm_models.Provider.objects.create(name="OpenAI", organization=org)
    ollama = llm_models.Provider.objects.create(name="Ollama", organization=org)

    gpt = llm_models.LLMModel.objects.create(
        provider=openai,
        model_id="gpt-4",
        label="GPT-4",
        input_modalities=["text", "image"],
        output_modalities=["text"],
    )
    whisper = llm_models.LLMModel.objects.create(
        provider=openai,
        model_id="whisper-1",
        label="Whisper",
        input_modalities=["audio"],
        output_modalities=["text"],
    )

    collection = vector_models.ChromaCollection.objects.create(name="recipes", embedder=gpt)
    vector_models.ChromaCollection.objects.create(name="weather", embedder=gpt)

    return {
        "org": org,
        "providers": {"openai": openai, "ollama": ollama},
        "models": {"gpt": gpt, "whisper": whisper},
        "collection": collection,
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_provider_filter_search(aexecute):
    """``search`` matches the Provider ``name`` (previously a broken ``title`` lookup)."""
    await seed()

    query = """
        query Providers($filters: ProviderFilter) {
            providers(filters: $filters) {
                name
            }
        }
    """

    result = await aexecute(query, {"filters": {"search": "openai"}})

    assert result.data, result.errors
    assert [p["name"] for p in result.data["providers"]] == ["OpenAI"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_provider_filter_ids(aexecute):
    """``ids`` restricts providers to the given primary keys."""
    data = await seed()

    query = """
        query Providers($filters: ProviderFilter) {
            providers(filters: $filters) {
                id
            }
        }
    """

    result = await aexecute(query, {"filters": {"ids": [str(data["providers"]["ollama"].id)]}})

    assert result.data, result.errors
    assert [p["id"] for p in result.data["providers"]] == [str(data["providers"]["ollama"].id)]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_llm_model_filter_search(aexecute):
    """``search`` matches the LLMModel ``label``."""
    await seed()

    query = """
        query Models($filters: LLMModelFilter) {
            llmModels(filters: $filters) {
                label
            }
        }
    """

    result = await aexecute(query, {"filters": {"search": "whisper"}})

    assert result.data, result.errors
    assert [m["label"] for m in result.data["llmModels"]] == ["Whisper"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_llm_model_filter_input_modalities(aexecute):
    """``inputModalities`` keeps only models whose JSON list contains the values."""
    await seed()

    query = """
        query Models($filters: LLMModelFilter) {
            llmModels(filters: $filters) {
                label
            }
        }
    """

    result = await aexecute(query, {"filters": {"inputModalities": ["IMAGE"]}})

    assert result.data, result.errors
    assert [m["label"] for m in result.data["llmModels"]] == ["GPT-4"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_chroma_collection_filter_search(aexecute):
    """``search`` matches the ChromaCollection ``name`` (previously a broken ``title`` lookup)."""
    await seed()

    query = """
        query Collections($filters: ChromaCollectionFilter) {
            chromaCollections(filters: $filters) {
                name
            }
        }
    """

    result = await aexecute(query, {"filters": {"search": "recipes"}})

    assert result.data, result.errors
    assert [c["name"] for c in result.data["chromaCollections"]] == ["recipes"]
