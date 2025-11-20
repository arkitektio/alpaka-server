from authentikate.models import User, Organization
from .models import LLMModel, DefaultUse


def get_default_llm_model_for_user(user: User, organization: Organization, kind: str) -> LLMModel:
    return DefaultUse.objects.get(user=user, organization=organization, kind=kind).model
