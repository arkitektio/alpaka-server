import datetime
import json
from enum import Enum
from typing import Any, Dict, ForwardRef, List, Literal, Optional, Union

import strawberry
from strawberry import LazyType
import strawberry_django
from kante.types import Info
from kammer import enums, filters, models, scalars
from authentikate.strawberry.types import Client, User, Organization
from .type_gen import create_stats_type


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


@strawberry_django.type(models.Room, pagination=True, filters=filters.RoomFilter)
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


@strawberry_django.type(models.Agent, pagination=True)
class Agent:
    id: strawberry.ID
    room: Room


@strawberry_django.type(models.Message, pagination=True, filters=filters.MessageFilter)
class Message:
    id: strawberry.ID
    title: str
    text: str
    agent: Agent
    attached_structures: List[LazyType["Structure", "vector.types"]] = strawberry_django.field(description="The collections that can be embedded with this model")
    created_at: datetime.datetime
