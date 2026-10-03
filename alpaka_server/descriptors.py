"""The ``descriptors`` field of every hosted GraphQL type, answered from the structure's declaration (``alpaka_server.service``)."""

from strawberry.scalars import JSON

DESCRIPTORS_DESCRIPTION = (
    "This object's descriptors, a flat mapping of key to value: the facts about it that an action's port can `require` and a trigger can test "
    "(e.g. `@alpaka/is_reply`). The keys are the ones alpaka declares for this structure, and the values are the ones a signal about the object carries. "
    "Empty for a structure that declares none"
)


def resolve_descriptors(root) -> JSON:  # noqa: ANN001 - the model instance behind any hosted type
    """The descriptors of a hosted object, from its structure's declaration (``alpaka_server.service``)."""
    from alpaka_server.service import service  # the declaration imports the apps' models

    return service.describe(root)
