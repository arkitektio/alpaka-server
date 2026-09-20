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


def test_django_settings_mirror_config():
    """settings.py must take its security-relevant values from the validated
    config instead of hard-coding them (DEBUG used to be a literal ``True``)."""
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "alpaka_server.settings")
    from django.conf import settings

    conf = Settings()
    assert settings.SECRET_KEY == conf.django.secret_key
    assert settings.DEBUG == conf.django.debug
    # pytest-django appends "testserver" under the test runner.
    assert set(conf.django.hosts) <= set(settings.ALLOWED_HOSTS)
    assert settings.CSRF_TRUSTED_ORIGINS == list(conf.django.csrf_trusted_origins)
    assert settings.USE_X_FORWARDED_HOST == conf.django.use_x_forwarded_host
    assert settings.MY_SCRIPT_NAME == conf.django.force_script_name
    # kante prefixes every URL pattern with MY_SCRIPT_NAME itself; Django's
    # FORCE_SCRIPT_NAME would strip that prefix again and 404 every route.
    assert not getattr(settings, "FORCE_SCRIPT_NAME", None)
    assert not hasattr(settings, "GRAPHENE")


def test_django_admin_setting_is_exposed_as_dict():
    """``ensureadmin`` reads ``settings.DJANGO_ADMIN``; it must mirror ``django.admin``."""
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "alpaka_server.settings")
    from django.conf import settings

    conf = Settings()
    expected = conf.django.admin.model_dump() if conf.django.admin else None
    assert settings.DJANGO_ADMIN == expected


def test_embeddings_block_defaults_and_override(monkeypatch):
    """The ``embeddings`` block defaults to potion-base-8M at 256 dims and is env-overridable."""
    s = Settings()
    assert s.embeddings.enabled is True
    assert s.embeddings.model == "minishlab/potion-base-8M"
    assert s.embeddings.dimensions == 256
    monkeypatch.setenv("EMBEDDINGS__DISTANCE_THRESHOLD", "0.42")
    assert Settings().embeddings.distance_threshold == 0.42
