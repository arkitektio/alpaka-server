"""Creating, changing and removing budgets."""

import strawberry
from authentikate.models import Membership, User
from kante.types import Info

from llm import models, types
from llm.inputs import CreateBudgetInput, DeleteBudgetInput, UpdateBudgetInput


def _scoped_user(info: Info, user_id: str | None) -> User | None:
    """The user a budget is restricted to, who must belong to the caller's organization."""
    if user_id is None:
        return None
    membership = Membership.objects.filter(user_id=user_id, organization=info.context.request.organization).select_related("user").first()
    if membership is None:
        raise ValueError(f"User {user_id} is not a member of this organization")
    return membership.user


def _scoped_model(info: Info, model_id: str | None) -> models.LLMModel | None:
    if model_id is None:
        return None
    return models.LLMModel.objects.for_organization(info.context.request.organization).get(id=model_id)


def create_budget(info: Info, input: CreateBudgetInput) -> types.Budget:
    """Create a budget in the caller's organization."""
    if input.limit_tokens is None and input.limit_cost is None:
        raise ValueError("A budget needs a token limit, a cost limit, or both")
    return models.Budget.objects.for_write().create(
        organization=info.context.request.organization,
        creator=info.context.request.user,
        user=_scoped_user(info, input.user),
        model=_scoped_model(info, input.model),
        period=input.period.value,
        limit_tokens=input.limit_tokens,
        limit_cost=input.limit_cost,
        hard=input.hard,
    )


def update_budget(info: Info, input: UpdateBudgetInput) -> types.Budget:
    """Change a budget's period, limits or hardness."""
    budget = models.Budget.objects.for_organization(info.context.request.organization).get(id=input.id)
    if input.period is not strawberry.UNSET and input.period is not None:
        budget.period = input.period.value
    if input.limit_tokens is not strawberry.UNSET:
        budget.limit_tokens = input.limit_tokens
    if input.limit_cost is not strawberry.UNSET:
        budget.limit_cost = input.limit_cost
    if input.hard is not strawberry.UNSET and input.hard is not None:
        budget.hard = input.hard
    if budget.limit_tokens is None and budget.limit_cost is None:
        raise ValueError("A budget needs a token limit, a cost limit, or both")
    budget.save()
    return budget


def delete_budget(info: Info, input: DeleteBudgetInput) -> strawberry.ID:
    """Delete a budget belonging to the caller's organization."""
    budget = models.Budget.objects.for_organization(info.context.request.organization).get(id=input.id)
    budget.delete()
    return input.id
