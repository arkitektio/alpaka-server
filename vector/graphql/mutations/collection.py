import strawberry
from typing import Optional, List

from kante.types import Info
from django.conf import settings

from llm import models as llm_models
from vector import models, types, enums, filters, inputs, gateway

from typing import List
import chromadb



async def create_collection(info: Info, input: inputs.ChromaCollectionInput) -> types.ChromaCollection:
    """ Create a new collection in the vector database """
    
    embedder = await llm_models.LLMModel.objects.aget(id=input.embedder)
    assert embedder.has_feature("embedding"), "Model does not support embedding"
    
    collection = await models.ChromaCollection.objects.acreate(
        name=input.name,
        description=input.description,
        owner=info.context.request.user,
        embedder=embedder,  # type: ignore
    )
    
    
    try:
        client = await gateway.aget_client()
        await client.create_collection(name=input.name)
    except chromadb.errors.CollectionAlreadyExists:
        collection.delete()
        raise Exception("Collection already exists")
    
    
    return collection
    
async def ensure_collection(info: Info, input: inputs.ChromaCollectionInput) -> types.ChromaCollection:
    """ Create a new collection in the vector database """
    
    
    embedder = await llm_models.LLMModel.objects.aget(id=input.embedder)  # type: ignore
    assert embedder.has_feature("embedding"), "Model does not support embedding"
    
    collection, created = await models.ChromaCollection.objects.aupdate_or_create(
        name=input.name,
        defaults=dict(
            description=input.description,
            owner=info.context.request.user,
            embedder=embedder,  # type: ignore
        )
    )
    
    if created:
        try:
            client = await gateway.aget_client()
            await client.create_collection(name=input.name)
        except chromadb.errors.CollectionAlreadyExists:
            collection.delete()
            raise Exception("Collection already exists")
    
    
    return collection  
    
async def delete_collection(info: Info, input: inputs.AddDocumentsToCollectionInput) -> strawberry.ID:
    """ Delete a collection in the vector database """
    
    collection = await models.ChromaCollection.objects.aget(id=input.id)
    
    
    
    try:
        client = await gateway.aget_client()
        await client.create_collection(name=collection.name)
    except chromadb.errors.CollectionNotFound:
        raise Exception("Collection not found in vector database")
    
    
    
    collection.delete()
    return input.id
    
        
        
        
