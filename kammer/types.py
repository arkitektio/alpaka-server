import datetime
import json
from enum import Enum
from typing import Any, Dict, ForwardRef, List, Literal, Optional, Union

import strawberry
from strawberry import LazyType
import strawberry_django
from kante.types import Info
from kammer import enums, filters, models, scalars
from authentikate.strawberry.types import Client, User



@strawberry_django.type(models.Room, pagination=True, filters=filters.RoomFilter)
class Room:
    id: strawberry.ID
    title: str
    description: str
    messages: list["Message"]
    agents: list["Agent"]



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
    attached_structures: List[LazyType["Structure", "vector.types"]] = strawberry_django.field(
        description="The collections that can be embedded with this model"
    )
    created_at: datetime.datetime
