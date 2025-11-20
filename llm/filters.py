from typing import Optional

import strawberry
import strawberry_django
from llm import enums, models


@strawberry_django.filter(models.LLMModel, description="Filter for LLMModel")
class LLMModelFilter:
    """Filter for LLMModel"""

    ids: list[strawberry.ID] | None
    search: Optional[str] | None
    input_modalities: list[enums.InputModality] | None
    output_modalities: list[enums.InputModality] | None

    def filter_ids(self, queryset, info):
        """Filter by IDs"""
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        """Filter by search term"""
        if self.search is None:
            return queryset
        return queryset.filter(label__icontains=self.search)

    def filter_input_modalities(self, queryset, info):
        if self.input_modalities is None:
            return queryset
        return queryset.filter(input_modalities__contains=self.input_modalities)

    def filter_output_modalities(self, queryset, info):
        if self.output_modalities is None:
            return queryset
        return queryset.filter(output_modalities__contains=self.output_modalities)


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
