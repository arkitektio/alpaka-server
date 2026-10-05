"""What this image answers a hub's installer: ``python -m arkitekt_service <verb>`` (see ``arkitekt_service.contract``).

The installer knows the hub; how this release spells its config is written here, with the
settings it is read by. A key renamed in ``configuration.py`` is renamed in :func:`render` in
the same commit, and no installer has to learn of it.
"""

from __future__ import annotations

from arkitekt_service.contract import JSON, Contract, Description, Facts, Needs, Offers, Scope, blocks

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
        summary="Language models for the hub.",
        needs=Needs(scopes=SCOPES, roles=ROLES, storage=["media"], instance_key=True, peers=["rekuest", "ollama"]),
        offers=Offers(endpoints={"rekuest_service": "_rekuest/service", "rekuest_hook": "_rekuest/hook"}),
        requires={"rekuest": ">=6"},
    ),
    settings=Settings,
    render=render,
    setup=(("ensureadmin",), ("ensurepartners",)),
)
