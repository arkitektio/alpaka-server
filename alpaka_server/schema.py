import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension
from kante.directives import upper, replace, relation
from bridge import types
from bridge import mutations
from bridge import subscriptions
from bridge import queries
from bridge import messages
import strawberry_django
from koherent.strawberry.extension import KoherentExtension
from typing import List
from rekuest_core.constants import interface_types


@strawberry.type
class Query:
    """The root query type"""

    github_repo: types.GithubRepo = strawberry_django.field(
        resolver=queries.github_repo, description="Return all dask clusters"
    )
    definition: types.Definition = strawberry_django.field(
        resolver=queries.definition, description="Return all dask clusters"
    )
    release: types.Release = strawberry_django.field(
        resolver=queries.release, description="Return all dask clusters"
    )
    flavour: types.Flavour = strawberry_django.field(
        resolver=queries.flavour, description="Return all dask clusters"
    )
    deployment: types.Deployment = strawberry_django.field(
        resolver=queries.deployment, description="Return all dask clusters"
    )
    backend: types.Backend = strawberry_django.field(
        resolver=queries.backend, description="Return all dask clusters"
    )
    pod: types.Pod = strawberry_django.field(
        resolver=queries.pod, description="Return all dask clusters"
    )
    me: types.User = strawberry_django.field(
        resolver=queries.me, description="Return the currently logged in user"
    )
    match_flavour: types.Flavour = strawberry_django.field(
        resolver=queries.match_flavour,
        description="Return the currently logged in user",
    )
    flavours: List[types.Flavour] = strawberry_django.field()
    releases: List[types.Release] = strawberry_django.field()
    deployments: List[types.Deployment] = strawberry_django.field()
    github_repos: List[types.GithubRepo] = strawberry_django.field()
    definitions: List[types.Definition] = strawberry_django.field()
    pods: List[types.Pod] = strawberry_django.field()

    backends: List[types.Backend]= strawberry_django.field()





@strawberry.type
class Mutation:
    """The root mutation type"""

    scan_repo: types.GithubRepo = strawberry_django.mutation(
        resolver=mutations.scan_repo,
        description="Create a new dask cluster on a bridge server",
    )
    create_github_repo: types.GithubRepo = strawberry_django.mutation(
        resolver=mutations.create_github_repo,
        description="Create a new Github repository on a bridge server",
    )
    create_deployment: types.Deployment = strawberry_django.mutation(
        resolver=mutations.create_deployment,
        description="Create a new dask cluster on a bridge server",
    )
    update_deployment: types.Deployment = strawberry_django.mutation(
        resolver=mutations.update_deployment,
        description="Create a new dask cluster on a bridge server",
    )
    create_pod: types.Pod = strawberry_django.mutation(
        resolver=mutations.create_pod,
        description="Create a new dask cluster on a bridge server",
    )
    update_pod: types.Pod = strawberry_django.mutation(
        resolver=mutations.update_pod,
        description="Create a new dask cluster on a bridge server",
    )
    dump_logs: types.LogDump = strawberry_django.mutation(
        resolver=mutations.dump_logs,
        description="Create a new dask cluster on a bridge server",
    )
    declare_backend: types.Backend = strawberry_django.mutation(
        resolver=mutations.declare_backend,
        description="Create a new dask cluster on a bridge server",
    )


@strawberry.type
class Subscription:
    """The root subscription type"""

    pod: messages.PodUpdateMessage = strawberry.subscription(
        resolver=subscriptions.pod,
        description="Create a new dask cluster on a bridge server",
    )
    pods: messages.PodUpdateMessage = strawberry.subscription(
        resolver=subscriptions.pods,
        description="Create a new dask cluster on a bridge server",
    )


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    directives=[upper, replace, relation],
    extensions=[DjangoOptimizerExtension, KoherentExtension],
    types=[types.Selector, types.CudaSelector, types.CPUSelector] + interface_types,
)
