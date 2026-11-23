"""A guest of the organization, granted a collaboration and nothing else: what they read, and where they may post.

Their token lists their collaborations by key (`collabs`: lok's key, one across the hub), with the
roles they hold in each; the guest token is minted per test (conftest `guest`). A full member
("test") puts rooms and messages in a collaboration under a fresh key (`addManyToCollaboration`,
which makes alpaka's row of it); what is part of a room (its agents and messages) is in it with the
room, and the structures its messages were posted about come along.
"""

import uuid

import httpx
import pytest
from arkitekt_service.collaborations.models import Collaboration, CollaborationItem
from asgiref.sync import sync_to_async
from authentikate.models import Client, Organization, User
from channels.testing import WebsocketCommunicator
from django.core.asgi import get_asgi_application
from kante.context import HttpContext
from strawberry.types import ExecutionResult

from alpaka_server.schema import schema
from kammer import consumers
from kammer import models as kammer_models
from llm import models as llm_models
from tests.support import GuestFactory, request_context
from vector import models as vector_models

ROOM = "query ($id: ID!) { room(id: $id) { id title messages { id text agent { name } } agents { name } } }"
ROOMS = "{ rooms { id } }"
MESSAGES = "{ messages { id } }"
MESSAGE = "query ($id: ID!) { message(id: $id) { id text agent { name } attachedStructures { identifier object } } }"
SEND = "mutation ($input: SendMessageInput!) { send(input: $input) { id room { id } } }"


async def _run(ctx: HttpContext, query: str, **variables: object) -> ExecutionResult:
    return await schema.execute(
        query, context_value=ctx, variable_values=variables or None
    )


def _refused(result: ExecutionResult, reason: str) -> None:
    assert result.errors, "it was let through"
    assert result.errors[0].extensions.get("reason") == reason, result.errors


@sync_to_async
def _room(
    title: str, *texts: str
) -> tuple[kammer_models.Room, list[kammer_models.Message]]:
    """A room of the organization, with one agent posting ``texts`` into it."""
    org = Organization.objects.get(identifier="static_issuer#static_org")
    user = User.objects.get(sub="1", iss="static_issuer")
    room = kammer_models.Room.objects.for_write().create(
        title=title, organization=org, creator=user
    )
    agent = kammer_models.Agent.objects.for_write().create(
        room=room,
        client=Client.objects.get(client_id="oinsoins"),
        user=user,
        name=f"{title} agent",
    )
    return room, [
        kammer_models.Message.objects.for_write().create(
            room=room, agent=agent, text=text
        )
        for text in texts
    ]


ADD_MANY = "mutation ($input: AddManyToCollaborationInput!) { addManyToCollaboration(input: $input) { key name } }"
IDENTIFIERS = {
    kammer_models.Room: "@alpaka/room",
    kammer_models.Message: "@alpaka/message",
}


def _put_in(
    key: str, *objects: kammer_models.Room | kammer_models.Message
) -> dict[str, object]:
    """The ``addManyToCollaboration`` input putting ``objects`` in the collaboration ``key``."""
    return {
        "collaboration": key,
        "name": "Shared",
        "objects": [
            {"identifier": IDENTIFIERS[type(obj)], "object": str(obj.pk)}
            for obj in objects
        ],
    }


async def _collaboration(*objects: kammer_models.Room | kammer_models.Message) -> str:
    """A collaboration of the organization holding ``objects``, as a full member puts them in:
    under a fresh key, as lok hands one out, in one ``addManyToCollaboration``. Its key."""
    key = str(uuid.uuid4())
    added = await _run(request_context("test"), ADD_MANY, input=_put_in(key, *objects))
    assert not added.errors, added.errors
    assert added.data is not None
    assert added.data["addManyToCollaboration"] == {"key": key, "name": "Shared"}
    assert await Collaboration.objects.filter(
        key=key, organization__identifier="static_issuer#static_org"
    ).aexists()
    return key


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_guest_reads_the_room_in_their_collaboration_and_nothing_else(
    authenticated_context: HttpContext, guest: GuestFactory
) -> None:
    shared, (hello, _) = await _room("Shared", "hello", "world")
    other, (secret,) = await _room("Other", "a secret")
    ctx = guest({await _collaboration(shared): []})

    listed = await _run(ctx, ROOMS)
    assert not listed.errors, listed.errors
    assert listed.data is not None
    assert [room["id"] for room in listed.data["rooms"]] == [str(shared.id)]
    read = await _run(ctx, ROOM, id=str(shared.id))
    assert not read.errors, read.errors
    assert read.data is not None
    assert sorted(m["text"] for m in read.data["room"]["messages"]) == [
        "hello",
        "world",
    ]
    assert read.data is not None
    assert {m["agent"]["name"] for m in read.data["room"]["messages"]} == {
        "Shared agent"
    }
    assert read.data is not None
    assert read.data["room"]["agents"] == [{"name": "Shared agent"}]

    messages = await _run(ctx, MESSAGES)
    assert not messages.errors, messages.errors
    assert messages.data is not None
    assert str(secret.id) not in {m["id"] for m in messages.data["messages"]}
    assert messages.data is not None
    assert len(messages.data["messages"]) == 2
    assert (await _run(ctx, ROOM, id=str(other.id))).errors
    assert (await _run(ctx, MESSAGE, id=str(secret.id))).errors
    assert (await _run(ctx, MESSAGE, id=str(hello.id))).data["message"][
        "text"
    ] == "hello"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_message_is_shared_with_its_room_not_alone(
    authenticated_context: HttpContext, guest: GuestFactory
) -> None:
    room, (message,) = await _room("Room", "only this")
    # Alone, its room would be unreadable where it points at it: the room is put in instead.
    key = str(uuid.uuid4())
    alone = await _run(request_context("test"), ADD_MANY, input=_put_in(key, message))
    assert alone.errors, "a message went in without its room"
    assert not await CollaborationItem.objects.aexists()
    assert not await Collaboration.objects.filter(key=key).aexists(), (
        "all or none: not even the collaboration's row"
    )

    ctx = guest(
        {await _collaboration(room, message): []}
    )  # with its room, it is in already
    read = await _run(ctx, MESSAGE, id=str(message.id))
    assert not read.errors, read.errors
    assert read.data is not None
    assert read.data["message"]["agent"]["name"] == "Room agent"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_who_made_and_posts_in_a_shared_room_comes_with_it(
    authenticated_context: HttpContext, guest: GuestFactory
) -> None:
    room, _ = await _room("Room", "hi")
    ctx = guest({await _collaboration(room): []})

    read = await _run(
        ctx,
        "query ($id: ID!) { room(id: $id) { creator { sub activeOrganization { identifier } } organization { identifier } agents { user { sub } client { clientId } } } }",
        id=str(room.id),
    )
    assert not read.errors, read.errors
    assert read.data is not None
    assert read.data["room"] == {
        # Who is at work where is theirs, not the room's.
        "creator": {"sub": "1", "activeOrganization": None},
        "organization": {"identifier": "static_issuer#static_org"},
        "agents": [{"user": {"sub": "1"}, "client": {"clientId": "oinsoins"}}],
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_what_a_message_was_posted_about_comes_along_when_it_is_posted_later(
    authenticated_context: HttpContext, guest: GuestFactory
) -> None:
    room, _ = await _room("Room")
    ctx = guest({await _collaboration(room): []})

    posted = await _run(
        request_context("test"),
        SEND,
        input={
            "room": str(room.id),
            "agentId": "member",
            "text": "look",
            "attachStructures": [{"identifier": "@mikro/image", "object": 7}],
        },
    )
    assert not posted.errors, posted.errors

    assert posted.data is not None
    read = await _run(ctx, MESSAGE, id=posted.data["send"]["id"])
    assert not read.errors, read.errors
    assert read.data is not None
    assert read.data["message"]["attachedStructures"] == [
        {"identifier": "@mikro/image", "object": 7}
    ]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_no_provider_model_or_collection_is_shown_to_a_guest_or_put_in_a_collaboration(
    authenticated_context: HttpContext, guest: GuestFactory
) -> None:
    room, _ = await _room("Room", "hi")

    @sync_to_async
    def seed() -> llm_models.Provider:
        org = Organization.objects.get(identifier="static_issuer#static_org")
        provider = llm_models.Provider.objects.for_write().create(
            name="Secret provider", organization=org, api_key="sk-do-not-leak"
        )
        model = llm_models.LLMModel.objects.for_write().create(
            provider=provider,
            model_id="secret-model",
            label="Secret",
            features=["embedding"],
        )
        vector_models.ChromaCollection.objects.for_write().create(
            name="secret-docs", embedder=model, organization=org
        )
        return provider

    provider = await seed()
    key = await _collaboration(room)
    ctx = guest({key: ["alpaka_editor"]})

    for field in ("providers", "llmModels", "chromaCollections"):
        listed = await _run(ctx, f"{{ {field} {{ id }} }}")
        assert not listed.errors, listed.errors
        assert listed.data is not None
        assert listed.data[field] == []
    assert (
        await _run(
            ctx, "query ($id: ID!) { provider(id: $id) { id } }", id=str(provider.id)
        )
    ).errors
    # Root fields handing out values computed from many rows are closed to guests.
    _refused(await _run(ctx, "{ roomStats { count } }"), "COLLABORATION_DOES_NOT_REACH")

    put = await _run(
        request_context("test"),
        "mutation ($input: CollaborationObjectInput!) { addToCollaboration(input: $input) { id } }",
        input={
            "collaboration": key,
            "identifier": "@alpaka/provider",
            "object": str(provider.id),
        },
    )
    assert put.errors and "never put in a collaboration" in put.errors[0].message, (
        put.errors
    )
    assert (
        await CollaborationItem.objects.filter(collaboration__key=key).acount() == 1
    )  # the room alone


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_full_member_shares_a_room_over_graphql(
    authenticated_context: HttpContext, guest: GuestFactory
) -> None:
    room, _ = await _room("Room", "hi")
    member = request_context("test")
    key = str(uuid.uuid4())  # lok's: nothing of it is here until something is put in
    put = await _run(
        member,
        "mutation ($input: CollaborationObjectInput!) { addToCollaboration(input: $input) { key name items { identifier } } }",
        input={
            "collaboration": key,
            "name": "With a guest",
            "identifier": "@alpaka/room",
            "object": str(room.id),
        },
    )
    assert not put.errors, put.errors
    assert put.data is not None
    assert put.data["addToCollaboration"] == {
        "key": key,
        "name": "With a guest",
        "items": [{"identifier": "@alpaka/room"}],
    }
    listed = await _run(
        member,
        "query ($key: ID!) { collaboration(key: $key) { key itemCount(brought: false) } }",
        key=key,
    )
    assert not listed.errors, listed.errors
    assert listed.data == {"collaboration": {"key": key, "itemCount": 1}}
    await _collaboration()  # another, not granted

    ctx = guest({key: []})
    assert [r["id"] for r in (await _run(ctx, ROOMS)).data["rooms"]] == [str(room.id)]
    granted = await _run(ctx, "{ collaborations { key name } }")
    assert not granted.errors, granted.errors
    assert granted.data == {"collaborations": [{"key": key, "name": "With a guest"}]}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_editor_in_the_collaboration_posts_there_and_only_there(
    authenticated_context: HttpContext, guest: GuestFactory
) -> None:
    room, _ = await _room("Room", "hi")
    other, _ = await _room("Other", "private")
    ctx = guest({await _collaboration(room): ["alpaka_editor"]})

    posted = await _run(
        ctx,
        SEND,
        input={"room": str(room.id), "agentId": "guest", "text": "hello from outside"},
    )
    assert not posted.errors, posted.errors
    read = await _run(ctx, ROOM, id=str(room.id))
    assert read.data is not None
    assert "hello from outside" in {
        m["text"] for m in read.data["room"]["messages"]
    }  # part of the room, so in the collaboration

    _refused(
        await _run(
            ctx,
            SEND,
            input={"room": str(other.id), "agentId": "guest", "text": "let me in"},
        ),
        "SHARE_INSUFFICIENT",
    )
    assert await kammer_models.Message.all_objects.filter(room=other).acount() == 1
    assert not await kammer_models.Agent.all_objects.filter(
        room=other, user__sub="20"
    ).aexists()  # its agent was taken back out


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_viewer_posts_nothing_and_no_guest_does_anything_else(
    authenticated_context: HttpContext, guest: GuestFactory
) -> None:
    room, _ = await _room("Room", "hi")
    key = await _collaboration(room)
    editor = guest({key: ["alpaka_editor"]})

    _refused(
        await _run(
            guest({key: []}),
            SEND,
            input={"room": str(room.id), "agentId": "guest", "text": "hi"},
        ),
        "INSUFFICIENT_ROLE",
    )
    _refused(
        await _run(
            editor,
            "mutation ($input: DeleteRoomInput!) { deleteRoom(input: $input) }",
            input={"id": str(room.id)},
        ),
        "SCOPED_READ_ONLY",
    )
    _refused(
        await _run(
            editor,
            "mutation ($input: StartMessageInput!) { startMessage(input: $input) { id } }",
            input={"room": str(room.id), "agentId": "guest"},
        ),
        "SCOPED_READ_ONLY",
    )
    _refused(
        await _run(editor, ADD_MANY, input=_put_in(str(uuid.uuid4()), room)),
        "SCOPED_READ_ONLY",
    )
    _refused(
        await _run(
            editor,
            "mutation ($input: ShareWorkflowInput!) { shareWorkflow(input: $input) { dryRun } }",
            input={"collaboration": key, "rootTask": "any", "dryRun": True},
        ),
        "SCOPED_READ_ONLY",
    )
    assert await kammer_models.Message.all_objects.filter(room=room).acount() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_guest_calls_no_model_and_streams_nothing_outside_graphql(
    authenticated_context: HttpContext, guest: GuestFactory
) -> None:
    room, _ = await _room("Room")
    guest({await _collaboration(room): ["alpaka_editor"]})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=get_asgi_application()),
        base_url="http://testserver",
    ) as http:
        listed = await http.get(
            "/llm/v1/models", headers={"Authorization": "Bearer guest"}
        )
    assert listed.status_code == 401, listed.text
    assert "guest" in listed.json()["error"]["message"]

    socket = WebsocketCommunicator(
        consumers.MessageStreamConsumer.as_asgi(), "/kammer/stream/"
    )
    connected, _ = await socket.connect()
    assert connected
    await socket.send_json_to({"type": "auth", "token": "guest"})
    assert (await socket.receive_json_from())["type"] == "error"
    assert (await socket.receive_output())["code"] == consumers.CLOSE_UNAUTHENTICATED


def _type_line(sdl: str, name: str) -> str:
    return next(line for line in sdl.splitlines() if line.startswith(f"type {name} "))


def test_the_schema_says_what_each_type_is_and_where_a_guest_may_post() -> None:
    sdl = str(schema)
    assert '@identified(by: "@alpaka/room")' in _type_line(sdl, "Room")
    send = next(
        line.strip() for line in sdl.splitlines() if line.strip().startswith("send(")
    )
    assert send.endswith(
        '@auth(required_scopes: ["alpaka_chat"], any_role_of: ["alpaka_editor"], allow_scoped: true)'
    ), send
