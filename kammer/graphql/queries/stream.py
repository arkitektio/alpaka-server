import hashlib
import json
import logging

import strawberry
from ekke.types import Info
from kammer import enums, inputs, models, scalars, types


def stream(info: Info, id: strawberry.ID) -> types.Stream:
    return models.Stream.objects.get(id=id)
