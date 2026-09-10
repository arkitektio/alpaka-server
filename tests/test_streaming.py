"""Streaming a reply into a room from a client-side agent.

``startMessage`` opens a message with ``isStreaming: true``; ``appendMessage``
grows it with an atomic server-side concat; ``finishMessage`` closes it. The
``room`` subscription reports each step (plus JOIN/LEAVE). The server never
calls an LLM on behalf of a room; the client forwards the tokens it received."""

import asyncio
import contextlib

import pytest
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

from alpaka_server.schema import schema
from authentikate.models import Organization
from kammer import models as kammer_models
from kammer.channels import room_group
from kammer.streaming import append_delta as _append_delta

START = "mutation($input: StartMessageInput!) { startMessage(input: $input) { id text isStreaming } }"
APPEND = "mutation($input: AppendMessageInput!) { appendMessage(input: $input) { id text isStreaming } }"
FINISH = "mutation($input: FinishMessageInput!) { finishMessage(input: $input) { id text isStreaming attachedStructures { identifier object } } }"
ROOM = """
    subscription($room: ID!, $agentId: ID!, $filterOwn: Boolean) {
        room(room: $room, agentId: $agentId, filterOwn: $filterOwn) {
            kind
            message { id text isStreaming }
            join { name }
            leave { name }
        }
    }
"""


@sync_to_async
def make_room(slug="static_org"):
    org = Organization.objects.get(slug=slug)
    return kammer_models.Room.objects.for_write().create(title="stream", organization=org)


@sync_to_async
def load_message(message_id):
    return kammer_models.Message.all_objects.get(id=message_id)


@sync_to_async
def history_count(message_id):
    return kammer_models.Message.all_objects.get(id=message_id).provenance_entries.count()


async def start(aexecute, room, agent="writer", context=None, text=""):
    result = await aexecute(START, {"input": {"room": str(room.id), "agentId": agent, "text": text}}, context=context)
    assert result.data, result.errors
    return result.data["startMessage"]


# --- mutations ---------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_start_append_finish_flow(aexecute):
    room = await make_room()
    started = await start(aexecute, room)
    assert started["text"] == "" and started["isStreaming"] is True

    first = await aexecute(APPEND, {"input": {"message": started["id"], "delta": "Hel"}})
    assert first.data["appendMessage"]["text"] == "Hel", first.errors
    second = await aexecute(APPEND, {"input": {"message": started["id"], "delta": "lo"}})
    assert second.data["appendMessage"] == {"id": started["id"], "text": "Hello", "isStreaming": True}, second.errors

    finished = await aexecute(FINISH, {"input": {"message": started["id"]}})
    assert finished.data["finishMessage"]["text"] == "Hello", finished.errors
    assert finished.data["finishMessage"]["isStreaming"] is False

    row = await load_message(started["id"])
    assert row.text == "Hello" and row.is_streaming is False
    # Start and finish go through save(); appends leave no history row.
    assert await history_count(started["id"]) == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_finish_text_override_and_structures(aexecute):
    room = await make_room()
    started = await start(aexecute, room)
    await aexecute(APPEND, {"input": {"message": started["id"], "delta": "partial"}})

    finished = await aexecute(FINISH, {"input": {"message": started["id"], "text": "final", "attachStructures": [{"identifier": "@mikro/image", "object": 7}]}})
    assert finished.data, finished.errors
    assert finished.data["finishMessage"]["text"] == "final"
    assert finished.data["finishMessage"]["attachedStructures"] == [{"identifier": "@mikro/image", "object": 7}]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_append_is_atomic_under_concurrency(aexecute):
    """Fifty concurrent appends, each on its own connection, lose nothing."""
    room = await make_room()
    started = await start(aexecute, room)

    append = sync_to_async(_append_delta, thread_sensitive=False)
    await asyncio.gather(*[append(int(started["id"]), f"<{i}>") for i in range(50)])

    row = await load_message(started["id"])
    for i in range(50):
        assert row.text.count(f"<{i}>") == 1
    assert len(row.text) == sum(len(f"<{i}>") for i in range(50))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_finished_message_is_immutable(aexecute):
    room = await make_room()
    started = await start(aexecute, room, text="done")
    await aexecute(FINISH, {"input": {"message": started["id"]}})

    appended = await aexecute(APPEND, {"input": {"message": started["id"], "delta": "!"}})
    assert appended.errors and "finished" in appended.errors[0].message
    refinished = await aexecute(FINISH, {"input": {"message": started["id"], "text": "changed"}})
    assert refinished.errors
    assert (await load_message(started["id"])).text == "done"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_other_organization_and_other_user_are_refused(aexecute, other_org_context, same_org_other_user_context):
    room = await make_room()
    started = await start(aexecute, room, text="mine")

    for context in (other_org_context, same_org_other_user_context):
        appended = await aexecute(APPEND, {"input": {"message": started["id"], "delta": "!"}}, context=context)
        assert appended.errors
        finished = await aexecute(FINISH, {"input": {"message": started["id"]}}, context=context)
        assert finished.errors

    row = await load_message(started["id"])
    assert row.text == "mine" and row.is_streaming is True

    # Another organization cannot start a message in this room either.
    foreign = await aexecute(START, {"input": {"room": str(room.id), "agentId": "intruder"}}, context=other_org_context)
    assert foreign.errors


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_send_input_has_no_notify_and_validates_parent(aexecute, other_org_context):
    sdl = schema.as_str()
    assert "notify" not in sdl.split("input SendMessageInput")[1].split("}")[0]

    room = await make_room()
    other_room = await make_room("other_org")
    foreign_parent = await sync_to_async(kammer_models.Message.objects.for_write().create)(
        room=other_room,
        agent=await sync_to_async(kammer_models.Agent.objects.for_write().create)(room=other_room, user=other_org_context.request.user, client=other_org_context.request.client, name="x"),
        text="theirs",
    )
    result = await aexecute(
        "mutation($input: SendMessageInput!) { send(input: $input) { id } }",
        {"input": {"room": str(room.id), "agentId": "writer", "text": "reply", "parent": str(foreign_parent.id)}},
    )
    assert result.errors


# --- subscription ------------------------------------------------------------


class Subscriber:
    """Drives one subscription from a single task.

    The AuthentikateExtension sets and resets context variables around the
    operation, which must happen in the same task; iterating the generator
    from ad-hoc tasks per event breaks that. Cancelling the task closes the
    subscription the way a client disconnect would.
    """

    def __init__(self, ws_context, room, agent, filter_own=True):
        self.ws_context = ws_context
        self.variables = {"room": str(room.id), "agentId": agent, "filterOwn": filter_own}
        self.events: asyncio.Queue = asyncio.Queue()
        self.task = asyncio.create_task(self._run())

    async def _run(self):
        sub = await schema.subscribe(ROOM, variable_values=self.variables, context_value=self.ws_context)
        if hasattr(sub, "errors"):
            self.events.put_nowait(sub)
            return
        async for result in sub:
            self.events.put_nowait(result)

    async def next(self, timeout=5):
        result = await asyncio.wait_for(self.events.get(), timeout)
        assert not result.errors, result.errors
        return result.data["room"]

    async def close(self):
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.task


async def subscribe(ws_context, room, agent, filter_own=True):
    """Start a subscription and wait until it is registered with the room's group."""
    subscriber = Subscriber(ws_context, room, agent, filter_own)
    layer = get_channel_layer()
    for _ in range(500):
        if subscriber.task.done():
            subscriber.task.result()  # surfaces a failed subscribe
        if ws_context.consumer.channel_name in layer.groups.get(room_group(room.id), {}):
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("subscription never joined the room group")
    return subscriber


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_subscription_sees_created_updated_finished(aexecute, ws_contexts):
    room = await make_room()
    listener = await subscribe(await ws_contexts(), room, "listener")

    started = await start(aexecute, room, agent="writer")
    event = await listener.next()
    assert event["kind"] == "MESSAGE_CREATED"
    assert event["message"] == {"id": started["id"], "text": "", "isStreaming": True}

    await aexecute(APPEND, {"input": {"message": started["id"], "delta": "Hel"}})
    event = await listener.next()
    assert event["kind"] == "MESSAGE_UPDATED" and event["message"]["text"] == "Hel"

    await aexecute(APPEND, {"input": {"message": started["id"], "delta": "lo"}})
    event = await listener.next()
    assert event["kind"] == "MESSAGE_UPDATED" and event["message"]["text"] == "Hello"

    await aexecute(FINISH, {"input": {"message": started["id"]}})
    event = await listener.next()
    assert event["kind"] == "MESSAGE_FINISHED"
    assert event["message"] == {"id": started["id"], "text": "Hello", "isStreaming": False}

    await listener.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_subscription_filter_own(aexecute, ws_contexts):
    room = await make_room()
    # Same user, client and agent name as the mutations -> own events hidden.
    own = await subscribe(await ws_contexts(), room, "writer")
    started = await start(aexecute, room, agent="writer")
    await aexecute(APPEND, {"input": {"message": started["id"], "delta": "x"}})
    with pytest.raises(asyncio.TimeoutError):
        await own.next(timeout=0.5)
    await own.close()

    everything = await subscribe(await ws_contexts(), room, "writer", filter_own=False)
    await aexecute(APPEND, {"input": {"message": started["id"], "delta": "y"}})
    event = await everything.next()
    assert event["kind"] == "MESSAGE_UPDATED" and event["message"]["text"] == "xy"
    await everything.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_subscription_join_and_leave(ws_contexts):
    room = await make_room()
    first = await subscribe(await ws_contexts(), room, "first")

    second = await subscribe(await ws_contexts(), room, "second")
    event = await first.next()
    assert event["kind"] == "JOIN" and event["join"] == {"name": "second"}

    await second.close()
    event = await first.next()
    assert event["kind"] == "LEAVE" and event["leave"] == {"name": "second"}

    await first.close()
