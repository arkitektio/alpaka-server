from typing import NewType

import strawberry

Base64EncodedString = strawberry.scalar(
    NewType("Base64EncodedString", str),
    description="Base64EncodedString represents an untyped options object returned by the Dask Gateway API.",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)
