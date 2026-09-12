"""The ``documents`` similarity query returns results for *every* query text.

It used to index ``results[...][0]`` and silently drop the results for the
second and later ``queryTexts``."""

import pytest
from asgiref.sync import sync_to_async

from authentikate.models import Organization
from llm import models as llm_models
from vector import models as vector_models
from vector.graphql.queries import document as document_query


@sync_to_async
def seed():
    org = Organization.objects.get(slug="static_org")
    provider = llm_models.Provider.objects.for_write().create(name="OpenAI", organization=org, kind="openai")
    embedder = llm_models.LLMModel.objects.for_write().create(provider=provider, model_id="text-embedding-3-small", label="Embed", features=["embedding"])
    return vector_models.ChromaCollection.objects.for_write().create(name="docs", embedder=embedder, organization=org)


class FakeCollection:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def query(self, **kwargs):
        self.calls.append(kwargs)
        return self.results


class FakeClient:
    def __init__(self, collection):
        self.collection = collection

    async def get_collection(self, name):
        return self.collection


QUERY = """
    query Documents($input: QueryInput!) {
        documents(input: $input) { id content distance }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_documents_merges_results_of_all_query_texts(aexecute, monkeypatch):
    collection = await seed()
    fake = FakeCollection(
        {
            "ids": [["a", "b"], ["b", "c"]],
            "documents": [["A", "B"], ["B", "C"]],
            "distances": [[0.1, 0.5], [0.2, 0.9]],
            # no "metadatas": the optional include is absent when not requested
        }
    )

    async def fake_embed(embedder, texts, **kwargs):
        return [[0.0] * 3 for _ in texts]

    async def fake_client():
        return FakeClient(fake)

    monkeypatch.setattr(document_query, "aembed_texts", fake_embed)
    monkeypatch.setattr(document_query.gateway, "aget_client", fake_client)

    result = await aexecute(QUERY, {"input": {"collection": str(collection.id), "queryTexts": ["x", "y"], "nResults": 2}})

    assert result.data, result.errors
    docs = result.data["documents"]
    assert [d["id"] for d in docs] == ["a", "b", "c"]
    # "b" matched both query texts; the best distance wins.
    assert next(d for d in docs if d["id"] == "b")["distance"] == 0.2
    assert fake.calls[0]["n_results"] == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_documents_empty_result(aexecute, monkeypatch):
    collection = await seed()
    fake = FakeCollection({"ids": [[]], "documents": [[]], "distances": [[]]})

    async def fake_embed(embedder, texts, **kwargs):
        return [[0.0] * 3 for _ in texts]

    async def fake_client():
        return FakeClient(fake)

    monkeypatch.setattr(document_query, "aembed_texts", fake_embed)
    monkeypatch.setattr(document_query.gateway, "aget_client", fake_client)

    result = await aexecute(QUERY, {"input": {"collection": str(collection.id), "queryTexts": ["x"]}})
    assert result.data == {"documents": []}, result.errors
