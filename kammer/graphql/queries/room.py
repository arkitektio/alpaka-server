import hashlib
import json
import logging

import strawberry
from ekke.types import Info
from kammer import enums, inputs, models, scalars, types


def room(info: Info, id: strawberry.ID) -> types.Room:
    return models.Room.objects.get(id=id)
