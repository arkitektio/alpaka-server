"""What this image answers a hub's installer: ``python -m hub_contract <verb>`` (see ``hub_contract``).

The installer knows the hub; how this release spells its config is written here, with the
settings it is read by. A key renamed in ``configuration.py`` is renamed in :func:`render` in
the same commit, and no installer has to learn of it.
"""

from __future__ import annotations

from hub_contract import JSON, Contract, Description, Facts, Needs, Offers, blocks

from alpaka_server.configuration import Settings


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
        needs=Needs(storage=["media"], instance_key=True, peers=["rekuest", "ollama"]),
        offers=Offers(endpoints={"rekuest_service": "_rekuest/service", "rekuest_hook": "_rekuest/hook"}),
        requires={"rekuest": ">=6"},
    ),
    settings=Settings,
    render=render,
)
