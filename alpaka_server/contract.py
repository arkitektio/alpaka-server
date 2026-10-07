"""What this image answers a hub's installer: ``arkitekt-service <verb>`` (see ``arkitekt_service.contract``).

The installer knows the hub; how this release spells its config is written here, with the
settings it is read by. A key renamed in ``configuration.py`` is renamed in :func:`render` in
the same commit, and no installer has to learn of it.
"""

from __future__ import annotations

from arkitekt_service.contract import JSON, Contract, Description, Descriptor, Facts, Hosts, Job, Needs, Offers, Scope, Signal, Start, Structure, blocks

from alpaka_server.configuration import Settings

#: What a token may be allowed to do here: defined at the coordination server when the hub enrols.
SCOPES = [
    Scope(key="alpaka_infer", description="Run inference on models"),
    Scope(key="alpaka_train", description="Train ML models"),
    Scope(key="alpaka_manage", description="Manage model registry"),
    Scope(key="read", description="Generic read access"),
    Scope(key="write", description="Generic write access"),
]

#: The roles a member of an organization can hold here.
ROLES = [
    Scope(key="admin", description="Full administrative access"),
    Scope(key="user", description="Standard user access"),
    Scope(key="modeler", description="Can manage ML models"),
    Scope(key="viewer", description="Read-only access"),
]

#: What exists on a hub because this service is there: said here, as data, so the hub knows it from
#: the image. ``service.py`` binds each of these to its model and refuses anything not said here.
HOSTS = Hosts(
    structures=[
        Structure(
            identifier="@alpaka/room",
            label="Room",
            description="A room: a conversation between users and agents.",
        ),
        Structure(
            identifier="@alpaka/message",
            label="Message",
            description="A message an agent posted in a room.",
            descriptors=[
                Descriptor(key="@alpaka/from_agent", type="BOOL", description="Whether an agent posted it"),
                Descriptor(key="@alpaka/is_reply", type="BOOL", description="Whether it replies to another message"),
            ],
        ),
        Structure(
            identifier="@alpaka/llmmodel",
            label="Llm Model",
            description="A language model reachable through one of the organization's providers.",
            descriptors=[
                Descriptor(key="@alpaka/features", type="LIST", description="What it can do (chat, embedding, ...)"),
                Descriptor(key="@alpaka/input_modalities", type="LIST", description="The modalities it accepts as input"),
                Descriptor(key="@alpaka/output_modalities", type="LIST", description="The modalities it produces as output"),
            ],
        ),
        Structure(
            identifier="@alpaka/chromacollection",
            label="Chroma Collection",
            description="A vector collection: documents searchable by meaning.",
        ),
        Structure(
            identifier="@alpaka/provider",
            label="Provider",
            description="A provider of language models, as configured by an organization.",
        ),
    ],
    signals=[
        Signal(
            identifier="@alpaka/room",
            kinds=["CREATED", "DELETED"],
            description="A room (a conversation) was created or deleted.",
        ),
        Signal(
            identifier="@alpaka/message",
            kinds=["CREATED", "UPDATED"],
            descriptors=["@alpaka/from_agent", "@alpaka/is_reply"],
            description="A message was posted in a room (a streamed reply: once it finished).",
        ),
        Signal(
            identifier="@alpaka/llmmodel",
            kinds=["CREATED", "UPDATED"],
            descriptors=["@alpaka/features", "@alpaka/input_modalities", "@alpaka/output_modalities"],
            description="A language model became available or changed (e.g. after a provider refresh).",
        ),
        Signal(
            identifier="@alpaka/chromacollection",
            kinds=["CREATED", "DELETED"],
            description="A vector collection was created or deleted.",
        ),
        Signal(
            identifier="@alpaka/provider",
            kinds=["CREATED", "UPDATED"],
            description="An LLM provider was added or changed.",
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
    },
    setup=("ensureadmin", "ensurepartners"),
)
