"""What alpaka's objects say about themselves: the describers ``alpaka_server.service`` binds, and how GraphQL asks for them.

Each describer is stored on the row whenever it is saved (``stored_descriptors``), so a port's
``requires`` is answered by one indexed query (the ``requires`` filter of a list) and a signal
carries what a picker filters on. A describer reads the row and what it points at; what a save of
the row cannot see (agents joining a room, structures attached after the insert, a provider's
kind changing under its models) is restored by whoever writes it (``alpaka_server.service``).

Nothing secret is described: a provider says what kind it is, never its key or its endpoint.
"""

from enum import Enum

import strawberry
from django.db.models import Q
from strawberry.scalars import JSON

from kammer import models as kammer_models
from llm import models as llm_models
from llm.enums import ProviderKind
from vector import models as vector_models

Descriptors = dict[str, int | str | bool | list[str]]


DESCRIPTORS_DESCRIPTION = (
    "This object's descriptors, a flat mapping of key to value: the facts about it that an action's port can `require` and a trigger can test "
    "(e.g. `@alpaka/is_reply`). The keys are the ones alpaka declares for this structure, and the values are the ones a signal about the object carries. "
    "Empty for a structure that declares none"
)


def resolve_descriptors(root) -> JSON:  # noqa: ANN001 - the model instance behind any hosted type
    """The descriptors of a hosted object, as they are stored on it (``alpaka_server.service``)."""
    from alpaka_server.service import service  # the declaration imports the apps' models

    return service.describe(root)


# --- the describers ----------------------------------------------------------------------


def _kind(provider: llm_models.Provider) -> str:
    """The provider's kind as it is stored: a row read back holds the value, one just built may hold the member."""
    return ProviderKind(provider.kind).value


def room_descriptors(room: kammer_models.Room) -> Descriptors:
    """A room's descriptors: what it is about, and how many agents take part in it."""
    return {
        "@alpaka/contextual_structures": sorted(set(room.contextual_structures.values_list("identifier", flat=True))),
        "@alpaka/n_agents": room.agents.count(),
    }


def message_descriptors(message: kammer_models.Message) -> Descriptors:
    """A message's descriptors: who posted it, whether it answers another, and what it was posted about."""
    return {
        "@alpaka/from_agent": message.agent_id is not None,
        "@alpaka/is_reply": message.is_reply_to_id is not None,
        "@alpaka/attached_structures": sorted(set(message.attached_structures.values_list("identifier", flat=True))),
    }


def provider_descriptors(provider: llm_models.Provider) -> Descriptors:
    """A provider's descriptors: its kind, and nothing else (the row holds an API key)."""
    return {"@alpaka/provider_kind": _kind(provider)}


def llm_model_descriptors(model: llm_models.LLMModel) -> Descriptors:
    """A model's descriptors: what it can do, what it reads and writes, and the kind of provider that runs it."""
    return {
        "@alpaka/features": list(model.features or []),
        "@alpaka/input_modalities": list(model.input_modalities or []),
        "@alpaka/output_modalities": list(model.output_modalities or []),
        "@alpaka/provider_kind": _kind(model.provider),
    }


def collection_descriptors(collection: vector_models.ChromaCollection) -> Descriptors:
    """A collection's descriptors: the model its documents are embedded by (a query must be embedded by the same)."""
    return {"@alpaka/embedder": collection.embedder.model_id}


# --- a port's requires, as a list filter ---------------------------------------------------


@strawberry.enum(description="How a descriptor constraint compares the object's value with the stated one. The operators a rekuest port's `requires` and `provides` are written in, with the same meaning.")
class DescriptorOperator(str, Enum):
    """The comparison of one constraint."""

    EQUALS = "EQUALS"
    MATCHES = "MATCHES"
    NOT_EQUALS = "NOT_EQUALS"
    GTE = "GTE"
    LTE = "LTE"
    EXISTS = "EXISTS"
    CONTAINS = "CONTAINS"
    IN = "IN"
    NOT_IN = "NOT_IN"


@strawberry.input(
    description=(
        "One constraint on an object's descriptors, in the shape a rekuest port states its `requires` in -- so a picker hands a port's constraints on unchanged. "
        "`key` is one of the keys the structure declares (e.g. `@alpaka/provider_kind`); a key it does not declare is refused."
    )
)
class DescriptorConstraintInput:
    """One ``{key, operator, value}`` constraint."""

    key: str = strawberry.field(description="The descriptor key, e.g. `@alpaka/provider_kind`")
    operator: DescriptorOperator = strawberry.field(description="How the object's value is compared with `value`. MATCHES is equality, as EQUALS is")
    value: JSON | None = strawberry.field(default=None, description="The value compared against: a number for GTE and LTE, a list for IN and NOT_IN, true or false for EXISTS, the member looked for with CONTAINS")


REQUIRES_DESCRIPTION = (
    "Filter to the objects satisfying every one of these descriptor constraints: the `requires` of a port, handed on unchanged, so a picker offers what the port accepts. "
    "Answered from the stored descriptors, in one indexed query"
)


def requires(model: type, value: list[DescriptorConstraintInput], prefix: str) -> Q:
    """A port's ``requires`` on the stored descriptors of ``model``'s rows."""
    from alpaka_server.service import service  # it imports the models this module describes

    return service.requires(model, value, prefix)
