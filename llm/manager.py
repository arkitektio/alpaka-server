from authentikate.models import User, Organization
from .models import LLMModel, DefaultUse


def get_default_llm_model_for_user(user: User, organization: Organization, kind: str) -> LLMModel:
    user = DefaultUse.objects.get(user=user, organization=organization, kind=kind)
    return LLMModel.objects.select_related("provider").get(id=user.model.id)
