from typing import Any, NewType
import strawberry


Identifier = NewType("Identifier", str)
UnsafeChild = NewType("UnsafeChild", object)
Map = NewType("Map", object)


scalar_map: dict[Any, Any] = {
    Identifier: strawberry.scalar(
        name="Identifier",
        description="The `Identifier` scalar type represents a reference to a store "
        "previously created by the user in a datalayer",
        serialize=lambda v: v,
        parse_value=lambda v: v,
    ),
    UnsafeChild: strawberry.scalar(
        name="UnsafeChild",
        description="The `UnsafeChild` scalar type represents an arbitrary, "
        "unvalidated child value",
        serialize=lambda v: v,
        parse_value=lambda v: v,
    ),
    Map: strawberry.scalar(
        name="Map",
        description="The `Map` scalar type represents an arbitrary key-value "
        "mapping (a JSON object) of strings to values.",
        serialize=lambda v: v,
        parse_value=lambda v: v,
    ),
}
