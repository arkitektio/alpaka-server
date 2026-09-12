"""``manage.py inspectollama`` registers an Ollama provider for an organization.

It used to create the provider without the mandatory ``organization`` FK and
re-implemented model discovery; now it requires ``--organization`` and delegates
to ``llm.logic.arefresh_provider_models``."""

import pytest
from django.core.management import CommandError, call_command

from authentikate.models import Organization
from llm import models as llm_models
from llm.management.commands import inspectollama


@pytest.mark.django_db(transaction=True)
def test_inspectollama_creates_provider_for_organization(monkeypatch):
    org = Organization.objects.create(slug="cmd_org")
    seen = {}

    async def fake_refresh(provider):
        seen["provider"] = provider
        return []

    monkeypatch.setattr(inspectollama, "arefresh_provider_models", fake_refresh)

    call_command("inspectollama", organization="cmd_org", url="http://ollama.test:11434")

    provider = llm_models.Provider.objects.for_organization(org).get(name="ollama")
    assert provider.kind == "ollama"
    assert provider.api_base == "http://ollama.test:11434"
    assert seen["provider"].id == provider.id

    # Re-running is idempotent (update_or_create on (organization, name)).
    call_command("inspectollama", organization="cmd_org", url="http://ollama.test:11434")
    assert llm_models.Provider.objects.for_organization(org).filter(name="ollama").count() == 1


@pytest.mark.django_db(transaction=True)
def test_inspectollama_requires_known_organization():
    Organization.objects.create(slug="exists")
    with pytest.raises(CommandError, match="No organization with slug 'nope'"):
        call_command("inspectollama", organization="nope")


@pytest.mark.django_db(transaction=True)
def test_inspectollama_refresh_failure_is_a_command_error(monkeypatch):
    Organization.objects.create(slug="cmd_org")

    async def failing_refresh(provider):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(inspectollama, "arefresh_provider_models", failing_refresh)

    with pytest.raises(CommandError, match="connection refused"):
        call_command("inspectollama", organization="cmd_org")
