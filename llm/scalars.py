from typing import Any, NewType

import strawberry


Base64EncodedString = NewType("Base64EncodedString", str)


scalar_map: dict[Any, Any] = {
    Base64EncodedString: strawberry.scalar(
        name="Base64EncodedString",
        description="Base64EncodedString represents an untyped options object "
        "returned by the Dask Gateway API.",
        serialize=lambda v: v,
        parse_value=lambda v: v,
    ),
}
