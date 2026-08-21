import datetime
import json
from enum import Enum
from typing import Annotated, Any, Dict, ForwardRef, List, Literal, Optional, Union

import strawberry
import strawberry_django
from kante.types import Info
from kammer import enums, filters, models, scalars
from authentikate.strawberry.types import Client, Organization, User
from strawberry import scalars
from .type_gen import create_stats_type
import kante
from strawberry_django.pagination import OffsetPaginationInput


def build_prescoper(field="organization"):
    """Build a prescoper binding stats queries to the request's organization.

    ``create_stats_type`` hands the prescoper the model's *manager*, not a
    queryset, so this goes through ``for_organization`` — which is both the
    scoped entry point and the only way to get a queryset out of
    :class:`~alpaka_server.scoping.OrganizationScopedManager` at all.

    The previous implementation consulted
    ``info.variable_values["filters"]["scope"]`` for a custom scope, which only
    ever saw filters passed as a GraphQL variable literally named ``filters`` —
    an inline argument bypassed it, and an explicitly-null variable made it
    raise. No caller can select a scope, so the organization filter is now
    unconditional.
    """

    def prescoper(manager, info):
        organization = info.context.request.organization
        if field == "organization":
            return manager.for_organization(organization)
        return manager.for_write().filter(**{field: organization})

    return prescoper


@kante.django_type(models.Room, pagination=True, filters=filters.RoomFilter, ordering=filters.RoomOrder, description="A room agents and users converse in")
class Room:
    """A room agents and users converse in."""

    @classmethod
    def get_queryset(cls, queryset, info, **kwargs):
        """Restrict every read of this type to the request's organization."""
        return queryset.filter(organization=info.context.request.organization)

    @classmethod
    async def resolve_reference(cls, info, id: strawberry.ID):
        """Resolve a federated reference, scoped to the request's organization.

        ``_entities`` resolves by ``__typename`` + ``id`` and does not go through
        the singular query resolvers or ``get_queryset``, so without this it is a
        second, unguarded door onto every row of this type.

        Async because the entity resolver runs in an async context and hands the
        returned awaitable straight back to graphql-core.
        """
        return await models.Room.objects.for_organization(info.context.request.organization).aget(id=id)

    id: strawberry.ID
    title: str
    description: Optional[str]
    messages: list["Message"]
    agents: list["Agent"]
    organization: Organization
    creator: Optional[User]
    created_at: datetime.datetime


RoomStats, RoomStatsResolver = create_stats_type(
    model=models.Room,
    filters=filters.RoomFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
    prescope=build_prescoper(field="organization"),
)


@kante.django_type(models.Agent, pagination=True, filters=filters.AgentFilter, ordering=filters.AgentOrder, description="A participant in a room")
class Agent:
    """A participant in a room — a user acting through one client."""

    @classmethod
    def get_queryset(cls, queryset, info, **kwargs):
        """Restrict every read of this type to the request's organization."""
        return queryset.filter(room__organization=info.context.request.organization)

    @classmethod
    async def resolve_reference(cls, info, id: strawberry.ID):
        """Resolve a federated reference, scoped to the request's organization.

        ``_entities`` resolves by ``__typename`` + ``id`` and does not go through
        the singular query resolvers or ``get_queryset``, so without this it is a
        second, unguarded door onto every row of this type.

        Async because the entity resolver runs in an async context and hands the
        returned awaitable straight back to graphql-core.
        """
        return await models.Agent.objects.for_organization(info.context.request.organization).aget(id=id)

    id: strawberry.ID
    room: Room
    # AgentOrder and AgentFilter both sort and search on `name`, so it has to be
    # readable as well as orderable.
    name: Optional[str]
    user: User
    client: Client


@kante.django_type(models.Message, pagination=True, filters=filters.MessageFilter, ordering=filters.MessageOrder)
class Message:
    """A message an agent posted in a room."""

    @classmethod
    def get_queryset(cls, queryset, info, **kwargs):
        """Restrict every read of this type to the request's organization."""
        return queryset.filter(room__organization=info.context.request.organization)

    @classmethod
    async def resolve_reference(cls, info, id: strawberry.ID):
        """Resolve a federated reference, scoped to the request's organization.

        ``_entities`` resolves by ``__typename`` + ``id`` and does not go through
        the singular query resolvers or ``get_queryset``, so without this it is a
        second, unguarded door onto every row of this type.

        Async because the entity resolver runs in an async context and hands the
        returned awaitable straight back to graphql-core.
        """
        return await models.Message.objects.for_organization(info.context.request.organization).aget(id=id)

    id: strawberry.ID
    text: str
    room: Room
    agent: Agent
    attached_structures: List[Annotated["Structure", strawberry.lazy("vector.types")]] = strawberry_django.field(description="The objects this message was posted about")
    created_at: datetime.datetime
    is_streaming: bool = strawberry_django.field(description="Whether this message is still being written")
    is_reply_to: Optional["Message"] = strawberry_django.field(description="The message this one replies to, if any")
    replies: List["Message"] = strawberry_django.field(description="The messages replying to this one")
    targets: List[Agent] = strawberry_django.field(description="The agents this message is addressed to")
    descendants: scalars.JSON = strawberry_django.field(description="The rich-text representation of the message")

    @kante.django_field
    def before(self, info: Info, filters: filters.MessageFilter | None = None, pagination: OffsetPaginationInput | None = None) -> List["Message"]:
        """Get the messages posted before this one in the same room."""
        # `room` is the direct FK — `agent__room` reached the same row through a
        # join, and only by the invariant that send() writes both consistently.
        # `self.room` was already resolved through a scoped read, so filtering
        # by it is the scope; `for_write` here just names the unfiltered queryset.
        qs = models.Message.objects.for_write().filter(room=self.room, created_at__lt=self.created_at).order_by("-created_at")
        if filters:
            qs = strawberry_django.filters.apply(filters, qs, info)
        if pagination:
            offset = pagination.offset or 0
            # `limit` is optional, and slicing by `offset + None` raised.
            qs = qs[offset : offset + pagination.limit] if pagination.limit is not None else qs[offset:]
        return qs

    @kante.django_field
    def title(self, info: Info) -> str:
        """Get the title of the message, which is the first 5 words"""
        return " ".join(self.text.split()[:5])
