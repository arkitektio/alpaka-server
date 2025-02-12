from typing import Any, Optional

import strawberry
from komment import enums, scalars
from pydantic import BaseModel
from strawberry import LazyType
from strawberry.experimental import pydantic


class DescendandInputModel(BaseModel):
    kind: enums.DescendantKind
    children: list["DescendandInputModel"] | None
    user: str | None
    bold: bool | None
    italic: bool | None
    code: bool | None
    text: str | None


@pydantic.input(DescendandInputModel)
class DescendantInput:
    kind: enums.DescendantKind
    children: list[LazyType["DescendantInput", __name__]] | None
    user: str | None
    bold: bool | None
    italic: bool | None
    code: bool | None
    text: str | None
