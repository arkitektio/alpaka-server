"""``manage.py inspectollama`` registers an Ollama provider for an organization.

It used to create the provider without the mandatory ``organization`` FK and
re-implemented model discovery; now it requires ``--organization`` and delegates
to ``llm.logic.arefresh_provider_models``."""

from typing import Never

import pytest
from authentikate.models import Organization
from django.core.management import CommandError, call_command

from llm import models as llm_models
from llm.management.commands import inspectollama


@pytest.mark.django_db(transaction=True)
def test_inspectollama_creates_provider_for_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = Organization.objects.create(identifier="static_issuer#cmd_org")
    seen = {}

    async def fake_refresh(provider: llm_models.Provider) -> list[llm_models.LLMModel]:
        seen["provider"] = provider
        return []

    monkeypatch.setattr(inspectollama, "arefresh_provider_models", fake_refresh)

    call_command(
        "inspectollama",
        organization="static_issuer#cmd_org",
        url="http://ollama.test:11434",
    )

    provider = llm_models.Provider.objects.for_organization(org).get(name="ollama")
    assert provider.kind == "ollama"
    assert provider.api_base == "http://ollama.test:11434"
    assert seen["provider"].id == provider.id

    # Re-running is idempotent (update_or_create on (organization, name)).
    call_command(
        "inspectollama",
        organization="static_issuer#cmd_org",
        url="http://ollama.test:11434",
    )
    assert (
        llm_models.Provider.objects.for_organization(org).filter(name="ollama").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_inspectollama_requires_known_organization() -> None:
    Organization.objects.create(identifier="static_issuer#exists")
    with pytest.raises(CommandError, match="No organization with identifier 'nope'"):
        call_command("inspectollama", organization="nope")


@pytest.mark.django_db(transaction=True)
def test_inspectollama_refresh_failure_is_a_command_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Organization.objects.create(identifier="static_issuer#cmd_org")

    async def failing_refresh(provider: llm_models.Provider) -> Never:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(inspectollama, "arefresh_provider_models", failing_refresh)

    with pytest.raises(CommandError, match="connection refused"):
        call_command("inspectollama", organization="static_issuer#cmd_org")
