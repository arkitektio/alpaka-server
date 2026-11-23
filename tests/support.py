"""The types the suite's fixtures hand to tests, and the requests they make as a client would."""

import datetime
import json
import pathlib
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, TypeAlias, TypedDict

from joserfc import jwt
from joserfc.jwk import OKPKey
from kante.context import HttpContext, UniversalRequest, WsContext
from strawberry.http.temporal_response import TemporalResponse
from strawberry.types import ExecutionResult

#: What rekuest signs task tokens with in the test settings (``AUTHENTIKATE["provenance"]``).
PROVENANCE_KEY = OKPKey.import_key(
    json.loads(
        (pathlib.Path(__file__).parent / "fixtures" / "provenance_key.json").read_text()
    )
)

#: ``guest({key: roles})``: a context presenting a guest's token granted those collaborations, by
#: their key (lok's), with the roles held in each (``[]``: view only).
GuestFactory: TypeAlias = Callable[[Mapping[str, list[str]]], HttpContext]


def task_token(
    rcb: str,
    org: str | None,
    act_sub: str = "1",
    *,
    tsk: str = "2",
    rtk: str = "1",
) -> str:
    """A task token as rekuest signs it for the static test app: task ``tsk`` of the workflow
    ``rtk`` (its root task), assigned by ``rcb``, in the organization ``org``."""
    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    claims: dict[str, object] = {
        "iss": "rekuest",
        "aud": ["alpaka"],
        "sub": act_sub,
        "act": {"sub": act_sub, "cid": "static", "iss": "static_issuer"},
        "iat": now,
        "exp": now + 300,
        "jti": uuid.uuid4().hex,
        "tsk": tsk,
        "ptk": rtk,
        "rtk": rtk,
        "rcb": rcb,
        "ahs": "e3b0c44298fc1c14",
        "aha": "sha256-canonical-v1",
    }
    if org is not None:
        claims["org"] = org
    return jwt.encode(
        {"alg": "Ed25519", "kid": "alpaka-test-provenance"},
        claims,
        PROVENANCE_KEY,
        algorithms=["Ed25519"],
    )


def request_context(bearer: str = "test", task: str | None = None) -> HttpContext:
    """A request presenting the static token ``bearer`` (and a task token), as a client sends it:
    nothing resolved yet."""
    headers = {"Authorization": f"Bearer {bearer}"}
    if task is not None:
        headers["rekuest-task"] = task
    return HttpContext(
        request=UniversalRequest(_extensions={}),
        response=TemporalResponse(),
        headers=headers,
        type="http",
    )


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
