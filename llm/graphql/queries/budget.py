"""Budget lookups."""

import strawberry
from kante.types import Info

from llm import models, types


def budget(info: Info, id: strawberry.ID) -> types.Budget:
    """Get a single budget by ID."""
    return models.Budget.objects.for_organization(info.context.request.organization).get(id=id)


def budget_status(info: Info, id: strawberry.ID) -> types.BudgetStatus:
    """How much of a budget is used in the current period."""
    return types.budget_status_of(models.Budget.objects.for_organization(info.context.request.organization).get(id=id))
