"""Resolving the model a user has chosen as their default for a given task."""

from authentikate.models import Organization, User

from .enums import DefaultKind
from .models import DefaultUse, LLMModel


class NoDefaultModel(Exception):
    """Raised when no default model is registered for a task."""


def get_default_llm_model_for_user(user: User, organization: Organization, kind: "DefaultKind | str") -> LLMModel:
    """Return the model this user has registered as their default for ``kind``.

    Raises :class:`NoDefaultModel` when nothing is registered, so callers get an
    actionable message rather than a bare ``DefaultUse.DoesNotExist``.
    """
    kind_value = kind.value if isinstance(kind, DefaultKind) else str(kind)
    try:
        default = DefaultUse.objects.for_organization(organization).select_related("model__provider").get(user=user, kind=kind_value)
    except DefaultUse.DoesNotExist as e:
        raise NoDefaultModel(f"No default model is configured for '{kind_value}'. Set one with the useModelFor mutation, or name a model explicitly.") from e
    return default.model
