import strawberry
import strawberry_django
from django.db.models import Q
from llm import enums, models
from strawberry import auto


@strawberry_django.order_type(models.LLMModel)
class LLMModelOrder:
    label: auto
    model_id: auto


@strawberry_django.filter_type(models.LLMModel, description="Filter for LLMModel")
class LLMModelFilter:
    """Filter for LLMModel"""

    @strawberry_django.filter_field
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}label__icontains": value})

    @strawberry_django.filter_field
    def input_modalities(self, value: list[enums.InputModality], prefix: str) -> Q:
        return Q(**{f"{prefix}input_modalities__contains": value})

    @strawberry_django.filter_field
    def output_modalities(self, value: list[enums.InputModality], prefix: str) -> Q:
        return Q(**{f"{prefix}output_modalities__contains": value})


@strawberry_django.order_type(models.Provider)
class ProviderOrder:
    name: auto
    created_at: auto


@strawberry_django.filter_type(models.Provider, description="Filter for Provider")
class ProviderFilter:
    """Filter for Provider"""

    @strawberry_django.filter_field
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__icontains": value})


@strawberry_django.order_type(models.DefaultUse)
class DefaultUseOrder:
    kind: auto


@strawberry_django.filter_type(models.DefaultUse, description="Filter for DefaultUse")
class DefaultUseFilter:
    """Filter for DefaultUse"""

    @strawberry_django.filter_field
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @strawberry_django.filter_field
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}kind__icontains": value})
