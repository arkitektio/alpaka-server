"""A person's memories are reached only through a task they assigned, and only in its organization.

Every request here goes through the real auth path: the static token authenticates the app
(user "1", client "static"), and a task token signed with tests/fixtures/provenance_key.json
names the human who assigned the task (``rcb``) and the organization it runs in (``org``).
"""

import datetime
import json
import pathlib
import uuid

import pytest
from authentikate.models import Membership, Organization, User
from joserfc import jwt
from joserfc.jwk import OKPKey
from kante.context import HttpContext, UniversalRequest
from strawberry.http.temporal_response import TemporalResponse
from strawberry.types.execution import ExecutionResult

from memory import models

#: The organizations the static tokens act in, as authentikate names them.
ORG = "static_issuer#static_org"
OTHER = "static_issuer#other_org"

KEY = OKPKey.import_key(json.loads((pathlib.Path(__file__).parent / "fixtures" / "provenance_key.json").read_text()))

REMEMBER = """
mutation ($input: MemoryInput!) {
  remember(input: $input) { id name description content kind }
}
"""
MEMORIES = """
query ($search: String) {
  memories(filters: {search: $search}) { name description kind }
}
"""
FORGET = "mutation ($name: String!) { forget(input: {name: $name}) }"
ASSIGNER = "{ assigner { sub } }"


def task_token(rcb: str, org: str | None, act_sub: str = "1") -> str:
    """A task token as rekuest signs it for the static test app, assigned by ``rcb``."""
    now = int(datetime.datetime.now().timestamp())
    claims = {
        "iss": "rekuest",
        "aud": ["alpaka"],
        "sub": act_sub,
        "act": {"sub": act_sub, "cid": "static", "iss": "static_issuer"},
        "iat": now,
        "exp": now + 300,
        "jti": uuid.uuid4().hex,
        "tsk": "2",
        "ptk": "1",
        "rtk": "1",
        "rcb": rcb,
        "ahs": "e3b0c44298fc1c14",
        "aha": "sha256-canonical-v1",
    }
    if org is not None:
        claims["org"] = org
    return jwt.encode({"alg": "Ed25519", "kid": "alpaka-test-provenance"}, claims, KEY, algorithms=["Ed25519"])


def context(bearer: str = "test", task: str | None = None) -> HttpContext:
    headers = {"Authorization": f"Bearer {bearer}"}
    if task is not None:
        headers["rekuest-task"] = task
    return HttpContext(request=UniversalRequest(_extensions={}), response=TemporalResponse(), headers=headers, type="http")


async def run(query: str, variables: dict | None = None, ctx: HttpContext | None = None) -> ExecutionResult:
    from alpaka_server.schema import schema

    return await schema.execute(query, variable_values=variables or {}, context_value=ctx or context())


def remembered(name: str, content: str = "Exports as OME-TIFF, never PNG.") -> dict:
    return {"input": {"name": name, "description": "How they want images exported", "content": content, "kind": "FEEDBACK"}}


def _human(sub: str, organization: str) -> User:
    user, _ = User.objects.get_or_create(sub=sub, iss="static_issuer", defaults={"username": f"human-{sub}"})
    Membership.objects.get_or_create(user=user, organization=Organization.objects.get_or_create(identifier=organization)[0])
    return user


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_task_remembers_for_the_human_who_assigned_it_not_for_the_app(backend_stack):
    from asgiref.sync import sync_to_async

    await sync_to_async(_human)("ada", ORG)
    result = await run(REMEMBER, remembered("exports"), context(task=task_token("ada", ORG)))
    assert result.errors is None, result.errors
    assert result.data["remember"]["kind"] == "FEEDBACK"

    owner = await sync_to_async(lambda: models.Memory.all_objects.select_related("user").get(name="exports").user.sub)()
    assert owner == "ada"

    # Another assigner's task, the same app: their memories, not Ada's.
    result = await run(MEMORIES, {}, context(task=task_token("grace", ORG)))
    assert result.errors is None, result.errors
    assert result.data["memories"] == []

    result = await run(ASSIGNER, {}, context(task=task_token("ada", ORG)))
    assert result.data["assigner"]["sub"] == "ada"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_apps_own_login_reaches_no_memories(backend_stack):
    for document, variables in ((REMEMBER, remembered("exports")), (MEMORIES, {}), (ASSIGNER, {})):
        result = await run(document, variables, context())
        assert result.errors and "only from a task" in result.errors[0].message, result.errors


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_task_of_another_organization_is_refused(backend_stack):
    # The app acts in static_org; the task runs in other_org.
    result = await run(MEMORIES, {}, context(task=task_token("ada", OTHER)))
    assert result.errors and "another organization" in result.errors[0].message, result.errors

    # A token from a rekuest that names no organization is refused too.
    result = await run(MEMORIES, {}, context(task=task_token("ada", None)))
    assert result.errors and "another organization" in result.errors[0].message, result.errors


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_remembering_a_name_again_replaces_it_and_forgetting_deletes_it(backend_stack):
    ada = context(task=task_token("ada", ORG))
    await run(REMEMBER, remembered("exports"), ada)
    await run(REMEMBER, remembered("exports", "Exports as Zarr now."), context(task=task_token("ada", ORG)))

    result = await run(MEMORIES, {"search": "zarr"}, context(task=task_token("ada", ORG)))
    assert result.errors is None, result.errors
    assert [m["name"] for m in result.data["memories"]] == ["exports"]

    result = await run(FORGET, {"name": "exports"}, context(task=task_token("ada", ORG)))
    assert result.data["forget"] is True
    result = await run(FORGET, {"name": "exports"}, context(task=task_token("ada", ORG)))
    assert result.data["forget"] is False
