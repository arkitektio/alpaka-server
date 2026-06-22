import strawberry
import strawberry_django
from django.db.models import Q, QuerySet
from kammer import models
from strawberry import auto
from vector import inputs as vector_inputs


@strawberry_django.order_type(models.Message)
class MessageOrder:
    created_at: auto


@strawberry_django.filter_type(models.Message)
class MessageFilter:
    @strawberry_django.filter_field
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}text__icontains": value})


@strawberry_django.order_type(models.Agent)
class AgentOrder:
    name: auto


@strawberry_django.filter_type(models.Agent)
class AgentFilter:
    @strawberry_django.filter_field
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__icontains": value})


@strawberry_django.order_type(models.Room)
class RoomOrder:
    created_at: auto
    title: auto


@strawberry_django.filter_type(models.Room)
class RoomFilter:
    @strawberry_django.filter_field
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}title__icontains": value})

    @strawberry_django.filter_field
    def talking_about(
        self,
        value: vector_inputs.StructureInput,
        queryset: QuerySet,
        prefix: str,
    ) -> tuple[QuerySet, Q]:
        structure = models.Structure.objects.filter(object=value.object, identifier=value.identifier).first()
        if not structure:
            return queryset.none(), Q()
        return queryset, Q(**{f"{prefix}contextual_structures": structure})
