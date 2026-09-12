# api/models.py
from alpaka_server.scoping import OrganizationScopedManager
from django.db import models
from llm.enums import BudgetPeriod, FeatureType, ProviderKind, UsageEndpoint, UsageStatus
from authentikate.models import Client, Organization, User


class ProviderPartner(models.Model):
    """A pre-declared LLM provider, loaded from config via ``ensurepartners``.

    Mirrors lok's ``KommunityPartner``. Partners flagged ``auto_configure`` are
    materialized into a real per-organization :class:`Provider` whenever an
    organization is created (see ``llm.logic.auto_configure_provider_partners``).
    """

    name = models.CharField(max_length=1000)
    identifier = models.CharField(max_length=1000, unique=True)
    description = models.TextField(default="No description available", null=True, blank=True)
    short_description = models.CharField(max_length=280, null=True, blank=True)
    logo_url = models.CharField(max_length=1000, null=True, blank=True)
    kind = models.CharField(max_length=50, choices=[(kind.value, kind.name) for kind in ProviderKind], default=ProviderKind.UNKNOWN.value)
    api_key = models.TextField(blank=True, null=True)
    api_base = models.URLField(blank=True, null=True)
    additional_config = models.JSONField(blank=True, null=True)
    auto_configure = models.BooleanField(default=False, help_text="If set, a Provider is created for every new organization.")
    filter_config = models.JSONField(
        help_text="Filter conditions to determine which users/organizations this partner applies to. Example: {'email_domain_equals': ['example.com'], 'email_domain_ends_with': ['edu']}",
        null=True,
        blank=True,
        default=dict,
    )

    def __str__(self):
        return f"{self.identifier}"

    def applies_to_user(self, user) -> bool:
        """Check whether this partner's filter conditions apply to the given user.

        If no ``filter_config`` is set, the partner applies to everyone. If it is
        set, all conditions must be satisfied (AND logic). Carried for parity with
        lok's ``KommunityPartner`` (alpaka organizations currently have no owner, so
        auto-config does not filter on a user yet).
        """
        if not self.filter_config:
            return True

        user_email = getattr(user, "email", None) or ""
        user_email_domain = user_email.split("@")[-1].lower() if "@" in user_email else ""
        username = getattr(user, "username", "") or ""

        if "email_domain_equals" in self.filter_config:
            domains = self.filter_config["email_domain_equals"]
            if isinstance(domains, list) and domains:
                if user_email_domain not in [d.lower() for d in domains]:
                    return False

        if "email_domain_ends_with" in self.filter_config:
            suffixes = self.filter_config["email_domain_ends_with"]
            if isinstance(suffixes, list) and suffixes:
                if not any(user_email_domain.endswith(s.lower()) for s in suffixes):
                    return False

        if "username_equals" in self.filter_config:
            usernames = self.filter_config["username_equals"]
            if isinstance(usernames, list) and usernames:
                if username not in usernames:
                    return False

        if "username_contains" in self.filter_config:
            substrings = self.filter_config["username_contains"]
            if isinstance(substrings, list) and substrings:
                if not any(s in username for s in substrings):
                    return False

        return True


class Provider(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    api_key = models.TextField(blank=True, null=True)
    api_base = models.URLField(blank=True, null=True)
    additional_config = models.JSONField(blank=True, null=True)
    creator = models.ForeignKey("authentikate.User", on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=50, choices=[(kind.value, kind.name) for kind in ProviderKind], default=ProviderKind.UNKNOWN.value)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        help_text="The organization this provider belongs to",
    )
    partner = models.ForeignKey(
        ProviderPartner,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provisioned_providers",
        help_text="The partner this provider was auto-provisioned from, if any.",
    )

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        unique_together = ("organization", "name")


#: litellm routes on the prefix before the first "/" in the model string, which
#: must be one of its provider keys. ``Provider.kind`` is the authoritative
#: field for that; ``Provider.name`` is a display name a user may set to
#: anything ("My OpenRouter"), so routing must never be derived from it.
#: CUSTOM and UNKNOWN are deliberately absent: they fall back to the name-based
#: convention, which is the only routing information such a provider carries.
LITELLM_PREFIX_BY_KIND = {
    ProviderKind.OPENAI.value: "openai",
    ProviderKind.ANTHROPIC.value: "anthropic",
    ProviderKind.GOOGLE.value: "gemini",
    ProviderKind.COHERE.value: "cohere",
    ProviderKind.MISTRAL.value: "mistral",
    ProviderKind.HUGGINGFACE.value: "huggingface",
    ProviderKind.OLLAMA.value: "ollama",
    ProviderKind.AZURE.value: "azure",
    ProviderKind.AWS.value: "bedrock",
    ProviderKind.VERTEX_AI.value: "vertex_ai",
    ProviderKind.PALM.value: "palm",
    ProviderKind.REPLICATE.value: "replicate",
    ProviderKind.TOGETHER_AI.value: "together_ai",
    ProviderKind.ANYSCALE.value: "anyscale",
    ProviderKind.FIREWORKS_AI.value: "fireworks_ai",
    ProviderKind.DEEPINFRA.value: "deepinfra",
    ProviderKind.PERPLEXITY.value: "perplexity",
    ProviderKind.GROQ.value: "groq",
    ProviderKind.OPENROUTER.value: "openrouter",
}

KINDS_BY_LITELLM_PREFIX: dict[str, list[str]] = {}
for _kind, _prefix in LITELLM_PREFIX_BY_KIND.items():
    KINDS_BY_LITELLM_PREFIX.setdefault(_prefix, []).append(_kind)


class LLMModel(models.Model):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="models")
    model_id = models.CharField(max_length=255)
    label = models.CharField(max_length=255)
    features = models.JSONField(default=list, blank=True, null=True)
    pinned_by = models.ManyToManyField(User, related_name="pinned_models")
    input_modalities = models.JSONField(default=list, blank=True, null=True)
    output_modalities = models.JSONField(default=list, blank=True, null=True)

    # LLMModel reaches its organization through its provider.
    objects = OrganizationScopedManager(field="provider__organization")
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"

    @property
    def is_available(self):
        return True

    @property
    def llm_string(self):
        kind = getattr(self.provider.kind, "value", self.provider.kind)
        prefix = LITELLM_PREFIX_BY_KIND.get(kind, self.provider.name)
        return f"{prefix}/{self.model_id}"

    def get_features(self):
        return self.features or []

    def has_feature(self, feature: FeatureType):
        return feature in self.get_features()

    @property
    def provider_kind(self) -> ProviderKind:
        """Get the provider kind from the related provider"""
        return self.provider.kind


class DefaultUse(models.Model):
    kind = models.CharField(max_length=600)
    model = models.ForeignKey(LLMModel, on_delete=models.CASCADE)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        help_text="The organization this provider belongs to",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        help_text="The organization this provider belongs to",
    )

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        unique_together = ("kind", "organization", "user")


class UsageRecord(models.Model):
    """One LLM call, as seen by the gateway.

    Written by :mod:`llm.usage` from every front door (GraphQL chat/image, the
    OpenAI-compatible REST views, vector embedding). The model is denormalised
    on purpose: a provider or model can be deleted later, and the record must
    still say what was called and what it cost.
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="usage_records", help_text="The organization that was billed")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="usage_records", help_text="The user who made the call")
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="usage_records", help_text="The client the call came through")
    model = models.ForeignKey(LLMModel, on_delete=models.SET_NULL, null=True, blank=True, related_name="usage_records", help_text="The model that was called, if it still exists")
    provider_kind = models.CharField(max_length=50, blank=True, default="")
    model_identifier = models.CharField(max_length=255, blank=True, default="", help_text="The provider-side model id at the time of the call")
    llm_string = models.CharField(max_length=512, blank=True, default="")
    endpoint = models.CharField(max_length=32, choices=[(e.value, e.name) for e in UsageEndpoint])
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    cost = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True, help_text="Cost in USD as reported or estimated by litellm; null when the model is not in its price map")
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=8, choices=[(e.value, e.name) for e in UsageStatus], default=UsageStatus.OK.value)
    error_type = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        indexes = [
            models.Index(fields=["organization", "created_at"], name="llm_usage_org_created_idx"),
            models.Index(fields=["organization", "user", "created_at"], name="llm_usage_org_user_created_idx"),
        ]

    def __str__(self):
        return f"{self.endpoint} {self.llm_string} {self.total_tokens} tokens"


class Budget(models.Model):
    """A cap on LLM consumption per calendar period.

    Applies to the whole organization, or only to one user and/or one model.
    ``hard`` budgets block calls once spent (see :func:`llm.usage.enforce_budget`);
    soft budgets only log.
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="budgets")
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name="budgets", help_text="Restrict the budget to one user; null applies to everyone in the organization")
    model = models.ForeignKey(LLMModel, on_delete=models.CASCADE, null=True, blank=True, related_name="budgets", help_text="Restrict the budget to one model; null applies to every model")
    period = models.CharField(max_length=8, choices=[(e.value, e.name) for e in BudgetPeriod], default=BudgetPeriod.MONTH.value)
    limit_tokens = models.PositiveBigIntegerField(null=True, blank=True, help_text="Maximum total tokens per period")
    limit_cost = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True, help_text="Maximum cost in USD per period")
    hard = models.BooleanField(default=True, help_text="Block calls once exceeded; otherwise only log a warning")
    creator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"

    def __str__(self):
        return f"Budget {self.pk} ({self.period})"
