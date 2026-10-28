"""A guest of the organization, granted a collaboration and nothing else: what they read, and where they may post.

Their token lists their collaborations by service instance (`collabs`, instance "1" in the test
settings), with the roles they hold in each; the guest token is minted per test. A full member
("test") puts rooms and messages in a collaboration; what is part of a room (its agents and
messages) is in it with the room, and the structures its messages were posted about come along.
"""

import httpx
import pytest
from asgiref.sync import sync_to_async
from authentikate import settings as authentikate_settings
from authentikate.models import Client, Organization, User
from channels.testing import WebsocketCommunicator
from django.core.asgi import get_asgi_application
from kante.context import HttpContext, UniversalRequest
from strawberry.http.temporal_response import TemporalResponse
from strawberry.types import ExecutionResult

from alpaka_server.schema import schema
from arkitekt_service.collaborations import items as collaboration_items
from arkitekt_service.collaborations.models import Collaboration, CollaborationItem
from kammer import consumers
from kammer import models as kammer_models
from llm import models as llm_models
from vector import models as vector_models

ROOM = "query ($id: ID!) { room(id: $id) { id title messages { id text agent { name } } agents { name } } }"
ROOMS = "{ rooms { id } }"
MESSAGES = "{ messages { id } }"
MESSAGE = "query ($id: ID!) { message(id: $id) { id text agent { name } attachedStructures { identifier object } } }"
SEND = "mutation ($input: SendMessageInput!) { send(input: $input) { id room { id } } }"


def _context(token: str) -> HttpContext:
    return HttpContext(request=UniversalRequest(_extensions={}), response=TemporalResponse(), headers={"Authorization": f"Bearer {token}"}, type="http")


@pytest.fixture
def guest(db, authenticated_context, settings):
    """``guest({collaboration: roles})``: a context presenting a guest's token granted those collaborations on instance "1"."""

    def mint(collaborations: dict[Collaboration, list[str]]) -> HttpContext:
        granted = {str(collaboration.pk): roles for collaboration, roles in collaborations.items()}
        settings.AUTHENTIKATE = {
            **settings.AUTHENTIKATE,
            "static_tokens": {**settings.AUTHENTIKATE["static_tokens"], "guest": {"sub": "20", "roles": [], "collabs": {"1": granted}, "scope": "openid alpaka_all"}},
        }
        authentikate_settings.cached_settings = None
        return _context("guest")

    yield mint
    authentikate_settings.cached_settings = None


async def _run(ctx: HttpContext, query: str, **variables: object) -> ExecutionResult:
    return await schema.execute(query, context_value=ctx, variable_values=variables or None)


def _refused(result: ExecutionResult, reason: str) -> None:
    assert result.errors, "it was let through"
    assert result.errors[0].extensions.get("reason") == reason, result.errors


@sync_to_async
def _room(title: str, *texts: str) -> tuple[kammer_models.Room, list[kammer_models.Message]]:
    """A room of the organization, with one agent posting ``texts`` into it."""
    org = Organization.objects.get(identifier="static_issuer#static_org")
    user = User.objects.get(sub="1", iss="static_issuer")
    room = kammer_models.Room.objects.for_write().create(title=title, organization=org, creator=user)
    agent = kammer_models.Agent.objects.for_write().create(room=room, client=Client.objects.get(client_id="oinsoins"), user=user, name=f"{title} agent")
    return room, [kammer_models.Message.objects.for_write().create(room=room, agent=agent, text=text) for text in texts]


@sync_to_async
def _collaboration(*objects: kammer_models.Room | kammer_models.Message) -> Collaboration:
    """A collaboration of the organization holding ``objects``, as a full member puts them in."""
    collaboration = Collaboration.objects.create(organization=Organization.objects.get(identifier="static_issuer#static_org"), name="Shared")
    for obj in objects:
        collaboration_items.add(collaboration, obj)
    return collaboration


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_guest_reads_the_room_in_their_collaboration_and_nothing_else(authenticated_context, guest):
    shared, (hello, _) = await _room("Shared", "hello", "world")
    other, (secret,) = await _room("Other", "a secret")
    ctx = guest({await _collaboration(shared): []})

    listed = await _run(ctx, ROOMS)
    assert not listed.errors, listed.errors
    assert [room["id"] for room in listed.data["rooms"]] == [str(shared.id)]
    read = await _run(ctx, ROOM, id=str(shared.id))
    assert not read.errors, read.errors
    assert sorted(m["text"] for m in read.data["room"]["messages"]) == ["hello", "world"]
    assert {m["agent"]["name"] for m in read.data["room"]["messages"]} == {"Shared agent"}
    assert read.data["room"]["agents"] == [{"name": "Shared agent"}]

    messages = await _run(ctx, MESSAGES)
    assert not messages.errors, messages.errors
    assert str(secret.id) not in {m["id"] for m in messages.data["messages"]}
    assert len(messages.data["messages"]) == 2
    assert (await _run(ctx, ROOM, id=str(other.id))).errors
    assert (await _run(ctx, MESSAGE, id=str(secret.id))).errors
    assert (await _run(ctx, MESSAGE, id=str(hello.id))).data["message"]["text"] == "hello"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_message_is_shared_with_its_room_not_alone(authenticated_context, guest):
    room, (message,) = await _room("Room", "only this")
    # Alone, its room would be unreadable where it points at it: the room is put in instead.
    with pytest.raises(collaboration_items.SharedWithItsWhole):
        await _collaboration(message)
    assert not await sync_to_async(CollaborationItem.objects.exists)()

    ctx = guest({await _collaboration(room, message): []})  # with its room, it is in already
    read = await _run(ctx, MESSAGE, id=str(message.id))
    assert not read.errors, read.errors
    assert read.data["message"]["agent"]["name"] == "Room agent"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_who_made_and_posts_in_a_shared_room_comes_with_it(authenticated_context, guest):
    room, _ = await _room("Room", "hi")
    ctx = guest({await _collaboration(room): []})

    read = await _run(
        ctx,
        "query ($id: ID!) { room(id: $id) { creator { sub activeOrganization { identifier } } organization { identifier } agents { user { sub } client { clientId } } } }",
        id=str(room.id),
    )
    assert not read.errors, read.errors
    assert read.data["room"] == {
        # Who is at work where is theirs, not the room's.
        "creator": {"sub": "1", "activeOrganization": None},
        "organization": {"identifier": "static_issuer#static_org"},
        "agents": [{"user": {"sub": "1"}, "client": {"clientId": "oinsoins"}}],
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_what_a_message_was_posted_about_comes_along_when_it_is_posted_later(authenticated_context, guest):
    room, _ = await _room("Room")
    ctx = guest({await _collaboration(room): []})

    posted = await _run(_context("test"), SEND, input={"room": str(room.id), "agentId": "member", "text": "look", "attachStructures": [{"identifier": "@mikro/image", "object": 7}]})
    assert not posted.errors, posted.errors

    read = await _run(ctx, MESSAGE, id=posted.data["send"]["id"])
    assert not read.errors, read.errors
    assert read.data["message"]["attachedStructures"] == [{"identifier": "@mikro/image", "object": 7}]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_no_provider_model_or_collection_is_shown_to_a_guest_or_put_in_a_collaboration(authenticated_context, guest):
    room, _ = await _room("Room", "hi")

    @sync_to_async
    def seed() -> llm_models.Provider:
        org = Organization.objects.get(identifier="static_issuer#static_org")
        provider = llm_models.Provider.objects.for_write().create(name="Secret provider", organization=org, api_key="sk-do-not-leak")
        model = llm_models.LLMModel.objects.for_write().create(provider=provider, model_id="secret-model", label="Secret", features=["embedding"])
        vector_models.ChromaCollection.objects.for_write().create(name="secret-docs", embedder=model, organization=org)
        return provider

    provider = await seed()
    collaboration = await _collaboration(room)
    ctx = guest({collaboration: ["alpaka_editor"]})

    for field in ("providers", "llmModels", "chromaCollections"):
        listed = await _run(ctx, f"{{ {field} {{ id }} }}")
        assert not listed.errors, listed.errors
        assert listed.data[field] == []
    assert (await _run(ctx, "query ($id: ID!) { provider(id: $id) { id } }", id=str(provider.id))).errors
    # Root fields handing out values computed from many rows are closed to guests.
    _refused(await _run(ctx, "{ roomStats { count } }"), "COLLABORATION_DOES_NOT_REACH")

    put = await _run(_context("test"), "mutation ($input: CollaborationObjectInput!) { addToCollaboration(input: $input) { id } }", input={"collaboration": str(collaboration.pk), "identifier": "@alpaka/provider", "object": str(provider.id)})
    assert put.errors and "never put in a collaboration" in put.errors[0].message, put.errors
    assert await CollaborationItem.objects.filter(collaboration=collaboration).acount() == 1  # the room alone


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_full_member_shares_a_room_over_graphql(authenticated_context, guest):
    room, _ = await _room("Room", "hi")
    member = _context("test")
    made = await _run(member, 'mutation { createCollaboration(input: {name: "With a guest"}) { id } }')
    assert not made.errors, made.errors
    collaboration = made.data["createCollaboration"]["id"]
    put = await _run(member, "mutation ($input: CollaborationObjectInput!) { addToCollaboration(input: $input) { items { identifier } } }", input={"collaboration": collaboration, "identifier": "@alpaka/room", "object": str(room.id)})
    assert not put.errors, put.errors
    assert put.data["addToCollaboration"]["items"] == [{"identifier": "@alpaka/room"}]

    ctx = guest({await Collaboration.objects.aget(pk=collaboration): []})
    assert [r["id"] for r in (await _run(ctx, ROOMS)).data["rooms"]] == [str(room.id)]
    assert [c["id"] for c in (await _run(ctx, "{ collaborations { id } }")).data["collaborations"]] == [collaboration]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_editor_in_the_collaboration_posts_there_and_only_there(authenticated_context, guest):
    room, _ = await _room("Room", "hi")
    other, _ = await _room("Other", "private")
    ctx = guest({await _collaboration(room): ["alpaka_editor"]})

    posted = await _run(ctx, SEND, input={"room": str(room.id), "agentId": "guest", "text": "hello from outside"})
    assert not posted.errors, posted.errors
    read = await _run(ctx, ROOM, id=str(room.id))
    assert "hello from outside" in {m["text"] for m in read.data["room"]["messages"]}  # part of the room, so in the collaboration

    _refused(await _run(ctx, SEND, input={"room": str(other.id), "agentId": "guest", "text": "let me in"}), "SHARE_INSUFFICIENT")
    assert await kammer_models.Message.all_objects.filter(room=other).acount() == 1
    assert not await kammer_models.Agent.all_objects.filter(room=other, user__sub="20").aexists()  # its agent was taken back out


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_viewer_posts_nothing_and_no_guest_does_anything_else(authenticated_context, guest):
    room, _ = await _room("Room", "hi")
    collaboration = await _collaboration(room)
    editor = guest({collaboration: ["alpaka_editor"]})

    _refused(await _run(guest({collaboration: []}), SEND, input={"room": str(room.id), "agentId": "guest", "text": "hi"}), "INSUFFICIENT_ROLE")
    _refused(await _run(editor, "mutation ($input: DeleteRoomInput!) { deleteRoom(input: $input) }", input={"id": str(room.id)}), "SCOPED_READ_ONLY")
    _refused(await _run(editor, "mutation ($input: StartMessageInput!) { startMessage(input: $input) { id } }", input={"room": str(room.id), "agentId": "guest"}), "SCOPED_READ_ONLY")
    _refused(await _run(editor, 'mutation { createCollaboration(input: {name: "Mine"}) { id } }'), "SCOPED_READ_ONLY")
    assert await kammer_models.Message.all_objects.filter(room=room).acount() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_guest_calls_no_model_and_streams_nothing_outside_graphql(authenticated_context, guest):
    room, _ = await _room("Room")
    guest({await _collaboration(room): ["alpaka_editor"]})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=get_asgi_application()), base_url="http://testserver") as http:
        listed = await http.get("/llm/v1/models", headers={"Authorization": "Bearer guest"})
    assert listed.status_code == 401, listed.text
    assert "guest" in listed.json()["error"]["message"]

    socket = WebsocketCommunicator(consumers.MessageStreamConsumer.as_asgi(), "/kammer/stream/")
    connected, _ = await socket.connect()
    assert connected
    await socket.send_json_to({"type": "auth", "token": "guest"})
    assert (await socket.receive_json_from())["type"] == "error"
    assert (await socket.receive_output())["code"] == consumers.CLOSE_UNAUTHENTICATED


def _type_line(sdl: str, name: str) -> str:
    return next(line for line in sdl.splitlines() if line.startswith(f"type {name} "))


def test_the_schema_says_what_each_type_is_and_where_a_guest_may_post():
    sdl = str(schema)
    assert '@identified(by: "@alpaka/room")' in _type_line(sdl, "Room")
    send = next(line.strip() for line in sdl.splitlines() if line.strip().startswith("send("))
    assert send.endswith('@auth(required_scopes: ["alpaka_chat"], any_role_of: ["alpaka_editor"], allow_scoped: true)'), send
