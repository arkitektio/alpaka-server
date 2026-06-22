import datetime
import json
from enum import Enum
from typing import Annotated, Any, Dict, ForwardRef, List, Literal, Optional, Union

import strawberry
import strawberry_django
from kante.types import Info
from kammer import enums, filters, models, scalars
from authentikate.strawberry.types import Client, User, Organization
from .type_gen import create_stats_type
import kante
from strawberry_django.pagination import OffsetPaginationInput


def build_prescoped_queryset(info, queryset, field="organization"):
    print(info)
    if info.variable_values.get("filters", {}).get("scope") is None:
        queryset = queryset.filter(**{field: info.context.request.organization})
        return queryset

    else:
        raise Exception("Custom scopes not implemented yet")


def build_prescoper(field="organization"):
    def prescoper(queryset, info):
        return build_prescoped_queryset(info, queryset, field=field)

    return prescoper


@strawberry_django.type(models.Room, pagination=True, filters=filters.RoomFilter, ordering=filters.RoomOrder)
class Room:
    id: strawberry.ID
    title: str
    description: str
    messages: list["Message"]
    agents: list["Agent"]
    organization: Organization


RoomStats, RoomStatsResolver = create_stats_type(
    model=models.Room,
    filters=filters.RoomFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
    prescope=build_prescoper(field="organization"),
)


@strawberry_django.type(models.Agent, pagination=True, filters=filters.AgentFilter, ordering=filters.AgentOrder)
class Agent:
    id: strawberry.ID
    room: Room


@kante.django_type(models.Message, pagination=True, filters=filters.MessageFilter, ordering=filters.MessageOrder)
class Message:
    id: strawberry.ID
    text: str
    room: Room
    agent: Agent
    attached_structures: List[Annotated["Structure", strawberry.lazy("vector.types")]] = strawberry_django.field(description="The collections that can be embedded with this model")
    created_at: datetime.datetime

    @kante.django_field
    def before(self, info: Info, filters: filters.MessageFilter | None = None, pagination: OffsetPaginationInput | None = None) -> List["Message"]:
        """Get the message before this one in the same room"""
        qs = models.Message.objects.filter(room=self.agent.room, created_at__lt=self.created_at).order_by("-created_at")
        if filters:
            qs = strawberry_django.filters.apply(filters, qs, info)
        if pagination:
            qs = qs[pagination.offset or 0 : (pagination.offset or 0) + pagination.limit]
        return qs

    @kante.django_field
    def title(self, info: Info) -> str:
        """Get the title of the message, which is the first 5 words"""
        return " ".join(self.text.split()[:5])
