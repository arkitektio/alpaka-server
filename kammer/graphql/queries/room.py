import hashlib
import json
import logging

import strawberry
from kante.types import Info
from kammer import enums, inputs, models, scalars, types


def room(info: Info, id: strawberry.ID) -> types.Room:
    return models.Room.objects.get(id=id)
