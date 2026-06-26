"""Typed, fully-documented configuration schema for the **alpaka** service.

Owned by this service. Values resolve (highest precedence first) from init
kwargs, environment variables (nested via ``__`` — e.g. ``POSTGRES__PASSWORD``),
then the YAML file (the mount's ``config.yaml`` by default; override with
``ARKITEKT_CONFIG_FILE``). Secret fields have **no default**: loading fails fast
with a ``ValidationError`` if they are not supplied via config or environment.
"""

import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from authentikate.base_models import AuthentikateSettings

_DEFAULT_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml"
)


class AdminSettings(BaseModel):
    """Django superuser created on first boot."""

    username: str = Field(description="Superuser login name.")
    password: str = Field(description="Superuser password. Secret — must be set.")
    email: Optional[str] = Field(default=None, description="Superuser email address.")


class DjangoSettings(BaseModel):
    """Core Django framework settings."""

    secret_key: str = Field(description="Django SECRET_KEY for cryptographic signing. Secret — must be set.")
    debug: bool = Field(default=False, description="Enable Django debug mode (never in production).")
    hosts: List[str] = Field(default_factory=lambda: ["*"], description="ALLOWED_HOSTS entries.")
    use_x_forwarded_host: bool = Field(default=True, description="Trust the X-Forwarded-Host header behind a reverse proxy.")
    admin: Optional[AdminSettings] = Field(default=None, description="Superuser provisioned on first boot.")
    csrf_trusted_origins: List[str] = Field(default_factory=lambda: ["http://localhost", "https://localhost"], description="CSRF_TRUSTED_ORIGINS for unsafe (POST) requests.")
    force_script_name: str = Field(default="", description="URL path prefix (FORCE_SCRIPT_NAME) this service is served under.")


class PostgresSettings(BaseModel):
    """PostgreSQL database connection (Django ``DATABASES['default']``)."""

    model_config = ConfigDict(extra="allow")

    engine: str = Field(default="django.db.backends.postgresql", description="Django database backend (PostgreSQL).")
    db_name: str = Field(description="Database name.")
    username: str = Field(description="Database user.")
    password: str = Field(description="Database password. Secret — must be set.")
    host: str = Field(description="Database host.")
    port: int = Field(default=5432, description="Database port.")


class RedisSettings(BaseModel):
    """Redis connection (channel layer / cache)."""

    model_config = ConfigDict(extra="allow")

    host: str = Field(description="Redis host.")
    port: int = Field(default=6379, description="Redis port.")


class ProviderPartnerFilterModel(BaseModel):
    """Filter conditions deciding which users/organizations a partner applies to.

    All conditions are optional. When several are set, ALL must be satisfied
    (AND logic). Mirrors lok's ``FilterConfigModel``.
    """

    email_domain_equals: Optional[List[str]] = Field(default=None, description="User email domain must exactly match one of these.")
    email_domain_ends_with: Optional[List[str]] = Field(default=None, description="User email domain must end with one of these suffixes.")
    username_equals: Optional[List[str]] = Field(default=None, description="Username must exactly match one of these.")
    username_contains: Optional[List[str]] = Field(default=None, description="Username must contain one of these substrings.")


class ProviderPartnerModel(BaseModel):
    """A pre-declared LLM provider that can be auto-provisioned for organizations.

    Mirrors lok's ``KommunityPartnerModel``. Partners flagged ``auto_configure``
    are materialized into a real per-organization ``llm.Provider`` whenever an
    organization is created.
    """

    name: str = Field(description="Human-readable provider name (also the generated Provider's name).")
    identifier: str = Field(description="Unique identifier for the partner within the system.")
    kind: str = Field(default="unknown", description="The provider kind (e.g. 'openai', 'openrouter', 'ollama').")
    description: Optional[str] = Field(default=None, description="Long description.")
    short_description: Optional[str] = Field(default=None, description="Short description.")
    logo_url: Optional[str] = Field(default=None, description="URL of the partner's logo.")
    api_key: Optional[str] = Field(default=None, description="API key handed to the provisioned provider.")
    api_base: Optional[str] = Field(default=None, description="API base URL for the provisioned provider.")
    additional_config: Optional[Dict[str, Any]] = Field(default=None, description="Extra provider configuration passed through verbatim.")
    auto_configure: bool = Field(default=False, description="If true, a Provider is auto-created for every new organization.")
    filter_config: Optional[ProviderPartnerFilterModel] = Field(default=None, description="Conditions narrowing which users/orgs the partner applies to.")


class ProviderPartnerConfigModel(BaseModel):
    """Wrapper model validating the list of provider partners from config."""

    partners: List[ProviderPartnerModel] = Field(default_factory=list)


class Settings(BaseSettings):
    """Top-level, validated configuration for the alpaka service."""

    model_config = SettingsConfigDict(env_nested_delimiter="__", extra="ignore")

    django: DjangoSettings = Field(description="Core Django settings.")
    postgres: PostgresSettings = Field(description="PostgreSQL connection.")
    redis: RedisSettings = Field(description="Redis connection.")
    authentikate: AuthentikateSettings = Field(description="Token-verification config (authentikate).")
    provider_partners: List[ProviderPartnerModel] = Field(default_factory=list, description="Pre-declared LLM providers; those with auto_configure are provisioned for every new organization.")
    ollama_url: str = Field(default="http://ollama:11434", description="Base URL of the Ollama server.")
    chroma_db_host: str = Field(default="chromadb", description="ChromaDB vector store host.")
    chroma_db_port: int = Field(default=8000, description="ChromaDB vector store port.")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Precedence: explicit init kwargs > environment variables > YAML file.
        path = os.environ.get("ARKITEKT_CONFIG_FILE", _DEFAULT_CONFIG)
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=path),
            file_secret_settings,
        )
