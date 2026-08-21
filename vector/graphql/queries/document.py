"""Similarity search over a collection."""

from typing import List

from kante.types import Info

from vector import gateway, inputs, models, types
from vector.embedding import aembed_texts


async def documents(info: Info, input: inputs.QueryInput) -> List[types.Document]:
    """Return the documents in a collection most similar to the query texts."""
    if not input.query_texts:
        raise ValueError("At least one query text must be provided.")

    db_collection = await models.ChromaCollection.objects.for_organization(info.context.request.organization).select_related("embedder__provider").aget(id=str(input.collection))

    query_embeddings = await aembed_texts(db_collection.embedder, input.query_texts)

    client = await gateway.aget_client()
    real_collection = await client.get_collection(name=db_collection.chroma_name)

    results = await real_collection.query(
        query_embeddings=query_embeddings,
        n_results=input.n_results,
        where=input.where,
    )

    if not results["ids"] or not results["documents"]:
        return []

    # Chroma nests one result list per query text, and the optional includes are
    # absent rather than empty when they were not requested.
    count = len(results["ids"][0])
    metadatas = results.get("metadatas") or [[None] * count]
    distances = results.get("distances") or [[None] * count]

    return [
        types.Document(id=id_, content=doc, _metadata=meta or {}, distance=dist)
        for id_, doc, meta, dist in zip(results["ids"][0], results["documents"][0], metadatas[0], distances[0])
    ]
