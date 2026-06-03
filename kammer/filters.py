from typing import Optional

import strawberry
import strawberry_django
from kammer import enums, models, scalars
from strawberry import auto
from strawberry_django.filters import FilterLookup
from vector import inputs as vector_inputs


@strawberry_django.order_type(models.Room)
class MessageOrder:
    created_at: auto


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
    talking_about: vector_inputs.StructureInput | None

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(title__icontains=self.search)

    def filter_talking_about(
        self,
        queryset,
        info,
    ):
        if not self.talking_about:
            return queryset
        structure = models.Structure.objects.filter(object=self.talking_about.object, identifier=self.talking_about.identifier).first()
        if not structure:
            return queryset.none()
        return queryset.filter(contextual_structures=structure)
