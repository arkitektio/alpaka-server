"""What this image answers a hub's installer: ``arkitekt-service <verb>`` (see ``arkitekt_service.contract``).

The installer knows the hub; how this release spells its config is written here, with the
settings it is read by. A key renamed in ``configuration.py`` is renamed in :func:`render` in
the same commit, and no installer has to learn of it.
"""

from __future__ import annotations

from arkitekt_service.contract import JSON, Contract, Description, Descriptor, Facts, Hosts, Job, Needs, Offers, Role, Scope, Signal, Start, Structure, blocks

from alpaka_server.configuration import Settings

#: What an app may do here on a user's behalf: defined at the coordination server when the hub
#: enrols. Every root field of the schema asks for one of them (`AuthExtension(scopes=...)`).
SCOPES = [
    Scope(key="alpaka_read", description="See your chat rooms, messages, vector collections, memories and the models your organization can use."),
    Scope(key="alpaka_write", description="Create and delete chat rooms and vector collections, add documents to collections, and manage memories and your default models."),
    Scope(key="alpaka_chat", description="Send messages and run models on your behalf (chat, image generation, decisions); this spends your organization's LLM budget."),
    Scope(key="alpaka_providers", description="Configure LLM providers, pull models onto them, and set the organization's spending budgets."),
    Scope(key="alpaka_share", description="Share rooms and messages with people outside your organization through collaborations."),
    Scope(key="alpaka_all", description="Do everything in Alpaka on your behalf.", is_all_scope=True),
]

#: What a member of an organization may do here.
ROLES = [
    Role(key="alpaka_admin", description="Full control of Alpaka in this organization.", is_admin_role=True),
    Role(key="alpaka_editor", description="Create rooms and collections, chat with models, and share through collaborations.", is_default_role=True),
    Role(key="alpaka_manager", description="Configure providers, models and budgets without being an Alpaka admin."),
]

#: The role every write asks for, the one that configures providers and budgets, and the one
#: holding every other.
EDITOR = "alpaka_editor"
MANAGER = "alpaka_manager"
ADMIN = "alpaka_admin"

#: The kind of provider that runs a model (``ollama``, ``openai``, ...): what a privacy-sensitive
#: action selects on, requiring a provider that runs on the hub (``ollama``, ``ollaya``). One key for
#: providers and their models, so one `requires` asks both.
_PROVIDER_KIND = Descriptor(key="@alpaka/provider_kind", type="STRING", description="The kind of provider that runs the model (ollama, ollaya, openai, anthropic, ...): ollama and ollaya run locally on the hub")

ROOM_DESCRIPTORS = [
    Descriptor(key="@alpaka/contextual_structures", type="LIST", description="The structures the conversation is about (e.g. @mikro/image), sorted, each once"),
    Descriptor(key="@alpaka/n_agents", type="INT", description="How many agents (participants) take part in the conversation"),
]
MESSAGE_DESCRIPTORS = [
    Descriptor(key="@alpaka/from_agent", type="BOOL", description="Whether an agent posted the message"),
    Descriptor(key="@alpaka/is_reply", type="BOOL", description="Whether it replies to another message"),
    Descriptor(key="@alpaka/attached_structures", type="LIST", description="The structures the message was posted about (e.g. @mikro/image), sorted, each once"),
]
LLM_MODEL_DESCRIPTORS = [
    Descriptor(key="@alpaka/features", type="LIST", description="What the model can do: chat, embedding, vision or decision"),
    Descriptor(key="@alpaka/input_modalities", type="LIST", description="The kinds of content it accepts as input (text, image, audio, video)"),
    Descriptor(key="@alpaka/output_modalities", type="LIST", description="The kinds of content it produces as output (text, image, audio, video)"),
    _PROVIDER_KIND,
]
CHROMA_COLLECTION_DESCRIPTORS = [
    Descriptor(key="@alpaka/embedder", type="STRING", description="The embedding model its documents are embedded by (its model id): a search query is embedded by the same"),
]
#: Only its kind: a provider row holds an API key, and nothing secret is described.
PROVIDER_DESCRIPTORS = [_PROVIDER_KIND]


def _keys(descriptors: list[Descriptor]) -> list[str]:
    return [descriptor.key for descriptor in descriptors]


#: What exists on a hub because this service is there: said here, as data, so the hub knows it from
#: the image. ``service.py`` binds each of these to its model and refuses anything not said here.
HOSTS = Hosts(
    structures=[
        Structure(
            identifier="@alpaka/room",
            label="Chat Room",
            description="A chat room: a conversation in which users and agents (the apps they take part through) exchange messages.",
            descriptors=ROOM_DESCRIPTORS,
        ),
        Structure(
            identifier="@alpaka/message",
            label="Chat Message",
            description="A chat message an agent posted in a room, possibly in reply to another message.",
            descriptors=MESSAGE_DESCRIPTORS,
        ),
        Structure(
            identifier="@alpaka/llmmodel",
            label="LLM Model",
            description="A large language model (LLM) for chat, vision or embeddings, reachable through one of the organization's AI providers.",
            descriptors=LLM_MODEL_DESCRIPTORS,
        ),
        Structure(
            identifier="@alpaka/chromacollection",
            label="Chroma Collection",
            description="A collection in the Chroma vector database: documents embedded by one model and searchable by meaning, like a knowledge base.",
            descriptors=CHROMA_COLLECTION_DESCRIPTORS,
        ),
        Structure(
            identifier="@alpaka/provider",
            label="LLM Provider",
            description="A provider of language models (OpenAI, Anthropic, Ollama, ...), as configured by an organization with its API key and endpoint.",
            descriptors=PROVIDER_DESCRIPTORS,
        ),
    ],
    signals=[
        Signal(
            identifier="@alpaka/room",
            kinds=["CREATED", "DELETED"],
            descriptors=_keys(ROOM_DESCRIPTORS),
            description="A chat room (a conversation) was created or deleted.",
        ),
        Signal(
            identifier="@alpaka/message",
            kinds=["CREATED", "UPDATED"],
            descriptors=_keys(MESSAGE_DESCRIPTORS),
            description="A chat message was posted in a room (a streamed reply: once it finished).",
        ),
        Signal(
            identifier="@alpaka/llmmodel",
            kinds=["CREATED", "UPDATED"],
            descriptors=_keys(LLM_MODEL_DESCRIPTORS),
            description="A language model (LLM) became available or changed (e.g. after a provider refresh).",
        ),
        Signal(
            identifier="@alpaka/chromacollection",
            kinds=["CREATED", "DELETED"],
            descriptors=_keys(CHROMA_COLLECTION_DESCRIPTORS),
            description="A vector collection (documents searchable by meaning) was created or deleted.",
        ),
        Signal(
            identifier="@alpaka/provider",
            kinds=["CREATED", "UPDATED"],
            descriptors=_keys(PROVIDER_DESCRIPTORS),
            description="An LLM provider (OpenAI, Ollama, ...) was added or changed.",
        ),
    ],
)


def render(facts: Facts) -> dict[str, JSON]:
    """This release's config for the hub ``facts`` describes."""
    document: dict[str, JSON] = blocks.server(facts)
    document["instance"] = blocks.instance(facts)
    hook = blocks.rekuest_hook(facts)
    if hook is not None:
        document["rekuest_hook"] = hook
    ollama = facts.peers.get("ollama")
    if ollama is not None:
        document["ollama_url"] = ollama.url
    return document


contract = Contract(
    description=Description(
        name="alpaka",
        identifier="live.arkitekt.alpaka",
        summary="Language models for the hub.",
        needs=Needs(scopes=SCOPES, roles=ROLES, storage=["media"], instance_key=True, peers=["rekuest", "ollama"]),
        offers=Offers(endpoints={"rekuest_service": "_rekuest/service", "rekuest_hook": "_rekuest/hook"}),
        requires={"rekuest": ">=6"},
        hosts=HOSTS,
    ),
    settings=Settings,
    render=render,
    # How this service is started: there is no script beside it. `arkitekt-service serve`
    # (and `debug`) become these, so they get the container's signals themselves.
    serve=Start(("daphne", "-b", "0.0.0.0", "-p", "80", "--websocket_timeout", "-1", "alpaka_server.asgi:application")),
    debug=Start(("python", "manage.py", "runserver", "0.0.0.0:80")),
    jobs={
        "ensureadmin": Job(("ensureadmin",), "Create the operator account the config names"),
        "ensurepartners": Job(("ensurepartners",), "Register the partners the config names"),
        "inspectollama": Job(("inspectollama",), "Register an Ollama server as a provider for an organization and list its models: --organization <identifier>"),
        "restore_descriptors": Job(("restore_descriptors",), "Store the descriptors of every room, message, model, collection and provider that misses one (--all: of every row)"),
    },
    setup=("ensureadmin", "ensurepartners", "restore_descriptors"),
)
