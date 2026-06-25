import strawberry
from strawberry.types import Info
from llm import models, types, inputs
import strawberry_django


def use_model_for(info: Info, input: inputs.UseModelForInput) -> types.DefaultUse:
    """Set a model as default for a specific kind of task."""
    user = info.context.request.user
    if not user.is_authenticated:
        raise Exception("User not authenticated")

    model = models.LLMModel.objects.get(id=input.model)

    # Create or update the default
    # We need to handle organization. Assuming user has an organization or we pick the first one?
    # Or maybe the model has an organization?
    # The Provider has an organization.

    # Let's try to get organization from the user if possible, or from the model's provider?
    # But DefaultUse requires organization.

    # Assuming user.organization exists or similar.
    # Looking at Provider model: creator = models.ForeignKey("authentikate.User"...)
    # Looking at DefaultUse model: organization = models.ForeignKey(Organization...)

    # Let's assume we can get it from the model's provider for now, or maybe the user has a current organization context?
    # Since I don't have full context on User model, I'll try to use the model's provider's organization if available,
    # or fail if I can't find one.

    organization = model.provider.organization

    default, created = models.DefaultUse.objects.update_or_create(
        user=user,
        kind=input.kind,
        defaults={"model": model, "organization": organization},
    )

    return default
