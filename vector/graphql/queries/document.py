import strawberry
from typing import Optional, List
from kante.types import Info
from django.conf import settings
from vector import models, types, gateway, inputs
from strawberry import scalars
from litellm import aembedding

async def documents(
    info: Info,
    collection: strawberry.ID,
    query_texts: Optional[List[str]] = None,
    n_results: Optional[int] = 3,
    where: Optional[scalars.JSON] = None,
) -> List[types.Document]:
    # Get DB collection
    db_coll = await models.ChromaCollection.objects.prefetch_related("embedder__provider").aget(id=str(collection))
    
    

    response = await aembedding(
        db_coll.embedder.llm_string,
        query_texts,
        api_base=settings.OLLAMA_URL,
        stream=False,
    )

    # Get vector DB client and collection
    client = await gateway.aget_client()
    real_collection = await client.get_collection(name=db_coll.name)

    # ChromaDB expects at least one query text
    if not query_texts:
        raise ValueError("At least one query text must be provided.")
    
   
    query_embeddings = [x["embedding"] for x in response.data]  
    
    print("THEE COUNT", await real_collection.count())

    results = await real_collection.query(
        query_embeddings=query_embeddings,
        n_results=n_results or 3,
        where=where
    )
    
    print(f"Results: {results}")

    # Ensure we have results to unpack
    if not results["ids"] or not results["documents"]:
        return []

    return [
        types.Document(
            id=id_,
            content=doc,
            _metadata=meta,
            distance=dist,
        )
        for id_, doc, meta, dist in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
    ]
