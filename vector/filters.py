from typing import Optional

import strawberry
import strawberry_django
from vector import enums, models



@strawberry_django.filter(models.ChromaCollection, description="Filter for ChromaCollection")
class ChromaCollectionFilter:
    """Filter for Provider"""

    search: Optional[str] | None
    ids: list[strawberry.ID] | None

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(title__icontains=self.search)
