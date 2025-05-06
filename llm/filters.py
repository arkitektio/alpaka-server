from typing import Optional

import strawberry
import strawberry_django
from llm import enums, models


@strawberry_django.filter(models.LLMModel, description="Filter for LLMModel")
class LLMModelFilter:
    """Filter for LLMModel"""

    ids: list[strawberry.ID] | None
    search: Optional[str] | None

    def filter_ids(self, queryset, info):
        """Filter by IDs"""
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        """Filter by search term"""
        if self.search is None:
            return queryset
        return queryset.filter(text__icontains=self.search)


@strawberry_django.filter(models.Provider, description="Filter for Provider")
class ProviderFilter:
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
