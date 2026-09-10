"""Similarity search over a collection."""

from typing import List

from kante.types import Info

from vector import gateway, inputs, models, types
from vector.embedding import aembed_texts


async def documents(info: Info, input: inputs.QueryInput) -> List[types.Document]:
    """Return the documents in a collection most similar to any of the query texts.

    Chroma answers with one result list per query text. Those lists are merged:
    a document that matches several query texts is returned once, with the best
    (lowest) distance it achieved, and the union is sorted by distance.
    """
    if not input.query_texts:
        raise ValueError("At least one query text must be provided.")

    db_collection = await models.ChromaCollection.objects.for_organization(info.context.request.organization).select_related("embedder__provider").aget(id=str(input.collection))

    query_embeddings = await aembed_texts(db_collection.embedder, input.query_texts, user=info.context.request.user, client=info.context.request.client)

    client = await gateway.aget_client()
    real_collection = await client.get_collection(name=db_collection.chroma_name)

    results = await real_collection.query(
        query_embeddings=query_embeddings,
        n_results=input.n_results,
        where=input.where,
    )

    if not results["ids"] or not results["documents"]:
        return []

    # The optional includes are absent (not empty) when they were not requested.
    n_queries = len(results["ids"])
    all_metadatas = results.get("metadatas") or [None] * n_queries
    all_distances = results.get("distances") or [None] * n_queries

    best: dict[str, types.Document] = {}
    for q, ids in enumerate(results["ids"]):
        docs = results["documents"][q]
        metadatas = all_metadatas[q] or [None] * len(ids)
        distances = all_distances[q] or [None] * len(ids)
        for id_, doc, meta, dist in zip(ids, docs, metadatas, distances):
            current = best.get(id_)
            if current is None or (dist is not None and (current.distance is None or dist < current.distance)):
                best[id_] = types.Document(id=id_, content=doc, _metadata=meta or {}, distance=dist)

    return sorted(best.values(), key=lambda d: (d.distance is None, d.distance or 0.0))
