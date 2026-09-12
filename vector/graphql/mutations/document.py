"""Add documents to a collection, embedding them with the collection's embedder."""

import uuid
from typing import Any, Dict, List

from kante.types import Info

from llm.models import LLMModel
from vector import gateway, inputs, models, types
from vector.embedding import aembed_texts


async def _prepare(documents: List[inputs.DocumentInput], embedder: LLMModel, *, user: Any = None, client: Any = None) -> Dict[str, Any]:
    """Embed the documents and shape them into the payload Chroma expects."""
    contents = [document.content for document in documents]
    metadatas: List[Dict[str, Any]] = [dict(document.metadata or {}) for document in documents]
    ids = [document.id or str(uuid.uuid4()) for document in documents]

    for index, document in enumerate(documents):
        if document.structure:
            metadatas[index] = {
                **metadatas[index],
                "identifier": document.structure.identifier,
                "object": document.structure.object,
            }

    embeddings = await aembed_texts(embedder, contents, user=user, client=client)

    return {
        "documents": contents,
        "metadatas": metadatas,
        "ids": ids,
        "embeddings": embeddings,
    }


async def add_documents_to_collection(info: Info, input: inputs.AddDocumentsToCollectionInput) -> List[types.Document]:
    """Add documents to a collection in the vector database."""
    if not input.documents:
        raise ValueError("No documents provided")

    collection = await models.ChromaCollection.objects.for_organization(info.context.request.organization).select_related("embedder__provider").aget(id=input.collection)

    payload = await _prepare(input.documents, collection.embedder, user=info.context.request.user, client=info.context.request.client)

    client = await gateway.aget_client()
    real_collection = await client.get_collection(name=collection.chroma_name)
    await real_collection.add(**payload)

    # Return what was actually written. The previous implementation declared a
    # list of documents and unconditionally returned [], so a caller had no way
    # to learn the generated ids.
    return [
        types.Document(id=id_, content=content, _metadata=metadata, distance=None)
        for id_, content, metadata in zip(payload["ids"], payload["documents"], payload["metadatas"])
    ]
