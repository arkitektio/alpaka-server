"""The GraphQL schema.

Every root field that reads tenant-owned data goes through a resolver that names
the request's organization. ``strawberry_django.field()`` on a bare ``list[T]``
would read every organization's rows, so list fields are backed by the resolvers
in each app's ``graphql/queries`` package rather than declared directly.

A guest of the organization (``arkitekt_service.collaborations``) reads the rooms and messages put
in their collaborations, and what is part of them, and nothing else: root fields are narrowed to
them (``alpaka_server.scoping.held_to_guest``) and the ``CollaborationGate`` drops whatever a
resolver hands out that is in none of them. Their only write is ``send``, into a room of theirs.
"""

import strawberry
from alpaka_server.logs import QuietErrorsSchema
import strawberry_django
from arkitekt_service.collaborations import graphql as collaboration_types
from arkitekt_service.graphql import CollaborationGate, annotate_schema
from authentikate.strawberry import AuthExtension, AuthSubscribeExtension
from authentikate.strawberry.extension import AuthentikateExtension
from django.db.models import Model
from kante.types import Info
from koherent.strawberry.extension import KoherentExtension
from strawberry.schema.config import StrawberryConfig
from strawberry_django.optimizer import DjangoOptimizerExtension

from alpaka_server.contract import EDITOR, MANAGER
from alpaka_server.scoping import OrganizationScopedManager
from alpaka_server.service import service as alpaka_service
from kammer import models as kammer_models
from kammer import types as kammer_types
from kammer.graphql import mutations as kammer_mutations
from kammer.graphql import queries as kammer_queries
from kammer.graphql import subscriptions as kammer_subscriptions
from kammer.scalars import scalar_map as kammer_scalar_map
from llm import types as llm_types
from llm.graphql import mutations as llm_mutations
from llm.graphql import queries as llm_queries
from llm.scalars import scalar_map as llm_scalar_map
from memory import types as memory_types
from memory.graphql import mutations as memory_mutations
from memory.graphql import queries as memory_queries
from vector import types as vector_types
from vector.graphql import mutations as vector_mutations
from vector.graphql import queries as vector_queries


#: What a full member may put in a collaboration, each read through its organization. A provider
#: holds an API key, and its models and the collections they embed are the organization's to call,
#: on its credentials: none of them is shown to a guest.
SHAREABLE: dict[type[Model], OrganizationScopedManager] = {kammer_models.Room: kammer_models.Room.objects, kammer_models.Message: kammer_models.Message.objects}


def _shareable(model: type[Model], id: strawberry.ID, info: Info) -> Model:
    """The object a collaboration mutation names, in the request's organization; refused unless it is shareable."""
    manager = SHAREABLE.get(model)
    if manager is None:
        raise PermissionError(f"A {model.__name__} is never put in a collaboration: only rooms and messages are")
    found: Model = manager.for_organization(info.context.request.organization).get(id=id)
    return found


#: The collaborations of alpaka's rooms, which a guest of the organization is granted.
collaboration_api = collaboration_types.resolvers(fetch=_shareable)


def field(scope: str = "alpaka_read", **kwargs):
    "A field an app needs ``scope`` for (``alpaka_read``, unless it says otherwise)."
    return strawberry_django.field(extensions=[AuthExtension(scopes=[scope])], **kwargs)


def mutation(scope: str = "alpaka_write", roles: list[str] | None = None, guests: bool = False, **kwargs):
    """A write: an app needs ``scope`` for it, a member one of ``roles`` (``alpaka_editor`` unless it says
    otherwise; ``alpaka_admin`` holds every role).

    ``guests`` opens it to guests of the organization holding the roles in one of their collaborations:
    the resolver then checks its target is in such a collaboration (``require_in_collaboration``).
    """
    return strawberry_django.mutation(extensions=[AuthExtension(scopes=[scope], any_role_of=roles or [EDITOR], allow_scoped=guests)], **kwargs)


@strawberry.type(description="The root query type")
class Query:
    """The root query type."""

    # Collaborations
    collaborations: list[collaboration_types.Collaboration] = field(resolver=collaboration_api.collaborations, description="List the organization's collaborations: what a guest granted one sees of it (a guest: the collaborations granted to them)")
    collaboration: collaboration_types.Collaboration = field(resolver=collaboration_api.collaboration, description="Get a single collaboration by ID")

    # Rooms and messages
    room = field(resolver=kammer_queries.room, description="Get a single room by ID")
    rooms: list[kammer_types.Room] = field(description="List the rooms in this organization")
    room_stats: kammer_types.RoomStats = field(resolver=kammer_types.RoomStatsResolver, description="Aggregate statistics over this organization's rooms")

    message = field(resolver=kammer_queries.message, description="Get a single message by ID")
    messages: list[kammer_types.Message] = field(description="List the messages in this organization's rooms")

    # Providers and models
    provider = field(resolver=llm_queries.provider, description="Get a single provider by ID")
    providers: list[llm_types.Provider] = field(description="List the LLM providers configured for this organization")
    llm_model = field(resolver=llm_queries.llm_model, description="Get a single LLM model by ID")
    llm_models: list[llm_types.LLMModel] = field(description="List the LLM models reachable through this organization's providers")

    default_uses: list[llm_types.DefaultUse] = field(description="The models the caller has registered as defaults")
    default_model_for = field(resolver=llm_queries.default_model_for, description="The model the caller uses by default for one kind of task, if any")

    # Usage and budgets
    usage_records: list[llm_types.UsageRecord] = field(description="This organization's recorded LLM calls")
    usage_stats: llm_types.UsageStats = field(resolver=llm_types.UsageStatsResolver, description="Aggregate token, cost and latency statistics over this organization's LLM calls")
    budgets: list[llm_types.Budget] = field(description="This organization's budgets")
    budget = field(resolver=llm_queries.budget, description="Get a single budget by ID")
    budget_status = field(resolver=llm_queries.budget_status, description="How much of a budget is used in the current period")

    # Vector collections
    chroma_collection = field(resolver=vector_queries.chroma_collection, description="Get a single Chroma collection by ID")
    chroma_collections: list[vector_types.ChromaCollection] = field(description="List this organization's Chroma collections")
    documents = field(resolver=vector_queries.documents, description="Search a collection for the documents most similar to some text")

    # Memories: only ever the assigner's of the task the request is made for (``memory.owner``)
    memories: list[memory_types.Memory] = field(description="What is remembered about the person who assigned the task this request is made for. Needs the task's provenance token")
    memory = field(resolver=memory_queries.memory, description="Get one of the assigner's memories by ID")
    assigner = field(resolver=memory_queries.whom, description="Who assigned the task this request is made for: whose memories it reaches")


@strawberry.type(description="The root mutation type")
class Mutation:
    """The root mutation type."""

    # Collaborations
    create_collaboration = mutation(scope="alpaka_share", resolver=collaboration_api.create_collaboration, description="Create an empty collaboration, to put rooms in and grant a guest")
    add_to_collaboration = mutation(scope="alpaka_share", resolver=collaboration_api.add_to_collaboration, description="Put a room or a message in a collaboration, with what it needs to be seen: a room comes with its agents and messages")
    remove_from_collaboration = mutation(scope="alpaka_share", resolver=collaboration_api.remove_from_collaboration, description="Take a room or a message out of a collaboration, with what it brought that nothing else there needs")
    delete_collaboration = mutation(scope="alpaka_share", resolver=collaboration_api.delete_collaboration, description="Delete a collaboration: whoever was granted it sees nothing of it any more")

    # Rooms and messages
    create_room = mutation(resolver=kammer_mutations.create_room, description="Open a new room")
    delete_room = mutation(resolver=kammer_mutations.delete_room, description="Delete a room and its messages")
    # Open to a guest of the organization holding a posting role in a collaboration that holds the
    # room: the resolver checks it (``require_in_collaboration``). Every other mutation refuses guests.
    send = mutation(scope="alpaka_chat", guests=True, resolver=kammer_mutations.send, description="Post a complete message into a room")
    start_message = mutation(scope="alpaka_chat", resolver=kammer_mutations.start_message, description="Open a message to stream text into. Only the starting agent (same user and client) can append to or finish it.")
    append_message = mutation(scope="alpaka_chat", resolver=kammer_mutations.append_message, description="Append a delta to a streaming message. Batch deltas (every ~100-250 ms or ~30 characters) and await each call before sending the next, so they arrive in order.")
    finish_message = mutation(scope="alpaka_chat", resolver=kammer_mutations.finish_message, description="Close a streaming message. Pass the full final text so any delta lost on the way is repaired; call it in a finally block so a crashed stream never stays open.")

    # Providers and models
    create_provider = mutation(scope="alpaka_providers", roles=[MANAGER], resolver=llm_mutations.create_provider, description="Configure a new LLM provider and list the models it offers")
    update_provider = mutation(scope="alpaka_providers", roles=[MANAGER], resolver=llm_mutations.update_provider, description="Update a provider in place, e.g. to rotate its credential")
    refresh_provider = mutation(scope="alpaka_providers", roles=[MANAGER], resolver=llm_mutations.refresh_provider, description="Re-list the models a provider offers")
    delete_provider = mutation(scope="alpaka_providers", roles=[MANAGER], resolver=llm_mutations.delete_provider, description="Delete a provider and the models it offers")
    pull = mutation(scope="alpaka_providers", roles=[MANAGER], resolver=llm_mutations.pull, description="Pull a model into an Ollama provider, or a decision model into an Ollaya provider")
    use_model_for = mutation(resolver=llm_mutations.use_model_for, description="Register a model as the caller's default for a kind of task")

    # Budgets
    create_budget = mutation(scope="alpaka_providers", roles=[MANAGER], resolver=llm_mutations.create_budget, description="Cap this organization's LLM consumption, optionally for one user and/or model")
    update_budget = mutation(scope="alpaka_providers", roles=[MANAGER], resolver=llm_mutations.update_budget, description="Change a budget's period, limits or hardness")
    delete_budget = mutation(scope="alpaka_providers", roles=[MANAGER], resolver=llm_mutations.delete_budget, description="Remove a budget")

    # Inference
    chat = mutation(scope="alpaka_chat", resolver=llm_mutations.chat, description="Send a chat completion request")
    generate_image = mutation(scope="alpaka_chat", resolver=llm_mutations.generate_image, description="Generate an image from a text description")
    decide = mutation(scope="alpaka_chat", resolver=llm_mutations.decide, description="Ask a decision model typed questions (noul, choice, score) about one state, and get calibrated answers")

    # Vector collections
    create_collection = mutation(resolver=vector_mutations.create_collection, description="Create a searchable collection of documents")
    ensure_collection = mutation(resolver=vector_mutations.ensure_collection, description="Create a collection, or update it if it already exists")
    delete_collection = mutation(resolver=vector_mutations.delete_collection, description="Delete a collection and its documents")
    add_documents_to_collection = mutation(resolver=vector_mutations.add_documents_to_collection, description="Embed documents and add them to a collection")

    # Memories
    remember = mutation(resolver=memory_mutations.remember, description="Remember something about the person who assigned the task, replacing the memory of that name. Needs the task's provenance token")
    forget = mutation(resolver=memory_mutations.forget, description="Forget one of the assigner's memories by name; whether there was one")


@strawberry.type(description="The root subscription type")
class Subscription:
    """The root subscription type."""

    room = strawberry.subscription(resolver=kammer_subscriptions.room, extensions=[AuthSubscribeExtension(scopes=["alpaka_read"])], description="Join a room and receive its events: messages created, streamed into and finished, and agents joining or leaving")


class Schema(QuietErrorsSchema, strawberry.federation.Schema):
    """strawberry.federation.Schema, logging expected resolver errors as one line and bugs with a traceback (see logs.py)."""


schema = Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    # A guest of the organization is handed only what is in their collaborations (CollaborationGate).
    extensions=[DjangoOptimizerExtension, AuthentikateExtension, CollaborationGate, KoherentExtension],
    types=[llm_types.Provider, llm_types.LLMModel, vector_types.ChromaCollection],
    config=StrawberryConfig(scalar_map={**kammer_scalar_map, **llm_scalar_map}),
)

# Which structure each type is (`@identified`), and, behind the gate, that alpaka lets guests in.
annotate_schema(schema, alpaka_service)
