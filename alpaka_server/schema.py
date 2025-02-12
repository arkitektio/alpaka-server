import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension
from kante.directives import upper, replace, relation
from kammer import types as kammer_types
from kammer.graphql import mutations as kammer_mutations
from kammer.graphql import queries as kammer_queries
from kammer.graphql import subscriptions as kammer_subscriptions
from koherent.strawberry.extension import KoherentExtension
from typing import List
import strawberry_django


@strawberry.type
class Query:
    """The root query type"""

    room = strawberry_django.field(resolver=kammer_queries.room)
    rooms: List[kammer_types.Room] = strawberry_django.field()





@strawberry.type
class Mutation:
    """The root mutation type"""

    create_room = strawberry_django.mutation(resolver=kammer_mutations.create_room)

    send = strawberry_django.mutation(resolver=kammer_mutations.send)



@strawberry.type
class Subscription:
    """The root subscription type"""

    room = strawberry.subscription(resolver=kammer_subscriptions.room)


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    directives=[upper, replace, relation],
    extensions=[DjangoOptimizerExtension, KoherentExtension],
    types=[]
)
