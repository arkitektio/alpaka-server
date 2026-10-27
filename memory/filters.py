from typing import Optional

import strawberry
import strawberry_django
from django.db.models import Q, QuerySet
from embeddings.search import hybrid_search
from kante.types import Info
from strawberry import auto

from memory import models
from memory.enums import MemoryKind


@strawberry_django.order_type(models.Memory)
class MemoryOrder:
    name: auto
    updated_at: auto


@strawberry_django.filter_type(models.Memory, description="Filter for memories")
class MemoryFilter:
    """Filter for memories"""

    @strawberry_django.filter_field
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @strawberry_django.filter_field
    def names(self, value: list[str], prefix: str) -> Q:
        return Q(**{f"{prefix}name__in": value})

    @strawberry_django.filter_field
    def kind(self, value: Optional[MemoryKind], prefix: str) -> Q:
        return Q(**{f"{prefix}kind": value.value}) if value is not None else Q()

    @strawberry_django.filter_field(description="Search what a memory says: a case-insensitive substring of its name, description or content, or semantic similarity to all three. Substring matches rank first, then by similarity; an explicit `ordering` replaces that ranking.")
    def search(self, info: Info, queryset: QuerySet, value: str, prefix: str) -> tuple[QuerySet, Q]:
        """Annotate the distance and OR the semantic predicate onto the substring one."""
        lexical = Q(**{f"{prefix}name__icontains": value}) | Q(**{f"{prefix}description__icontains": value}) | Q(**{f"{prefix}content__icontains": value})
        return hybrid_search(queryset, prefix, value, lexical)
