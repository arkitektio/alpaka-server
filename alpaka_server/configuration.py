"""Typed, fully-documented configuration schema for the **alpaka** service.

Owned by this service. Values resolve (highest precedence first) from init
kwargs, environment variables (nested via ``__`` — e.g. ``POSTGRES__PASSWORD``),
then the YAML file (``config.yaml`` where the service runs by default; override with
``ARKITEKT_CONFIG_FILE``). Secret fields have **no default**: loading fails fast
with a ``ValidationError`` if they are not supplied via config or environment.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arkitekt_service.server import settings as shared
from arkitekt_service.server.settings import InstanceSettings, PostgresSettings, ServiceSettings
from authentikate.base_models import AuthentikateSettings

class DjangoSettings(shared.DjangoSettings):
    """Core Django framework settings."""

    force_script_name: str = Field(default="", description="URL path prefix this service is served under (applied to every route by kante's dynamicpath; not Django's FORCE_SCRIPT_NAME).")


class RedisSettings(shared.RedisSettings):
    """Redis connection (channel layer / cache)."""

    channel_prefix: str = Field(default="alpaka", description="Key prefix for the channels_redis channel layer. Must be unique per service: every service on a shared redis used to send under the same prefix, so identically-named groups (e.g. \"files\") delivered one service's events to another's subscribers.")


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


class EmbeddingsSettings(BaseModel):
    """Semantic search: a model2vec static model embeds name + description into pgvector columns.

    Every value has a default, so the block may be omitted. The vector width is fixed by the
    model *and* by the database columns; see CONFIG.md before changing ``model``.
    """

    model_config = ConfigDict(extra="allow", protected_namespaces=())

    enabled: bool = Field(default=True, description="Embed rows on save and give `search` a semantic leg. Off: `search` is lexical-only and the embedding columns stay NULL.")
    model: str = Field(default="minishlab/potion-base-8M", description="model2vec model id. Recorded on every row; rows embedded by another model are re-embedded in-process and skipped by vector search until then.")
    model_path: Optional[str] = Field(default=None, description="Directory holding the weights of `model` (save_pretrained layout). The Docker image bakes them under /opt/models and sets EMBEDDINGS__MODEL_PATH; unset, model2vec downloads from Hugging Face on first use.")
    dimensions: int = Field(default=256, description="Vector width of `model`. Also the width of the database columns, so changing it is a migration. Checked against both at startup.")
    distance_threshold: float = Field(default=0.55, description="Cosine distance (0 identical, 1 unrelated) above which a row no longer counts as a semantic `search` hit.")
    sweep_interval: int = Field(default=300, description="No longer used: `reembed_stale` (which re-embeds rows whose `embedding_model` is not `model`) is only offered as an action, and scheduling it is the organization's own automation. Kept so existing configs load.")
    sweep_batch_size: int = Field(default=200, description="Rows re-embedded per pass.")


class RekuestHookSettings(BaseModel):
    """How this process reaches the hub's rekuest: as a service (``rekuest_service``) and as a hook agent (``rekuest_hook``)."""

    rekuest_url: str = Field(default="http://rekuest:80/rekuest", description="rekuest's base URL on the internal network; runs are reported to its `agi/http/<agent>` intake.")
    service: str = Field(default="alpaka", description="The name rekuest knows this process by: its `rekuest.services[].name` (signals are sent as it) and its `rekuest.hook_agents[].name`.")
    max_skew: int = Field(default=30, description="Clock skew (seconds) tolerated on a signed request; tokens themselves live 60 s.")


class Settings(ServiceSettings):
    """Top-level, validated configuration for the alpaka service."""

    django: DjangoSettings = Field(description="Core Django settings.")
    postgres: PostgresSettings = Field(description="PostgreSQL connection.")
    redis: RedisSettings = Field(description="Redis connection.")
    authentikate: AuthentikateSettings = Field(description="Token-verification config (authentikate).")
    provider_partners: List[ProviderPartnerModel] = Field(default_factory=list, description="Pre-declared LLM providers; those with auto_configure are provisioned for every new organization.")
    embeddings: EmbeddingsSettings = Field(default_factory=EmbeddingsSettings, description="Semantic search over rooms and collections: model and thresholds. Unrelated to the document embeddings of the Chroma collections, which use the collection's own LLM embedder.")
    rekuest_hook: Optional[RekuestHookSettings] = Field(default=None, description="Let the hub's rekuest run this service's periodic work (`reembed_stale`). Without it stale embeddings are not healed.")
    instance: Optional[InstanceSettings] = Field(default=None, description="This instance's key and the hub trust bundle (signed requests to and from rekuest, no shared secrets).")

    @model_validator(mode="before")
    @classmethod
    def _accept_providers_shorthand(cls, data: Any) -> Any:
        """Fold a top-level ``providers:`` block into ``provider_partners``.

        Deployments write the shorthand::

            providers:
            - openrouter: sk-or-...

        With ``extra="ignore"`` that block used to be silently discarded and no
        provider was ever provisioned. Each shorthand entry maps every
        ``<kind>: <api_key>`` pair to an auto-configured partner; keys with a
        null value (e.g. a bare ``organization:``) are skipped. Entries that
        already look like a full ``ProviderPartnerModel`` (they carry an
        ``identifier``) pass through unchanged.
        """
        if not isinstance(data, dict):
            return data
        providers = data.get("providers")
        if not providers or data.get("provider_partners"):
            return data

        partners: List[Any] = []
        for entry in providers:
            if not isinstance(entry, dict):
                continue
            if "identifier" in entry:
                partners.append(entry)
                continue
            for kind, api_key in entry.items():
                if not api_key or not isinstance(api_key, str):
                    continue
                partners.append(
                    {
                        "name": kind,
                        "identifier": kind,
                        "kind": kind,
                        "api_key": api_key,
                        "auto_configure": True,
                    }
                )
        if partners:
            data = {**data, "provider_partners": partners}
        return data
    ollama_url: str = Field(default="http://ollama:11434", description="Base URL of the Ollama server.")
    chroma_db_host: str = Field(default="chromadb", description="ChromaDB vector store host.")
    chroma_db_port: int = Field(default=8000, description="ChromaDB vector store port.")
