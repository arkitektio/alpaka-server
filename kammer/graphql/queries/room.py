"""Room and message lookups.

Only the singular fetchers live here — the list fields are plain
``strawberry_django.field()`` declarations, scoped by each type's
``get_queryset`` classmethod.
"""

import strawberry
from kante.types import Info

from kammer import models, types


def room(info: Info, id: strawberry.ID) -> types.Room:
    """Get a single room by ID."""
    return models.Room.objects.for_organization(info.context.request.organization).get(id=id)


def message(info: Info, id: strawberry.ID) -> types.Message:
    """Get a single message by ID."""
    return models.Message.objects.for_organization(info.context.request.organization).get(id=id)
