"""Collection lookups.

Only the singular fetcher lives here — the list field is a plain
``strawberry_django.field()`` declaration, scoped by ``ChromaCollection``\'s
``get_queryset`` classmethod.
"""

import strawberry
from kante.types import Info

from alpaka_server.scoping import held_to_guest
from vector import models, types


def chroma_collection(info: Info, id: strawberry.ID) -> types.ChromaCollection:
    """Get a single Chroma collection by ID."""
    return held_to_guest(models.ChromaCollection.objects.for_organization(info.context.request.organization), info).get(id=id)
