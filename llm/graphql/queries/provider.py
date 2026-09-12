"""Provider and model lookups.

Only the singular fetchers live here. The list fields are plain
``strawberry_django.field()`` declarations — organization scoping is applied by
each type's ``get_queryset`` classmethod, which strawberry_django runs for list
fields, singular fields and nested traversals alike.
"""

from typing import Optional

import strawberry
from kante.types import Info

from llm import enums, manager, models, types


def provider(info: Info, id: strawberry.ID) -> types.Provider:
    """Get a single provider by ID."""
    return models.Provider.objects.for_organization(info.context.request.organization).get(id=id)


def llm_model(info: Info, id: strawberry.ID) -> types.LLMModel:
    """Get a single LLM model by ID."""
    return models.LLMModel.objects.for_organization(info.context.request.organization).select_related("provider").get(id=id)


def default_model_for(info: Info, kind: enums.DefaultKind) -> Optional[types.LLMModel]:
    """The model the caller uses by default for ``kind``, or null if none is set."""
    try:
        return manager.get_default_llm_model_for_user(info.context.request.user, info.context.request.organization, kind)
    except manager.NoDefaultModel:
        return None
