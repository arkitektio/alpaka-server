"""Budget lookups."""

import strawberry
from kante.types import Info

from alpaka_server.scoping import held_to_guest
from llm import models, types


def budget(info: Info, id: strawberry.ID) -> types.Budget:
    """Get a single budget by ID."""
    return held_to_guest(models.Budget.objects.for_organization(info.context.request.organization), info).get(id=id)


def budget_status(info: Info, id: strawberry.ID) -> types.BudgetStatus:
    """How much of a budget is used in the current period."""
    return types.budget_status_of(models.Budget.objects.for_organization(info.context.request.organization).get(id=id))
