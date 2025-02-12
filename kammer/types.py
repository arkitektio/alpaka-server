import datetime
import json
from enum import Enum
from typing import Any, Dict, ForwardRef, Literal, Optional, Union

import strawberry
import strawberry_django
from kante.types import Info
from kammer import enums, filters, models, scalars


@strawberry_django.type(models.Structure, pagination=True)
class Structure:
    id: strawberry.ID
    object: strawberry.ID
    identifier: str


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
    attached_structures: list[Structure]
