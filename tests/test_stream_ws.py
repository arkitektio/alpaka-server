"""The websocket at ``/kammer/stream/`` streams replies into rooms without a
GraphQL mutation per token (``kammer.consumers.MessageStreamConsumer``)."""

import asyncio

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator

from authentikate.models import Organization
from kammer import consumers
from kammer import models as kammer_models
from tests.test_streaming import FINISH, START, history_count, load_message, subscribe

APP = consumers.MessageStreamConsumer.as_asgi()


@sync_to_async
def make_room():
    org = Organization.objects.get(slug="static_org")
    return kammer_models.Room.objects.for_write().create(title="ws", organization=org)


async def connect(path="/kammer/stream/", token="test"):
    """A connected, authenticated socket (auth frame unless the token is in the URL)."""
    communicator = WebsocketCommunicator(APP, path)
    connected, _ = await communicator.connect()
    assert connected
    if token is not None and "token=" not in path:
        await communicator.send_json_to({"type": "auth", "token": token})
    if token is not None:
        assert (await communicator.receive_json_from())["type"] == "authenticated"
    return communicator


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_frames_before_auth_are_refused(authenticated_context):
    communicator = await connect(token=None)
    await communicator.send_json_to({"type": "start", "room": "1", "agent_id": "x"})
    assert (await communicator.receive_json_from())["type"] == "error"
    assert (await communicator.receive_output())["code"] == consumers.CLOSE_UNAUTHENTICATED

    communicator = WebsocketCommunicator(APP, "/kammer/stream/")
    await communicator.connect()
    await communicator.send_json_to({"type": "auth", "token": "not-a-token"})
    assert (await communicator.receive_json_from())["type"] == "error"
    assert (await communicator.receive_output())["code"] == consumers.CLOSE_UNAUTHENTICATED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_query_string_token_authenticates(authenticated_context):
    communicator = await connect(path="/kammer/stream/?token=test")
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_start_append_finish_over_socket(authenticated_context, monkeypatch):
    monkeypatch.setattr(consumers, "FLUSH_INTERVAL_SECONDS", 0.02)
    room = await make_room()
    communicator = await connect()

    await communicator.send_json_to({"type": "start", "room": str(room.id), "agent_id": "writer"})
    started = await communicator.receive_json_from()
    assert started["type"] == "started"
    message_id = started["message"]

    for delta in ["Hel", "lo", ", ", "world"]:
        await communicator.send_json_to({"type": "append", "message": message_id, "delta": delta})
    await asyncio.sleep(0.1)
    # Coalesced deltas land in the database before finish.
    row = await load_message(message_id)
    assert row.text == "Hello, world" and row.is_streaming is True

    await communicator.send_json_to({"type": "append", "message": message_id, "delta": "!"})
    await communicator.send_json_to({"type": "finish", "message": message_id})
    finished = await communicator.receive_json_from()
    assert finished == {"type": "finished", "message": message_id, "text": "Hello, world!"}

    row = await load_message(message_id)
    assert row.text == "Hello, world!" and row.is_streaming is False
    assert await history_count(message_id) == 2  # start + finish; appends leave no history
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_large_buffer_flushes_immediately_and_finish_text_overrides(authenticated_context):
    room = await make_room()
    communicator = await connect()
    await communicator.send_json_to({"type": "start", "room": str(room.id), "agent_id": "writer"})
    message_id = (await communicator.receive_json_from())["message"]

    await communicator.send_json_to({"type": "append", "message": message_id, "delta": "x" * consumers.MAX_BUFFER_CHARS})
    await communicator.send_json_to({"type": "finish", "message": message_id, "text": "final"})
    assert (await communicator.receive_json_from())["text"] == "final"
    assert (await load_message(message_id)).text == "final"
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_disconnect_finishes_open_message(authenticated_context, monkeypatch):
    monkeypatch.setattr(consumers, "FLUSH_INTERVAL_SECONDS", 5)
    room = await make_room()
    communicator = await connect()
    await communicator.send_json_to({"type": "start", "room": str(room.id), "agent_id": "writer"})
    message_id = (await communicator.receive_json_from())["message"]
    await communicator.send_json_to({"type": "append", "message": message_id, "delta": "partial"})
    await asyncio.sleep(0.05)

    await communicator.disconnect()

    row = await load_message(message_id)
    assert row.text == "partial" and row.is_streaming is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_socket_can_continue_a_message_started_over_graphql_but_not_someone_elses(aexecute, authenticated_context):
    room = await make_room()
    started = await aexecute(START, {"input": {"room": str(room.id), "agentId": "writer"}})
    message_id = int(started.data["startMessage"]["id"])

    mine = await connect(token="test")
    await mine.send_json_to({"type": "append", "message": message_id, "delta": "via socket"})
    await mine.send_json_to({"type": "finish", "message": message_id})
    assert (await mine.receive_json_from())["text"] == "via socket"
    await mine.disconnect()

    started = await aexecute(START, {"input": {"room": str(room.id), "agentId": "writer"}})
    other_id = int(started.data["startMessage"]["id"])
    theirs = await connect(token="test2")  # same organization, different user
    await theirs.send_json_to({"type": "append", "message": other_id, "delta": "hijack"})
    error = await theirs.receive_json_from()
    assert error["type"] == "error" and "Only the agent" in error["detail"]
    await theirs.disconnect()
    assert (await load_message(other_id)).text == ""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_subscribers_see_socket_streamed_updates(ws_contexts, monkeypatch):
    monkeypatch.setattr(consumers, "FLUSH_INTERVAL_SECONDS", 0.02)
    room = await make_room()
    listener = await subscribe(await ws_contexts(), room, "listener")

    communicator = await connect()
    await communicator.send_json_to({"type": "start", "room": str(room.id), "agent_id": "writer"})
    message_id = (await communicator.receive_json_from())["message"]
    event = await listener.next()
    assert event["kind"] == "MESSAGE_CREATED" and event["message"]["id"] == str(message_id)

    for delta in ["a", "b", "c"]:
        await communicator.send_json_to({"type": "append", "message": message_id, "delta": delta})
    event = await listener.next()
    assert event["kind"] == "MESSAGE_UPDATED"
    assert event["message"]["text"] in ("a", "ab", "abc")

    await communicator.send_json_to({"type": "finish", "message": message_id})
    await communicator.receive_json_from()
    kinds = [event["kind"]]
    while kinds[-1] != "MESSAGE_FINISHED":
        event = await listener.next()
        kinds.append(event["kind"])
    assert event["message"] == {"id": str(message_id), "text": "abc", "isStreaming": False}

    await communicator.disconnect()
    await listener.close()


# --- failure handling --------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_disconnect_flushes_but_does_not_finish_an_adopted_message(aexecute, authenticated_context, monkeypatch):
    """A message opened with ``startMessage`` belongs to the caller that opened it.

    The socket writes to it, and a drop flushes what arrived -- but closing it here
    would make the opener's own ``finishMessage`` fail as "already finished"."""
    monkeypatch.setattr(consumers, "FLUSH_INTERVAL_SECONDS", 5)
    room = await make_room()
    started = await aexecute(START, {"input": {"room": str(room.id), "agentId": "writer"}})
    message_id = int(started.data["startMessage"]["id"])

    communicator = await connect()
    await communicator.send_json_to({"type": "append", "message": message_id, "delta": "adopted"})
    await asyncio.sleep(0.05)
    await communicator.disconnect()

    row = await load_message(message_id)
    assert row.text == "adopted" and row.is_streaming is True

    finished = await aexecute(FINISH, {"input": {"message": str(message_id)}})
    assert finished.data, finished.errors
    assert finished.data["finishMessage"]["isStreaming"] is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_failing_write_keeps_the_delta_and_retries_it(authenticated_context, monkeypatch):
    """A delta whose write fails must survive to the next flush.

    ``append_delta`` is stubbed one layer *below* the code under test (the consumer's
    buffering), not the consumer itself -- a database blip is otherwise unstageable.
    """
    real_append = consumers.streaming.append_delta
    calls = {"n": 0}

    def flaky(message_id, delta):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database went away")
        return real_append(message_id, delta)

    monkeypatch.setattr(consumers.streaming, "append_delta", flaky)
    monkeypatch.setattr(consumers, "FLUSH_INTERVAL_SECONDS", 0.02)

    room = await make_room()
    communicator = await connect()
    await communicator.send_json_to({"type": "start", "room": str(room.id), "agent_id": "writer"})
    message_id = (await communicator.receive_json_from())["message"]

    await communicator.send_json_to({"type": "append", "message": message_id, "delta": "lost?"})
    error = await communicator.receive_json_from()
    assert error["type"] == "error" and "retried" in error["detail"]
    assert (await load_message(message_id)).text == ""

    # The retained delta rides along with the next one, in order.
    await communicator.send_json_to({"type": "append", "message": message_id, "delta": " no"})
    await communicator.send_json_to({"type": "finish", "message": message_id})
    assert (await communicator.receive_json_from())["text"] == "lost? no"
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_malformed_frames_are_errors_not_disconnects(authenticated_context):
    """A bad frame is answered, never dropped: the socket may be streaming other
    messages successfully at the time."""
    room = await make_room()
    communicator = await connect()

    for frame in (
        {"type": "start"},                                       # KeyError: room
        {"type": "append", "message": {}, "delta": "x"},         # TypeError: int({})
        {"type": "append", "message": "abc", "delta": "x"},      # ValueError: int("abc")
        {"type": "finish"},                                      # KeyError: message
        {"type": "wat"},                                         # unknown type
        ["not", "an", "object"],                                 # not a mapping at all
    ):
        await communicator.send_json_to(frame)
        assert (await communicator.receive_json_from())["type"] == "error"

    # The same socket still works.
    await communicator.send_json_to({"type": "start", "room": str(room.id), "agent_id": "writer"})
    message_id = (await communicator.receive_json_from())["message"]
    await communicator.send_json_to({"type": "append", "message": message_id, "delta": "fine"})
    await communicator.send_json_to({"type": "finish", "message": message_id})
    assert (await communicator.receive_json_from())["text"] == "fine"
    await communicator.disconnect()
