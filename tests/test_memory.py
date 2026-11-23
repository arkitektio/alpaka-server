"""A person's memories are reached only through a task they assigned, and only in its organization.

Every request here goes through the real auth path: the static token authenticates the app
(user "1", client "static"), and a task token signed with tests/fixtures/provenance_key.json
names the human who assigned the task (``rcb``) and the organization it runs in (``org``).
"""

import pytest
from authentikate.models import Membership, Organization, User
from kante.context import HttpContext
from strawberry.types.execution import ExecutionResult

from memory import models
from tests.support import BackendStack, request_context, task_token

#: The organizations the static tokens act in, as authentikate names them.
ORG = "static_issuer#static_org"
OTHER = "static_issuer#other_org"

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


async def run(
    query: str, variables: dict | None = None, ctx: HttpContext | None = None
) -> ExecutionResult:
    from alpaka_server.schema import schema

    return await schema.execute(
        query, variable_values=variables or {}, context_value=ctx or request_context()
    )


def remembered(name: str, content: str = "Exports as OME-TIFF, never PNG.") -> dict:
    return {
        "input": {
            "name": name,
            "description": "How they want images exported",
            "content": content,
            "kind": "FEEDBACK",
        }
    }


def _human(sub: str, organization: str) -> User:
    user, _ = User.objects.get_or_create(
        sub=sub, iss="static_issuer", defaults={"username": f"human-{sub}"}
    )
    Membership.objects.get_or_create(
        user=user,
        organization=Organization.objects.get_or_create(identifier=organization)[0],
    )
    return user


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_task_remembers_for_the_human_who_assigned_it_not_for_the_app(
    backend_stack: BackendStack,
) -> None:
    from asgiref.sync import sync_to_async

    await sync_to_async(_human)("ada", ORG)
    result = await run(
        REMEMBER, remembered("exports"), request_context(task=task_token("ada", ORG))
    )
    assert result.errors is None, result.errors
    assert result.data is not None
    assert result.data["remember"]["kind"] == "FEEDBACK"

    owner = await sync_to_async(
        lambda: (
            models.Memory.all_objects.select_related("user")
            .get(name="exports")
            .user.sub
        )
    )()
    assert owner == "ada"

    # Another assigner's task, the same app: their memories, not Ada's.
    result = await run(MEMORIES, {}, request_context(task=task_token("grace", ORG)))
    assert result.errors is None, result.errors
    assert result.data is not None
    assert result.data["memories"] == []

    result = await run(ASSIGNER, {}, request_context(task=task_token("ada", ORG)))
    assert result.data is not None
    assert result.data["assigner"]["sub"] == "ada"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_apps_own_login_reaches_no_memories(
    backend_stack: BackendStack,
) -> None:
    for document, variables in (
        (REMEMBER, remembered("exports")),
        (MEMORIES, {}),
        (ASSIGNER, {}),
    ):
        result = await run(document, variables, request_context())
        assert result.errors and "only from a task" in result.errors[0].message, (
            result.errors
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_task_of_another_organization_is_refused(
    backend_stack: BackendStack,
) -> None:
    # The app acts in static_org; the task runs in other_org.
    result = await run(MEMORIES, {}, request_context(task=task_token("ada", OTHER)))
    assert result.errors and "another organization" in result.errors[0].message, (
        result.errors
    )

    # A token from a rekuest that names no organization is refused too.
    result = await run(MEMORIES, {}, request_context(task=task_token("ada", None)))
    assert result.errors and "another organization" in result.errors[0].message, (
        result.errors
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_remembering_a_name_again_replaces_it_and_forgetting_deletes_it(
    backend_stack: BackendStack,
) -> None:
    ada = request_context(task=task_token("ada", ORG))
    await run(REMEMBER, remembered("exports"), ada)
    await run(
        REMEMBER,
        remembered("exports", "Exports as Zarr now."),
        request_context(task=task_token("ada", ORG)),
    )

    result = await run(
        MEMORIES, {"search": "zarr"}, request_context(task=task_token("ada", ORG))
    )
    assert result.errors is None, result.errors
    assert result.data is not None
    assert [m["name"] for m in result.data["memories"]] == ["exports"]

    result = await run(
        FORGET, {"name": "exports"}, request_context(task=task_token("ada", ORG))
    )
    assert result.data is not None
    assert result.data["forget"] is True
    result = await run(
        FORGET, {"name": "exports"}, request_context(task=task_token("ada", ORG))
    )
    assert result.data is not None
    assert result.data["forget"] is False
