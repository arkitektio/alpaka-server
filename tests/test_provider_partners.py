"""Tests for ProviderPartner auto-provisioning on organization creation.

A ProviderPartner flagged ``auto_configure`` must materialize into a per-org
``Provider`` whenever an ``authentikate`` Organization is created (via the
``llm.signals`` post_save receiver)."""

import pytest

from authentikate.models import Organization
from llm import models as llm_models
from llm.logic import auto_configure_provider_partners


@pytest.mark.django_db(transaction=True)
def test_auto_configure_partner_provisions_provider_on_org_creation():
    llm_models.ProviderPartner.objects.create(
        name="Shared OpenRouter",
        identifier="shared-openrouter",
        kind="openrouter",
        api_key="sk-test",
        api_base="https://openrouter.ai/api/v1",
        auto_configure=True,
    )

    org = Organization.objects.create(slug="partner_test_org")

    provider = llm_models.Provider.objects.get(organization=org, name="Shared OpenRouter")
    assert provider.partner.identifier == "shared-openrouter"
    assert provider.kind == "openrouter"
    assert provider.api_key == "sk-test"


@pytest.mark.django_db(transaction=True)
def test_non_auto_partner_is_not_provisioned():
    llm_models.ProviderPartner.objects.create(
        name="Manual Provider",
        identifier="manual-provider",
        kind="openai",
        auto_configure=False,
    )

    org = Organization.objects.create(slug="manual_test_org")

    assert not llm_models.Provider.objects.filter(organization=org).exists()


@pytest.mark.django_db(transaction=True)
def test_auto_configure_is_idempotent():
    partner = llm_models.ProviderPartner.objects.create(
        name="Idempotent Provider",
        identifier="idempotent-provider",
        kind="openai",
        auto_configure=True,
    )

    org = Organization.objects.create(slug="idempotent_org")
    # Re-running must not create a duplicate (matches per-org (organization, name) uniqueness).
    auto_configure_provider_partners(org)

    assert llm_models.Provider.objects.filter(organization=org, partner=partner).count() == 1


@pytest.mark.django_db(transaction=True)
def test_same_partner_provisions_distinct_providers_across_orgs():
    """Per-org uniqueness lets the same partner name exist in multiple orgs."""
    llm_models.ProviderPartner.objects.create(
        name="Fleet Provider",
        identifier="fleet-provider",
        kind="openai",
        auto_configure=True,
    )

    org_a = Organization.objects.create(slug="fleet_org_a")
    org_b = Organization.objects.create(slug="fleet_org_b")

    assert llm_models.Provider.objects.filter(name="Fleet Provider", organization=org_a).exists()
    assert llm_models.Provider.objects.filter(name="Fleet Provider", organization=org_b).exists()
