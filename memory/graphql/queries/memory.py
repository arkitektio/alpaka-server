"""The assigner's memories, and who the assigner is.

Only the singular fetchers live here: the list field is a plain ``strawberry_django.field()``,
held to the assigner by the type's ``get_queryset``.
"""

import strawberry
from authentikate.strawberry.types import User
from kante.types import Info

from memory import models, types
from memory.owner import memory_owner


def memory(info: Info, id: strawberry.ID) -> types.Memory:
    """Get one of the assigner's memories by ID."""
    user, organization = memory_owner(info)
    return models.Memory.objects.for_organization(organization).get(user=user, id=id)


def whom(info: Info) -> User:
    """Who assigned the task this request is made for: the person whose memories it reaches."""
    user, _ = memory_owner(info)
    return user
