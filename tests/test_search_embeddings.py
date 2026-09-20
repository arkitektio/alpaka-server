"""Rooms and Chroma collections embed their title/name + description on save; ``search`` is hybrid.

Real model (potion-base-8M), real Postgres with pgvector -- what the service runs. Where a
test needs rows at *known* distances from the query it writes the vectors directly: ``e0`` is
the real embedding of the query, ``_vec(d)`` a unit vector at cosine distance ``d`` from it.
The Chroma *documents* are untouched by any of this: only the collection's metadata row embeds.
"""

import math

import numpy as np
import pytest
from asgiref.sync import sync_to_async
from django.test import override_settings

from authentikate.models import Organization, User
from embeddings import engine
from embeddings.healer import reembed_all, reembed_stale
from kammer import models as kammer_models
from llm import models as llm_models
from vector import models as vector_models

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

QUERY = "detect cells"

ROOMS = """
query ($filters: RoomFilter, $ordering: [RoomOrder!]) {
  rooms(filters: $filters, ordering: $ordering) { title }
}
"""
COLLECTIONS = """
query ($filters: ChromaCollectionFilter, $ordering: [ChromaCollectionOrder!]) {
  chromaCollections(filters: $filters, ordering: $ordering) { name }
}
"""


@sync_to_async
def _room(title: str, description: str | None = None) -> kammer_models.Room:
    org = Organization.objects.get(slug="static_org")
    user = User.objects.get(sub="1", iss="static_issuer")
    return kammer_models.Room.objects.for_write().create(title=title, description=description, organization=org, creator=user)


@sync_to_async
def _collection(name: str, description: str | None = None) -> vector_models.ChromaCollection:
    org = Organization.objects.get(slug="static_org")
    provider, _ = llm_models.Provider.objects.for_write().get_or_create(name="OpenAI", organization=org, defaults={"kind": "openai"})
    embedder, _ = llm_models.LLMModel.objects.for_write().get_or_create(provider=provider, model_id="text-embedding-3-small", defaults={"label": "Embed", "features": ["embedding"]})
    return vector_models.ChromaCollection.objects.for_write().create(name=name, description=description or "", embedder=embedder, organization=org)


MODELS = [
    pytest.param(kammer_models.Room, _room, ROOMS, "title", id="room"),
    pytest.param(vector_models.ChromaCollection, _collection, COLLECTIONS, "name", id="chroma_collection"),
]


def _unit_orthogonal(e0: np.ndarray) -> np.ndarray:
    axis = np.zeros_like(e0)
    axis[int(np.argmin(np.abs(e0)))] = 1.0
    u = axis - float(np.dot(axis, e0)) * e0
    return u / np.linalg.norm(u)


def _vec(e0: np.ndarray, distance: float) -> list[float]:
    theta = math.acos(1.0 - distance)
    return (math.cos(theta) * e0 + math.sin(theta) * _unit_orthogonal(e0)).astype(float).tolist()


async def _pin(model, row, e0, distance, embedding_model=None):
    await model.all_objects.filter(pk=row.pk).aupdate(embedding=_vec(e0, distance) if distance is not None else None, embedding_model=embedding_model or engine.model_id())


async def _labels(aexecute, query, label, search, ordering=None):
    res = await aexecute(query, {"filters": {"search": search}, "ordering": ordering or []})
    assert not res.errors, res.errors
    return [row[label] for row in next(iter(res.data.values()))]


@pytest.mark.parametrize(("model", "seed", "query", "label"), MODELS)
async def test_create_embeds(authenticated_context, model, seed, query, label):
    row = await seed("Segment nuclei", "Find cell nuclei in a fluorescence image")
    await row.arefresh_from_db()
    assert row.embedding is not None and len(row.embedding) == 256
    assert abs(sum(x * x for x in row.embedding) - 1.0) < 1e-4
    assert row.embedding_model == engine.model_id()


async def test_blank_text_stores_null_and_is_complete(authenticated_context):
    row = await _room("  ", None)
    await row.arefresh_from_db()
    assert row.embedding is None and row.embedding_model == engine.model_id()
    assert await sync_to_async(reembed_stale)(kammer_models.Room) == 0


async def test_healer_reembeds_rows_of_another_model(authenticated_context):
    room = await _room("Blur", "Gaussian blur of an image")
    coll = await _collection("papers", "Blur-related papers")
    for model, row in ((kammer_models.Room, room), (vector_models.ChromaCollection, coll)):
        await model.all_objects.filter(pk=row.pk).aupdate(embedding=None, embedding_model="some/older-model")
    assert await sync_to_async(reembed_all)([kammer_models.Room, vector_models.ChromaCollection]) == 2
    for model, row in ((kammer_models.Room, room), (vector_models.ChromaCollection, coll)):
        fresh = await model.all_objects.aget(pk=row.pk)
        assert fresh.embedding is not None and fresh.embedding_model == engine.model_id()


@pytest.mark.parametrize(("model", "seed", "query", "label"), MODELS)
async def test_semantic_match_without_substring(aexecute, authenticated_context, model, seed, query, label):
    await seed("Segment nuclei", "Find cell nuclei in a fluorescence image and detect every cell")
    await seed("Export spreadsheet", "Write a table to an xlsx file on disk")
    labels = await _labels(aexecute, query, label, QUERY)
    assert "Segment nuclei" in labels and "Export spreadsheet" not in labels


@pytest.mark.parametrize(("model", "seed", "query", "label"), MODELS)
async def test_lexical_only_when_disabled(aexecute, authenticated_context, model, seed, query, label):
    await seed("Detect cells", None)
    await seed("Segment nuclei", "detect cells in an image")
    with override_settings(EMBEDDINGS={**engine._settings(), "ENABLED": False}):
        assert await _labels(aexecute, query, label, QUERY) == ["Detect cells"]


@pytest.mark.parametrize(("model", "seed", "query", "label"), MODELS)
async def test_ranking_lexical_first_then_by_distance(aexecute, authenticated_context, model, seed, query, label):
    e0 = np.asarray(engine.embed_query(QUERY))
    await _pin(model, await seed("Far"), e0, 0.5)
    await _pin(model, await seed("Near"), e0, 0.1)
    await _pin(model, await seed("Mid"), e0, 0.3)
    await _pin(model, await seed("Beyond"), e0, 0.7)
    await _pin(model, await seed("Detect cells here"), e0, None)
    assert await _labels(aexecute, query, label, QUERY) == ["Detect cells here", "Near", "Mid", "Far"]


@pytest.mark.parametrize(("model", "seed", "query", "label"), MODELS)
async def test_stale_embedding_model_is_not_a_vector_hit(aexecute, authenticated_context, model, seed, query, label):
    e0 = np.asarray(engine.embed_query(QUERY))
    await _pin(model, await seed("Old model near"), e0, 0.05, "some/older-model")
    await _pin(model, await seed("Old model detect cells"), e0, 0.05, "some/older-model")
    assert await _labels(aexecute, query, label, QUERY) == ["Old model detect cells"]


@pytest.mark.parametrize(("model", "seed", "query", "label"), MODELS)
async def test_explicit_ordering_replaces_the_ranking(aexecute, authenticated_context, model, seed, query, label):
    e0 = np.asarray(engine.embed_query(QUERY))
    await _pin(model, await seed("Zeta"), e0, 0.1)
    await _pin(model, await seed("Alpha"), e0, 0.4)
    assert await _labels(aexecute, query, label, QUERY) == ["Zeta", "Alpha"]
    assert await _labels(aexecute, query, label, QUERY, ordering=[{label: "ASC"}]) == ["Alpha", "Zeta"]


async def test_unloadable_model_degrades_to_substring(aexecute, authenticated_context):
    e0 = np.asarray(engine.embed_query(QUERY))
    await _pin(kammer_models.Room, await _room("Near"), e0, 0.05)
    await _room("Detect cells")
    try:
        with override_settings(EMBEDDINGS={**engine._settings(), "MODEL_PATH": "/nonexistent/embeddings"}):
            engine.reset()
            assert await _labels(aexecute, ROOMS, "title", QUERY) == ["Detect cells"]
    finally:
        engine.reset()
