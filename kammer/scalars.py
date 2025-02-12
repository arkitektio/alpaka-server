from typing import NewType
import strawberry

Identifier = strawberry.scalar(
    NewType("Identifier", str),
    description="The `Identifier` scalasr typsse represents a reference to a store "
    "previously created by the user n a datalayer",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


UnsafeChild = strawberry.scalar(
    NewType("UnsafeChild", object),
    description="The `Identifier` scalasr typsse represents a reference to a store "
    "previously created by the user n a datalayer",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)
