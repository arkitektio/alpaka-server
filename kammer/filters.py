from typing import Optional

import strawberry
import strawberry_django
from kammer import enums, models, scalars
from strawberry import auto
from strawberry_django.filters import FilterLookup


@strawberry_django.filter(models.Message)
class MessageFilter:
    ids: list[strawberry.ID] | None
    search: Optional[str] | None

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(text__icontains=self.search)


@strawberry_django.filter(models.Room)
class RoomFilter:
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
