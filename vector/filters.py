import strawberry
import strawberry_django
from alpaka_server.descriptors import REQUIRES_DESCRIPTION, DescriptorConstraintInput
from alpaka_server.descriptors import requires as descriptor_requires
from django.db.models import Q, QuerySet
from embeddings.search import hybrid_search
from kante.types import Info
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

    @strawberry_django.filter_field(description="Search by name: a case-insensitive substring, or semantic similarity of the query to the collection's name and description. Substring matches rank first, then by similarity; an explicit `ordering` replaces that ranking.")
    def search(self, info: Info, queryset: QuerySet, value: str, prefix: str) -> tuple[QuerySet, Q]:
        """Annotate the distance and OR the semantic predicate onto the substring one."""
        return hybrid_search(queryset, prefix, value, Q(**{f"{prefix}name__icontains": value}))

    @strawberry_django.filter_field(description=REQUIRES_DESCRIPTION)
    def requires(self, value: list[DescriptorConstraintInput], prefix: str) -> Q:
        """A port\'s ``requires``, on the stored descriptors."""
        return descriptor_requires(models.ChromaCollection, value, prefix)
