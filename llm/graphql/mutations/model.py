"""Registering which model to use by default for a given task."""

from kante.types import Info

from llm import inputs, models, types


def use_model_for(info: Info, input: inputs.UseModelForInput) -> types.DefaultUse:
    """Set a model as the caller's default for a specific kind of task."""
    user = info.context.request.user
    organization = info.context.request.organization

    # Scoped so a caller cannot adopt another organization's model as a default.
    model = models.LLMModel.objects.for_organization(organization).select_related("provider").get(id=input.model)

    # DefaultUse is unique on (kind, organization, user), so all three belong in
    # the lookup. With organization only in `defaults`, a user in two
    # organizations overwrote their other organization's default instead of
    # holding one per organization.
    default, _ = models.DefaultUse.objects.for_write().update_or_create(
        user=user,
        organization=organization,
        kind=input.kind.value,
        defaults={"model": model},
    )

    return default

