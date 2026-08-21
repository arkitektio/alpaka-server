"""Create, ensure and delete vector collections.

A collection exists in two places: a Django row carrying the human label,
owner, organization and embedder, and a Chroma collection holding the vectors.
The Django row is written first so its primary key can name the Chroma side —
see ``ChromaCollection.chroma_name`` for why the two names differ. If the Chroma
call then fails, the Django row is rolled back so the two never drift apart.
"""

import chromadb.errors
import strawberry
from django.db import IntegrityError
from kante.types import Info

from llm import models as llm_models
from vector import gateway, inputs, models, types


class EmbedderNotSuitable(Exception):
    """Raised when the model chosen to embed a collection cannot embed."""


class CollectionAlreadyExists(Exception):
    """Raised when the organization already has a collection of that name."""


async def _get_embedder(info: Info, embedder_id: str) -> llm_models.LLMModel:
    """Resolve an embedding-capable model belonging to the caller's organization."""
    embedder = await llm_models.LLMModel.objects.for_organization(info.context.request.organization).select_related("provider").aget(id=embedder_id)
    if not embedder.has_feature("embedding"):
        raise EmbedderNotSuitable(f"Model '{embedder.llm_string}' does not support embedding. Pick a model whose features include 'embedding'.")
    return embedder


async def create_collection(info: Info, input: inputs.ChromaCollectionInput) -> types.ChromaCollection:
    """Create a new collection in the vector database."""
    embedder = await _get_embedder(info, input.embedder)

    try:
        collection = await models.ChromaCollection.objects.for_write().acreate(
            name=input.name,
            description=input.description or "",
            owner=info.context.request.user,
            organization=info.context.request.organization,
            embedder=embedder,
        )
    except IntegrityError as e:
        raise CollectionAlreadyExists(f"A collection named '{input.name}' already exists in this organization. Use ensureCollection to update it in place.") from e

    try:
        client = await gateway.aget_client()
        await client.create_collection(name=collection.chroma_name)
    except Exception:
        # Never leave a Django row pointing at a Chroma collection that was not
        # created — the row would resolve but every query against it would fail.
        await collection.adelete()
        raise

    return collection


async def ensure_collection(info: Info, input: inputs.ChromaCollectionInput) -> types.ChromaCollection:
    """Create a collection if it does not exist yet, otherwise update it in place."""
    embedder = await _get_embedder(info, input.embedder)

    collection, created = await models.ChromaCollection.objects.for_write().aupdate_or_create(
        organization=info.context.request.organization,
        name=input.name,
        defaults=dict(
            description=input.description or "",
            owner=info.context.request.user,
            embedder=embedder,
        ),
    )

    try:
        client = await gateway.aget_client()
        # Idempotent by contract, so the Chroma side is reconciled on every call
        # rather than only when the Django row was newly created.
        await client.get_or_create_collection(name=collection.chroma_name)
    except Exception:
        if created:
            await collection.adelete()
        raise

    return collection


async def delete_collection(info: Info, input: inputs.DeleteCollectionInput) -> strawberry.ID:
    """Delete a collection from both the vector database and the metadata store."""
    collection = await models.ChromaCollection.objects.for_organization(info.context.request.organization).aget(id=input.id)
    chroma_name = collection.chroma_name

    client = await gateway.aget_client()
    try:
        await client.delete_collection(name=chroma_name)
    except (chromadb.errors.NotFoundError, ValueError):
        # Already gone from Chroma — drop the metadata row anyway so the two
        # sides converge instead of leaving an unusable collection behind.
        # ValueError is caught too: some chromadb versions raise a bare
        # ValueError("Collection ... does not exist") here rather than
        # NotFoundError, and guessing wrong turns "already gone" into a 500.
        pass

    await collection.adelete()
    return input.id
