"""The types the suite's fixtures hand to tests."""

from collections.abc import Awaitable
from typing import Any, Protocol, TypedDict

from kante.context import HttpContext, WsContext
from strawberry.types import ExecutionResult


class BackendStack(TypedDict):
    """The host ports the test stack's services came up on."""

    db: int
    ollaya: int
    faketypesafe: int


class AExecute(Protocol):
    """``aexecute``: run a GraphQL document against the schema, as the authed context by default."""

    def __call__(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        context: HttpContext | WsContext | None = None,
    ) -> Awaitable[ExecutionResult]: ...


class WsContexts(Protocol):
    """``ws_contexts``: a fresh websocket context, with its own consumer, per call."""

    def __call__(self, token: str = "test") -> Awaitable[WsContext]: ...
