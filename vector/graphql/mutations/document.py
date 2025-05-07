import strawberry
from typing import Optional, List

from kante.types import Info
from django.conf import settings
from litellm import aembedding
from vector import models, types, enums, filters, inputs, gateway
from llm import models as llm_models
from typing import List
import chromadb
import uuid


async def embed_documents(documents: list[inputs.DocumentInput], embedder: llm_models.LLMModel) -> dict:
    
    
    rdocuments = [document.content for document in documents]
    metadata = [document.metadata or {} for document in documents]
    ids = [document.id or str(uuid.uuid4()) for document in documents]
    structures = [document.structure for document in documents]
    
    embedding_response = await aembedding(embedder.llm_string, rdocuments, api_base=settings.OLLAMA_URL,
        stream=False,)
    
    embeddings = [x["embedding"] for x in embedding_response.data]
    
    for i, structure in enumerate(structures):
        if structure:
            metadata[i] = {**metadata[i], "identifier": structure.identifier, "object": structure.object}
    
    return {
        "documents": rdocuments,
        "metadatas": metadata,
        "ids": ids,
        "embeddings": embeddings,
    }
    



async def add_documents_to_collection(
    info: Info, input: inputs.AddDocumentsToCollectionInput
) -> list[types.Document]:
    """ Add documents to a collection in the vector database """
    
    collection = await models.ChromaCollection.objects.prefetch_related("embedder__provider").aget(id=input.collection)
    
    client = await gateway.aget_client()
    
    real_collection =  await client.get_collection(name=collection.name)
    
    # Check if the collection exists
    if not collection:
        raise Exception("Collection not found")
    
    # Check if the documents are valid
    if not input.documents:
        raise Exception("No documents provided")
    
    
    
    embeded_documents = await embed_documents(input.documents, collection.embedder)
    
    
    await real_collection.add(**embeded_documents)
    
    
    
    return []