"""Validate the alpaka service's config.yaml against its bespoke schema.

Standalone — needs no database; run with ``uv run pytest tests/test_config.py``.
"""

from alpaka_server.configuration import Settings


def test_config_yaml_validates():
    """The service's own config.yaml parses into the typed schema."""
    s = Settings()
    assert s.postgres.db_name
    assert s.redis.host


def test_env_override(monkeypatch):
    """Env vars override the YAML file (nested via ``__``)."""
    monkeypatch.setenv("POSTGRES__PASSWORD", "from-env-test")
    assert Settings().postgres.password == "from-env-test"


def test_providers_shorthand_maps_to_auto_configured_partners():
    """The deployment-style ``providers:`` shorthand (kind → api key, null
    values skipped) lands in ``provider_partners`` instead of being silently
    dropped by ``extra='ignore'``."""
    s = Settings(providers=[{"organization": None, "openrouter": "sk-or-test"}])
    assert len(s.provider_partners) == 1
    partner = s.provider_partners[0]
    assert partner.identifier == "openrouter"
    assert partner.kind == "openrouter"
    assert partner.api_key == "sk-or-test"
    assert partner.auto_configure is True


def test_providers_full_partner_entries_pass_through():
    """An entry that already looks like a ProviderPartnerModel is taken as-is."""
    s = Settings(providers=[{"identifier": "corp", "name": "Corp", "kind": "openai", "api_key": "sk-x"}])
    assert s.provider_partners[0].identifier == "corp"
    assert s.provider_partners[0].auto_configure is False


def test_explicit_provider_partners_wins_over_shorthand():
    s = Settings(
        providers=[{"openrouter": "sk-ignored"}],
        provider_partners=[{"identifier": "explicit", "name": "Explicit", "kind": "openai"}],
    )
    assert [p.identifier for p in s.provider_partners] == ["explicit"]
