"""GraphQL types for the vector app."""

import datetime
import logging
from typing import Annotated

import strawberry
import strawberry_django
from authentikate.strawberry.types import User
from strawberry import scalars
from strawberry.types import Info

from alpaka_server.descriptors import DESCRIPTORS_DESCRIPTION, resolve_descriptors
from alpaka_server.scoping import held_to_guest
from vector import filters, gateway, models

logger = logging.getLogger(__name__)


@strawberry.type(
    description="A reference to an object held by another Arkitekt service"
)
class Structure:
    """A structure definition for a large language model."""

    identifier: str
    object: int


@strawberry.type(description="A document stored in a collection")
class Document:
    """A document, with its similarity distance when it came from a query."""

    _metadata: strawberry.Private[dict]
    id: str
    content: str
    distance: float | None = None

    @strawberry.field(description="The metadata stored alongside the document")
    def metadata(self) -> scalars.JSON | None:
        """Get the metadata for the document."""
        return self._metadata

    @strawberry.field(description="The object this document was derived from, if any")
    def structure(self) -> Structure | None:
        """Get the structure for the document."""
        if self._metadata and "identifier" in self._metadata:
            return Structure(
                identifier=self._metadata["identifier"],
                object=int(self._metadata["object"]),
            )
        return None


@strawberry_django.type(
    models.ChromaCollection,
    description="A collection of documents searchable by string",
    filters=filters.ChromaCollectionFilter,
    ordering=filters.ChromaCollectionOrder,
    pagination=True,
)
class ChromaCollection:
    """A collection of documents searchable by string."""

    @classmethod
    def get_queryset(cls, queryset, info, **kwargs):
        """Restrict every read of this type to the request's organization (a guest: their collaborations)."""
        return held_to_guest(
            queryset.filter(organization=info.context.request.organization), info
        )

    descriptors: scalars.JSON = strawberry_django.field(
        resolver=resolve_descriptors, description=DESCRIPTORS_DESCRIPTION
    )
    id: strawberry.ID
    name: str
    description: str
    created_at: datetime.datetime
    owner: User | None
    embedder: Annotated["LLMModel", strawberry.lazy("llm.types")] = (
        strawberry_django.field(
            description="The model used to embed this collection's documents"
        )
    )

    @strawberry_django.field(
        description="The number of documents stored in this collection, or null if the vector database cannot be reached"
    )
    async def count(self, info: Info) -> int | None:
        """Count the documents held in the vector database for this collection.

        Nullable on purpose: this is the one field that leaves the database to
        answer, and a Chroma outage — or a single row whose Chroma side is
        missing — must not fail the entire collection list.
        """
        try:
            client = await gateway.aget_client()
            real_collection = await client.get_collection(name=self.chroma_name)
            return await real_collection.count()
        except Exception:
            logger.warning(
                "Could not count collection %s in the vector database",
                self.chroma_name,
                exc_info=True,
            )
            return None
