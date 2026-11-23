"""Sharing a workflow: what a root task created in alpaka, put in a collaboration as it is now.

A workflow is a root task (koherent's ``Task.root_task_id``). Its tasks call alpaka with a task
token rekuest signed (``tests/support.task_token``, ``rtk`` naming the workflow), and koherent
records the task on the CREATE row of what each request made: a room's history, a message's. A
message is part of its room: it comes along with a room the workflow opened, and one posted into an
older room that is not shared is left out. Providers, their models and the collections they embed
are never put in a collaboration, whatever made them.

The collaboration is lok's, named by a key: a full member shares under a fresh one, and a guest's
token names the same key.
"""

import uuid
from dataclasses import dataclass

import pytest
from arkitekt_service.collaborations.models import Collaboration, CollaborationItem
from authentikate.models import Organization
from kante.context import HttpContext
from strawberry.types import ExecutionResult

from alpaka_server.schema import schema
from llm import models as llm_models
from tests.support import GuestFactory, request_context, task_token
from vector import models as vector_models

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

ORG = "static_issuer#static_org"

SHARE = """
mutation ($input: ShareWorkflowInput!) {
  shareWorkflow(input: $input) {
    collaboration
    dryRun
    added { identifier object }
    covered
    skipped { identifier object wholeIdentifier whole }
    unknown
  }
}
"""
ADD = "mutation ($input: CollaborationObjectInput!) { addToCollaboration(input: $input) { key } }"
CREATE_ROOM = "mutation ($input: CreateRoomInput!) { createRoom(input: $input) { id } }"
SEND = "mutation ($input: SendMessageInput!) { send(input: $input) { id } }"
LISTS = """
query ($rooms: RoomFilter, $messages: MessageFilter) {
  rooms(filters: $rooms) { id }
  messages(filters: $messages) { id }
}
"""
NEVER_SHARED = """
query ($providers: ProviderFilter, $models: LLMModelFilter, $collections: ChromaCollectionFilter) {
  providers(filters: $providers) { id }
  llmModels(filters: $models) { id }
  chromaCollections(filters: $collections) { id }
}
"""


async def _run(ctx: HttpContext, query: str, **variables: object) -> ExecutionResult:
    return await schema.execute(
        query, context_value=ctx, variable_values=variables or None
    )


async def _as(task: str | None, query: str, **variables: object) -> dict:
    """Run ``query`` as the full member, under the task token ``task`` when given, and hand back its data."""
    result = await _run(request_context("test", task=task), query, **variables)
    assert not result.errors, result.errors
    assert result.data is not None
    return result.data


async def _room(title: str, task: str | None = None) -> str:
    return (await _as(task, CREATE_ROOM, input={"title": title}))["createRoom"]["id"]


async def _send(room: str, text: str, task: str | None = None) -> str:
    sent = await _as(
        task, SEND, input={"room": room, "agentId": "workflow", "text": text}
    )
    return sent["send"]["id"]


@dataclass(frozen=True)
class Workflow:
    """A workflow's root task and what it made, beside what it did not."""

    root: str
    #: Opened by the workflow, and the message it posted there.
    room: str
    message: str
    #: Opened before the workflow, and not shared; the workflow only posted into it.
    older: str
    message_in_older: str
    #: Opened in the organization, but not by the workflow.
    unrelated: str
    #: Made while the workflow ran: never shared.
    provider: str


async def _workflow() -> Workflow:
    """A workflow (two tasks under one root) that opened a room and posted into it and into an
    older room; plus what it did not make, and a provider, a model and a collection."""
    older = await _room("Older")
    unrelated = await _room("Unrelated")
    root = f"root-{uuid.uuid4().hex}"
    first = task_token("1", ORG, tsk=f"task-{uuid.uuid4().hex}", rtk=root)
    second = task_token("1", ORG, tsk=f"task-{uuid.uuid4().hex}", rtk=root)

    room = await _room("Made", first)
    message = await _send(room, "in the workflow's room", first)
    message_in_older = await _send(older, "into the older room", second)
    organization = await Organization.objects.aget(identifier=ORG)
    provider = await llm_models.Provider.objects.for_write().acreate(
        name="Workflow's provider", organization=organization, api_key="sk-never-shared"
    )
    model = await llm_models.LLMModel.objects.for_write().acreate(
        provider=provider, model_id="embedder", label="Embedder", features=["embedding"]
    )
    await vector_models.ChromaCollection.objects.for_write().acreate(
        name="workflow-docs", embedder=model, organization=organization
    )
    return Workflow(
        root=root,
        room=room,
        message=message,
        older=older,
        message_in_older=message_in_older,
        unrelated=unrelated,
        provider=str(provider.pk),
    )


def _ids(data: dict, field: str) -> set[str]:
    return {row["id"] for row in data[field]}


def _report(workflow: Workflow, key: str, *, dry_run: bool) -> dict:
    """What sharing ``workflow`` reports: its room put in, its message there covered by it, the
    message in the older room left out, and nothing unknown."""
    return {
        "collaboration": key,
        "dryRun": dry_run,
        "added": [{"identifier": "@alpaka/room", "object": workflow.room}],
        "covered": 1,
        "skipped": [
            {
                "identifier": "@alpaka/message",
                "object": workflow.message_in_older,
                "wholeIdentifier": "@alpaka/room",
                "whole": workflow.older,
            }
        ],
        "unknown": [],
    }


async def test_a_dry_run_says_what_sharing_a_workflow_puts_in_and_writes_nothing(
    authenticated_context: HttpContext,
) -> None:
    workflow = await _workflow()
    key = str(uuid.uuid4())

    tried = await _as(
        None,
        SHARE,
        input={"collaboration": key, "rootTask": workflow.root, "dryRun": True},
    )

    assert tried["shareWorkflow"] == _report(workflow, key, dry_run=True)
    assert not await Collaboration.objects.filter(key=key).aexists(), (
        "a dry run makes no row of the collaboration here"
    )
    assert await CollaborationItem.objects.acount() == 0


async def test_sharing_a_workflow_puts_in_what_it_made_and_a_guest_sees_exactly_that(
    authenticated_context: HttpContext, guest: GuestFactory
) -> None:
    workflow = await _workflow()
    key = str(uuid.uuid4())
    before = await _run(guest({key: []}), LISTS)
    assert not before.errors, before.errors
    assert before.data == {"rooms": [], "messages": []}, (
        "a key granted before anything is put in here holds nothing"
    )

    shared = await _as(
        None,
        SHARE,
        input={"collaboration": key, "rootTask": workflow.root, "name": "Pilot"},
    )

    assert shared["shareWorkflow"] == _report(workflow, key, dry_run=False)
    assert (await Collaboration.objects.aget(key=key)).name == "Pilot"
    seen = await _run(guest({key: []}), LISTS)
    assert not seen.errors, seen.errors
    assert seen.data is not None
    assert _ids(seen.data, "rooms") == {workflow.room}
    assert _ids(seen.data, "messages") == {workflow.message}, (
        "the message with its room, and not the one in the older room"
    )
    never = await _run(guest({key: []}), NEVER_SHARED)
    assert not never.errors, never.errors
    assert never.data == {"providers": [], "llmModels": [], "chromaCollections": []}
    assert not await CollaborationItem.objects.filter(
        content_type__app_label__in=["llm", "vector"]
    ).aexists(), "no provider, model or collection went in"

    stranger = await _run(guest({str(uuid.uuid4()): []}), LISTS)
    assert not stranger.errors, stranger.errors
    assert stranger.data == {"rooms": [], "messages": []}, (
        "another key sees nothing of it"
    )


async def test_a_message_in_an_older_room_comes_along_once_that_room_is_shared(
    authenticated_context: HttpContext, guest: GuestFactory
) -> None:
    workflow = await _workflow()
    key = str(uuid.uuid4())
    await _as(None, SHARE, input={"collaboration": key, "rootTask": workflow.root})
    assert workflow.message_in_older not in _ids(
        (await _run(guest({key: []}), LISTS)).data or {}, "messages"
    ), "the workflow does not hand out a part of what it did not make"

    await _as(
        None,
        ADD,
        input={
            "collaboration": key,
            "identifier": "@alpaka/room",
            "object": workflow.older,
        },
    )
    again = await _as(
        None, SHARE, input={"collaboration": key, "rootTask": workflow.root}
    )

    assert again["shareWorkflow"]["skipped"] == []
    assert again["shareWorkflow"]["covered"] == 2, "both messages, with their rooms"
    seen = await _run(guest({key: []}), LISTS)
    assert seen.data is not None
    assert workflow.message_in_older in _ids(seen.data, "messages")
    assert _ids(seen.data, "rooms") == {workflow.room, workflow.older}


async def test_lists_filter_by_the_workflow_that_made_them_and_by_collaboration(
    authenticated_context: HttpContext,
) -> None:
    workflow = await _workflow()
    key = str(uuid.uuid4())
    under = {"createdUnder": workflow.root}

    made = await _as(None, LISTS, rooms=under, messages=under)

    assert _ids(made, "rooms") == {workflow.room}
    assert _ids(made, "messages") == {workflow.message, workflow.message_in_older}
    never = await _as(
        None, NEVER_SHARED, providers=under, models=under, collections=under
    )
    assert never == {"providers": [], "llmModels": [], "chromaCollections": []}, (
        "never shared, so never listed as a workflow's"
    )
    assert _ids(await _as(None, NEVER_SHARED), "providers") == {workflow.provider}

    inside = {"inCollaboration": key}
    nothing_yet = await _as(None, LISTS, rooms=inside, messages=inside)
    assert nothing_yet == {"rooms": [], "messages": []}

    await _as(None, SHARE, input={"collaboration": key, "rootTask": workflow.root})
    shared = await _as(None, LISTS, rooms=inside, messages=inside)

    assert _ids(shared, "rooms") == {workflow.room}
    assert _ids(shared, "messages") == {workflow.message}, (
        "a part of what was put in is in it, live"
    )
    both = await _as(
        None,
        LISTS,
        rooms={"inCollaboration": key, "ids": [workflow.older]},
        messages={"createdUnder": workflow.root, "inCollaboration": key},
    )
    assert both["rooms"] == []
    assert _ids(both, "messages") == {workflow.message}


async def test_another_organization_shares_nothing_of_this_workflow(
    authenticated_context: HttpContext,
) -> None:
    workflow = await _workflow()

    tried = await _run(
        request_context("othertest"),
        SHARE,
        input={
            "collaboration": str(uuid.uuid4()),
            "rootTask": workflow.root,
            "dryRun": True,
        },
    )

    assert not tried.errors, tried.errors
    assert tried.data is not None
    assert tried.data["shareWorkflow"]["added"] == []
    assert tried.data["shareWorkflow"]["skipped"] == []


async def test_an_explicit_null_filters_nothing(
    authenticated_context: HttpContext,
) -> None:
    workflow = await _workflow()
    unset = {"inCollaboration": None, "createdUnder": None}

    listed = await _as(None, LISTS, rooms=unset, messages=unset)

    assert _ids(listed, "rooms") == {workflow.room, workflow.older, workflow.unrelated}
    assert _ids(listed, "messages") == {workflow.message, workflow.message_in_older}
