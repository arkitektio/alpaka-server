import strawberry
import strawberry_django
from django.db.models import Q
from strawberry import auto
from vector import models


@strawberry_django.order_type(models.ChromaCollection)
class ChromaCollectionOrder:
    name: auto
    created_at: auto


@strawberry_django.filter_type(models.ChromaCollection, description="Filter for ChromaCollection")
class ChromaCollectionFilter:
    """Filter for ChromaCollection"""

    @strawberry_django.filter_field
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__icontains": value})
