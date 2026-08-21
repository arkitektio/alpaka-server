"""Input types for the vector app."""

from typing import List, Optional

import strawberry
from strawberry import scalars


@strawberry.input(description="A reference to an object held by another Arkitekt service")
class StructureInput:
    """A structure definition for a large language model."""

    identifier: str
    object: int


@strawberry.input(description="A document to put into the vector database")
class DocumentInput:
    """A document input for a large language model."""

    content: str
    structure: StructureInput | None = None
    id: str | None = None
    metadata: Optional[scalars.JSON] = None


@strawberry.input(description="A similarity query against a collection")
class QueryInput:
    """A query input for a large language model."""

    collection: strawberry.ID
    query_texts: List[str]
    n_results: int = 3
    where: Optional[scalars.JSON] = None


@strawberry.input(description="Documents to add to an existing collection")
class AddDocumentsToCollectionInput:
    """The documents to embed and store, and the collection to store them in."""

    collection: strawberry.ID
    documents: List[DocumentInput]


@strawberry.input(description="A collection of documents searchable by string")
class ChromaCollectionInput:
    """The collection to create, and the model used to embed its documents."""

    name: str
    embedder: strawberry.ID
    description: Optional[str] = None


@strawberry.input(description="The collection to delete")
class DeleteCollectionInput:
    """The collection to remove from both the vector database and the metadata store."""

    id: strawberry.ID
