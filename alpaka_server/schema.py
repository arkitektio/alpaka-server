"""The GraphQL schema.

Every root field that reads tenant-owned data goes through a resolver that names
the request's organization. ``strawberry_django.field()`` on a bare ``list[T]``
would read every organization's rows, so list fields are backed by the resolvers
in each app's ``graphql/queries`` package rather than declared directly.
"""

import strawberry
import strawberry_django
from authentikate.strawberry.extension import AuthentikateExtension
from koherent.strawberry.extension import KoherentExtension
from strawberry.schema.config import StrawberryConfig
from strawberry_django.optimizer import DjangoOptimizerExtension

from kammer import types as kammer_types
from kammer.graphql import mutations as kammer_mutations
from kammer.graphql import queries as kammer_queries
from kammer.graphql import subscriptions as kammer_subscriptions
from kammer.scalars import scalar_map as kammer_scalar_map
from llm import types as llm_types
from llm.graphql import mutations as llm_mutations
from llm.graphql import queries as llm_queries
from llm.scalars import scalar_map as llm_scalar_map
from vector import types as vector_types
from vector.graphql import mutations as vector_mutations
from vector.graphql import queries as vector_queries


@strawberry.type(description="The root query type")
class Query:
    """The root query type."""

    # Rooms and messages
    room = strawberry_django.field(resolver=kammer_queries.room, description="Get a single room by ID")
    rooms: list[kammer_types.Room] = strawberry_django.field(description="List the rooms in this organization")
    room_stats: kammer_types.RoomStats = strawberry_django.field(resolver=kammer_types.RoomStatsResolver, description="Aggregate statistics over this organization's rooms")

    message = strawberry_django.field(resolver=kammer_queries.message, description="Get a single message by ID")
    messages: list[kammer_types.Message] = strawberry_django.field(description="List the messages in this organization's rooms")

    # Providers and models
    provider = strawberry_django.field(resolver=llm_queries.provider, description="Get a single provider by ID")
    providers: list[llm_types.Provider] = strawberry_django.field(description="List the LLM providers configured for this organization")
    llm_model = strawberry_django.field(resolver=llm_queries.llm_model, description="Get a single LLM model by ID")
    llm_models: list[llm_types.LLMModel] = strawberry_django.field(description="List the LLM models reachable through this organization's providers")

    default_uses: list[llm_types.DefaultUse] = strawberry_django.field(description="The models the caller has registered as defaults")
    default_model_for = strawberry_django.field(resolver=llm_queries.default_model_for, description="The model the caller uses by default for one kind of task, if any")

    # Vector collections
    chroma_collection = strawberry_django.field(resolver=vector_queries.chroma_collection, description="Get a single Chroma collection by ID")
    chroma_collections: list[vector_types.ChromaCollection] = strawberry_django.field(description="List this organization's Chroma collections")
    documents = strawberry_django.field(resolver=vector_queries.documents, description="Search a collection for the documents most similar to some text")


@strawberry.type(description="The root mutation type")
class Mutation:
    """The root mutation type."""

    # Rooms and messages
    create_room = strawberry_django.mutation(resolver=kammer_mutations.create_room, description="Open a new room")
    delete_room = strawberry_django.mutation(resolver=kammer_mutations.delete_room, description="Delete a room and its messages")
    send = strawberry_django.mutation(resolver=kammer_mutations.send, description="Post a message into a room")

    # Providers and models
    create_provider = strawberry_django.mutation(resolver=llm_mutations.create_provider, description="Configure a new LLM provider and list the models it offers")
    update_provider = strawberry_django.mutation(resolver=llm_mutations.update_provider, description="Update a provider in place, e.g. to rotate its credential")
    refresh_provider = strawberry_django.mutation(resolver=llm_mutations.refresh_provider, description="Re-list the models a provider offers")
    delete_provider = strawberry_django.mutation(resolver=llm_mutations.delete_provider, description="Delete a provider and the models it offers")
    pull = strawberry_django.mutation(resolver=llm_mutations.pull, description="Pull a model into an Ollama provider")
    use_model_for = strawberry_django.mutation(resolver=llm_mutations.use_model_for, description="Register a model as the caller's default for a kind of task")

    # Inference
    chat = strawberry_django.mutation(resolver=llm_mutations.chat, description="Send a chat completion request")
    generate_image = strawberry_django.mutation(resolver=llm_mutations.generate_image, description="Generate an image from a text description")

    # Vector collections
    create_collection = strawberry_django.mutation(resolver=vector_mutations.create_collection, description="Create a searchable collection of documents")
    ensure_collection = strawberry_django.mutation(resolver=vector_mutations.ensure_collection, description="Create a collection, or update it if it already exists")
    delete_collection = strawberry_django.mutation(resolver=vector_mutations.delete_collection, description="Delete a collection and its documents")
    add_documents_to_collection = strawberry_django.mutation(resolver=vector_mutations.add_documents_to_collection, description="Embed documents and add them to a collection")


@strawberry.type(description="The root subscription type")
class Subscription:
    """The root subscription type."""

    room = strawberry.subscription(resolver=kammer_subscriptions.room, description="Join a room and receive its messages as they are posted")


schema = strawberry.federation.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    extensions=[DjangoOptimizerExtension, AuthentikateExtension, KoherentExtension],
    types=[llm_types.Provider, llm_types.LLMModel, vector_types.ChromaCollection],
    config=StrawberryConfig(scalar_map={**kammer_scalar_map, **llm_scalar_map}),
)
