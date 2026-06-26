# api/models.py
from django.db import models
from llm.enums import FeatureType, ProviderKind
import litellm
from authentikate.models import Organization, User


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

    class Meta:
        unique_together = ("organization", "name")


class LLMModel(models.Model):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="models")
    model_id = models.CharField(max_length=255)
    label = models.CharField(max_length=255)
    features = models.JSONField(default=list, blank=True, null=True)
    pinned_by = models.ManyToManyField(User, related_name="pinned_models")
    input_modalities = models.JSONField(default=list, blank=True, null=True)
    output_modalities = models.JSONField(default=list, blank=True, null=True)

    @property
    def is_available(self):
        return True

    @property
    def llm_string(self):
        return f"{self.provider.name}/{self.model_id}"

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

    class Meta:
        unique_together = ("kind", "organization", "user")
