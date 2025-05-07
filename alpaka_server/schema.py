import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension
from kammer import types as kammer_types
from kammer.graphql import mutations as kammer_mutations
from kammer.graphql import queries as kammer_queries
from kammer.graphql import subscriptions as kammer_subscriptions
from llm.graphql import mutations as llm_mutations
from llm import types as llm_types
from llm import models as llm_models
from vector.graphql import queries as vector_queries
from vector.graphql import mutations as vector_mutations
from vector import types as vector_types
from vector import models as vector_models
from koherent.strawberry.extension import KoherentExtension
from authentikate.strawberry.extension import AuthentikateExtension
from typing import List
import strawberry_django


@strawberry.type
class Query:
    """The root query type"""

    room = strawberry_django.field(resolver=kammer_queries.room)
    rooms: list[kammer_types.Room] = strawberry_django.field()

    providers: list[llm_types.Provider] = strawberry_django.field()
    llm_models: list[llm_types.LLMModel] = strawberry_django.field()
    
    
    chroma_collections: list[vector_types.ChromaCollection] = strawberry_django.field()
    
    documents = strawberry_django.field(resolver=vector_queries.documents)
    

    @strawberry_django.field
    def llm_model(self, id: strawberry.ID) -> llm_types.LLMModel:
        """Get a single LLM model by ID"""
        return llm_models.LLMModel.objects.get(id=id)
    
    
    @strawberry_django.field
    def chroma_collection(self, id: strawberry.ID) -> vector_types.ChromaCollection:
        """Get a single Chroma collection by ID"""
        return vector_models.ChromaCollection.objects.get(id=id)
    
    @strawberry_django.field
    def provider(self, id: strawberry.ID) -> llm_types.Provider:
        """Get a single Chroma collection by ID"""
        return llm_models.Provider.objects.get(id=id)
    
    
    


@strawberry.type
class Mutation:
    """The root mutation type"""

    create_room = strawberry_django.mutation(resolver=kammer_mutations.create_room)

    delete_room = strawberry_django.mutation(resolver=kammer_mutations.delete_room)
    create_provider = strawberry_django.mutation(resolver=llm_mutations.create_provider)

    send = strawberry_django.mutation(resolver=kammer_mutations.send)
    chat = strawberry_django.mutation(resolver=llm_mutations.chat)
    pull = strawberry_django.mutation(resolver=llm_mutations.pull)
    
    create_collection = strawberry_django.mutation(resolver=vector_mutations.create_collection)
    ensure_collection = strawberry_django.mutation(resolver=vector_mutations.ensure_collection)
    delete_collection = strawberry_django.mutation(resolver=vector_mutations.delete_collection)
    add_documents_to_collection = strawberry_django.mutation(resolver=vector_mutations.add_documents_to_collection)


@strawberry.type
class Subscription:
    """The root subscription type"""

    room = strawberry.subscription(resolver=kammer_subscriptions.room)


schema = strawberry.Schema(query=Query, mutation=Mutation, subscription=Subscription, extensions=[DjangoOptimizerExtension, AuthentikateExtension, KoherentExtension], types=[])
