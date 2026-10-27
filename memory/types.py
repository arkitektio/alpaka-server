"""GraphQL types for the memory app."""

import datetime

import strawberry
import strawberry_django

from memory import filters, models
from memory.enums import MemoryKind
from memory.owner import memory_owner


@strawberry_django.type(models.Memory, description="Something an assistant remembers about the person who assigned its task", filters=filters.MemoryFilter, ordering=filters.MemoryOrder, pagination=True)
class Memory:
    """A memory of the assigner's: only ever theirs, and only ever from a task they assigned."""

    @classmethod
    def get_queryset(cls, queryset, info, **kwargs):
        """Hold every read to the assigner of the request's task, in its organization."""
        user, organization = memory_owner(info)
        return queryset.filter(organization=organization, user=user)

    id: strawberry.ID
    name: str
    description: str
    content: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @strawberry_django.field(description="What the memory is about")
    def kind(self) -> MemoryKind:
        return MemoryKind(self.kind)
